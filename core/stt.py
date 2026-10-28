"""
تبدیل گفتار به متن برای جستجوی صوتی (core/voice_search.py).

## قرارداد موتورها

هر موتور یه کلاسه با یه متد:

    transcribe(pcm, language, timeout) -> str

  * pcm      -- صدای خامِ PCM شونزده‌بیتی little-endian، مونو، ۱۶ کیلوهرتز.
                voice_search قبل از صدا زدن، صدای تیم‌تاک رو به همین شکل
                درآورده؛ پس هیچ موتوری با فرمت ورودی درگیر نمی‌شه.
  * language -- کد BCP-47 مثل fa-IR یا en-US. رشته‌ی خالی یعنی «خودت تشخیص
                بده» (فقط برای موتوری که SUPPORTS_AUTO_LANGUAGE داره).
  * خروجی   -- متنِ شنیده‌شده. رشته‌ی خالی یعنی «هیچ کلمه‌ای فهمیده نشد».
  * خطا      -- فقط SpeechToTextError، با پیامی که نشون دادنش به کاربر امنه.

اضافه‌کردن موتور جدید یعنی *یه کلاس* با @register؛ اسمش خودکار توی
`vss engine` قابل‌انتخاب می‌شه و بقیه‌ی زنجیره (ضبط، پاک‌سازی، پیام‌ها،
جستجو) دست نمی‌خوره:

    @register
    class MyEngine(Engine):
        NAME = "mine"

        def transcribe(self, pcm, language, timeout):
            request = urllib.request.Request("https://...", data=pcm, method="POST")
            raw = perform(request, timeout, secrets=[self.settings.get("my_key")])
            return json.loads(raw)["text"]

## موتورهای موجود

  * google -- همون endpoint رایگانِ Web Speech که کتابخونه‌ی SpeechRecognition
    استفاده می‌کنه. هر زبانی که گوگل می‌شناسه (fa-IR، en-US، ar-SA، ...)، بدون
    ثبت‌نام. تشخیص خودکار زبان نداره.
  * openai -- هر سروری که `/v1/audio/transcriptions` سازگار با OpenAI داره:
    خودِ OpenAI، Groq، یا یه faster-whisper محلی. آدرس، کلید و مدل قابل
    تنظیمه؛ زبان اختیاریه (خالی = تشخیص خودکار).

## شبکه

فقط کتابخونه‌ی استاندارد (urllib). پروکسیِ خودِ ربات (core/proxy_state)
رعایت می‌شه، چون از ایران نه گوگل در دسترسه نه OpenAI. urllib فقط پروکسی
http/https رو می‌شناسه؛ برای پروکسی socks به‌جای یه timeout مبهم، همون اول
پیام روشن داده می‌شه. سروری که روی همین سیستم یا شبکه‌ی داخلیه (مثلاً
faster-whisper روی 127.0.0.1) همیشه مستقیم صدا زده می‌شه، نه از پروکسی.

## حریم خصوصی

هیچ‌چیز روی دیسک نوشته نمی‌شه: WAV و بدنه‌ی multipart فقط توی حافظه
ساخته می‌شن. پیام خطاها هیچ‌وقت کلید API یا آدرس کامل (کلید گوگل توی
آدرسه) رو ندارن، و خطای اصلی با `from None` زنجیر نمی‌شه تا توی
traceback لاگ هم نیاد.
"""

import http.client
import ipaddress
import json
import re
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from core import config_defaults
from core import proxy_state

#: نرخ نمونه‌برداریِ ورودیِ همه‌ی موتورها.
SAMPLE_RATE = 16000

#: سقف اندازه‌ی جواب سرور. جواب یه تشخیص گفتار چند کیلوبایته؛ هر چیز
#: خیلی بزرگ‌تر یعنی یه صفحه‌ی اشتباه (مثلاً صفحه‌ی فیلترینگ).
MAX_RESPONSE_BYTES = 1024 * 1024

USER_AGENT = "TeamTalkAudioBot-VoiceSearch/1.0"


class SpeechToTextError(ValueError):
    """
    خطای قابل‌نمایش به کاربر. هیچ‌وقت کلید API یا آدرس کامل توش نیست.

    عمداً از ValueError ارث می‌بره (نه فقط Exception خام): این دقیقاً همون
    قراردادیه که core/logging_setup.py:safe_error_text با آن آشناست --
    فقط یه ValueError/LookupError با پیامِ کوتاه و تمیزِ *خودِ همین پروژه*
    عیناً به کاربر نشون داده می‌شه؛ core/voice_search.py هم به‌جای str(e)
    خام، همیشه از همون safe_error_text عبور می‌ده.
    """


class TransientSpeechError(SpeechToTextError):
    """
    خطای موقتیِ سرویس (timeout بی‌جواب، 429، 5xx، قطعیِ اتصال). kind یکی از
    "timeout" / "throttle" / "server" / "network" است. فقط این خطاها ارزشِ
    یک تلاشِ دوباره (از مسیرِ دیگه) و ثبتِ cooldown رو دارن.
    """

    def __init__(self, message, kind="network"):
        super().__init__(message)
        self.kind = kind


class SpeechThrottledError(SpeechToTextError):
    """
    سرویس (معمولاً گوگلِ رایگان) موقتاً درخواست‌ها رو محدود کرده و ما داریم
    cooldown می‌دیم. retry_after ثانیه‌ی باقی‌مونده‌ست؛ متنش عمداً خنثیه چون
    voice_search پیامِ i18n رو خودش می‌سازه.
    """

    def __init__(self, retry_after, engine="google"):
        super().__init__(f"{engine} is temporarily limiting requests, retry in {int(retry_after)}s")
        self.retry_after = max(1, int(retry_after))
        self.engine = engine


_ENGINES = {}


def register(cls):
    """یه موتور رو با اسم NAME ثبت می‌کنه (دکوراتور)."""
    if not cls.NAME:
        raise ValueError("engine needs a NAME")
    _ENGINES[cls.NAME] = cls
    return cls


def engine_names():
    return sorted(_ENGINES)


def engine_class(name):
    return _ENGINES.get(name)


def create_engine(name, settings):
    cls = _ENGINES.get(name)
    if cls is None:
        raise SpeechToTextError(f"unknown speech recognition engine '{name}'")
    return cls(settings)


class Engine:
    NAME = ""
    #: آیا زبان خالی (تشخیص خودکار) رو قبول می‌کنه؟
    SUPPORTS_AUTO_LANGUAGE = False

    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def transcribe(self, pcm, language, timeout):
        raise NotImplementedError


# ---------------------------------------------------------------- محتوای درخواست


def wav_bytes(pcm, sample_rate=SAMPLE_RATE, channels=1):
    """
    PCM شونزده‌بیتی رو توی یه فایل WAV *در حافظه* می‌پیچه (هدر ۴۴ بایتی).

    ماژول wave عمداً استفاده نمی‌شه: هدر یه ساختار ثابته و این‌جوری هیچ
    مسیری که حتی به‌اشتباه یه فایل باز کنه وجود نداره.
    """
    frame = 2 * channels
    data = bytes(pcm[: len(pcm) - (len(pcm) % frame)])
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, sample_rate * frame, frame, 16,
        b"data", len(data),
    )
    return header + data


def multipart_body(fields, files, boundary=None):
    """
    بدنه‌ی multipart/form-data.

    fields: [(name, value)]، files: [(name, filename, content_type, bytes)].
    خروجی: (body, content_type_header)
    """
    boundary = boundary or "----voicesearch" + uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8"))
    for name, filename, content_type, data in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'.encode("utf-8")
            + bytes(data) + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------- شبکه


def is_local_url(url):
    """
    آدرس روی همین سیستم یا شبکه‌ی داخلیه؟ (localhost، 127.x، 10.x، 192.168.x،
    ...). اسم دامنه resolve نمی‌شه -- فقط چیزی که خودِ آدرس می‌گه.
    """
    host = (urllib.parse.urlsplit(url).hostname or "").strip("[]").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def open_url(request, timeout, route="auto"):
    """
    درخواست رو با رعایت پروکسیِ ربات می‌فرسته.

      * سرور محلی/داخلی -> مستقیم، بدون هیچ پروکسی‌ای (نه حتی پروکسی سیستم).
      * پروکسی http/https تنظیم شده -> از همون.
      * پروکسی socks -> خطای روشن؛ urllib باهاش کار نمی‌کنه و نتیجه‌اش فقط
        یه timeout بی‌توضیح می‌شد.
      * بدون پروکسی -> urlopen معمولی (همون رفتار بقیه‌ی درخواست‌های ربات).

    route: "auto" (پیش‌فرض) یا "direct" برای عبورِ عمدی از پروکسی (تلاشِ
    دومِ perform_resilient وقتی مسیرِ پروکسی جواب نداده بود).
    """
    url = request.full_url
    if route == "direct" and not is_local_url(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    if is_local_url(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)

    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        scheme = urllib.parse.urlsplit(proxy_url).scheme.lower()
        if scheme not in ("http", "https"):
            raise SpeechToTextError(
                f"speech recognition needs an http proxy, but the bot's proxy is {scheme}")
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        return opener.open(request, timeout=timeout)

    return urllib.request.urlopen(request, timeout=timeout)


def scrub(text, secrets=()):
    """کلیدها و هر key=... ای رو از یه متن خطا پاک می‌کنه."""
    text = str(text or "")
    for secret in secrets:
        if secret and len(str(secret)) >= 4:
            text = text.replace(str(secret), "***")
    return re.sub(r"(?i)(key=)[^&\s]+", r"\1***", text)


def _is_timeout(error):
    return isinstance(error, (socket.timeout, TimeoutError))


def _error_detail(http_error):
    """پیام خطای JSON سرور (مثلاً {"error": {"message": ...}})، اگه باشه."""
    try:
        raw = http_error.read(4096)
    except Exception:
        return ""
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message")
    elif isinstance(error, str):
        message = error
    else:
        message = data.get("message") or data.get("detail")
    if not isinstance(message, str):
        return ""
    return " ".join(message.split())[:160]


_HTTP_HINTS = {
    400: "the server rejected the audio or a setting",
    401: "check the API key",
    403: "check the API key",
    404: "check the server address",
    413: "the recording was too large",
    429: "rate limit or quota reached",
}


def perform(request, timeout, secrets=(), route="auto"):
    """
    درخواست رو می‌فرسته و بدنه‌ی جواب رو (bytes) برمی‌گردونه. هر شکست به یه
    SpeechToTextError کوتاه و بی‌کلید تبدیل می‌شه.
    """
    host = urllib.parse.urlsplit(request.full_url).hostname or "the server"
    try:
        with (open_url(request, timeout, route) if route != "auto" else open_url(request, timeout)) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except SpeechToTextError:
        raise
    except urllib.error.HTTPError as e:
        detail = _error_detail(e)
        hint = _HTTP_HINTS.get(e.code) or ("server error" if e.code >= 500 else "")
        text = f"{host} answered HTTP {e.code}"
        if hint:
            text += f" ({hint})"
        if detail:
            text += f": {detail}"
        if e.code == 429:
            raise TransientSpeechError(scrub(text, secrets), "throttle") from None
        if e.code >= 500:
            raise TransientSpeechError(scrub(text, secrets), "server") from None
        raise SpeechToTextError(scrub(text, secrets)) from None
    except urllib.error.URLError as e:
        if _is_timeout(e.reason):
            raise TransientSpeechError(f"{host} did not answer within {timeout:g}s", "timeout") from None
        raise TransientSpeechError(scrub(f"could not reach {host} ({e.reason})", secrets), "network") from None
    except OSError as e:
        if _is_timeout(e):
            raise TransientSpeechError(f"{host} did not answer within {timeout:g}s", "timeout") from None
        raise TransientSpeechError(scrub(f"could not reach {host} ({e})", secrets), "network") from None
    except http.client.HTTPException as e:
        raise TransientSpeechError(f"the connection to {host} broke ({type(e).__name__})", "network") from None
    except ValueError:
        # urllib برای آدرس خراب ValueError می‌ده و متنش خودِ آدرسه؛ نشونش نمی‌دیم.
        raise SpeechToTextError("the speech recognition server address is invalid") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise SpeechToTextError(f"{host} sent an unexpectedly large answer")
    return body


# ---------------------------------------------------------------- تاب‌آوری

#: هر تلاش حداکثر این‌قدر منتظر می‌مونه. گوگلِ رایگان وقتی محدود می‌کنه
#: *هیچ جوابی* نمی‌ده (اندازه‌گیریِ زنده: جواب‌های سالم ۱ تا ۳ ثانیه، بقیه
#: تا آخرِ مهلت ساکت)؛ پس دو تلاشِ کوتاه شانسِ بیشتری از یه انتظارِ بلند دارن.
ATTEMPT_TIMEOUT_CAP = 10.0
RETRY_BACKOFF_SECONDS = 0.6
#: حداقل فاصله‌ی دو درخواست به یه سرویسِ رایگان (پشت‌سرهم زدن = محدودیت).
MIN_REQUEST_INTERVAL = 1.5
#: cooldown بعد از شکستِ هر دو تلاش؛ با شکستِ پشت‌سرهم دو برابر می‌شه.
COOLDOWN_BASE_SECONDS = 30.0
COOLDOWN_MAX_SECONDS = 300.0

_now = time.monotonic
_sleep = time.sleep
#: کلید -> {"until", "fails", "last"}. فقط توی حافظه‌ی همین پروسه؛ خودِ
#: کلیدِ API هش می‌شه تا هیچ‌جا نگه‌داری/چاپ نشه.
_guard = {}


def _guard_state(guard_key):
    return _guard.setdefault(guard_key, {"until": 0.0, "fails": 0, "last": 0.0})


def cooldown_remaining(guard_key):
    return max(0.0, _guard_state(guard_key)["until"] - _now())


def reset_guards():
    _guard.clear()


def _other_route(route):
    """مسیرِ جایگزین: اگه پروکسی فعاله و با اون رفتیم -> مستقیم، و برعکس."""
    if not proxy_state.get_proxy_url():
        return route
    return "direct" if route == "auto" else "auto"


def perform_resilient(request, timeout, secrets=(), route="auto"):
    """
    perform() + یک تلاشِ دوباره (از مسیرِ دیگه‌ی پروکسی/مستقیم) با backoffِ
    کوتاه برای timeout/429/5xx، محدودکننده‌ی نرخ، و cooldown بعد از شکست:
    وقتی cooldown فعاله فوراً SpeechThrottledError می‌ده، بدونِ هیچ انتظاری.
    """
    host = urllib.parse.urlsplit(request.full_url).hostname or ""
    guard_key = f"{host}:{hash(''.join(secrets))}"
    state = _guard_state(guard_key)
    remaining = state["until"] - _now()
    if remaining > 0:
        raise SpeechThrottledError(remaining + 0.999)

    wait = MIN_REQUEST_INTERVAL - (_now() - state["last"])
    if 0 < wait <= MIN_REQUEST_INTERVAL:
        _sleep(wait)

    attempt_timeout = min(float(timeout), ATTEMPT_TIMEOUT_CAP)
    for attempt in range(2):
        state["last"] = _now()
        try:
            body = perform(request, attempt_timeout, secrets, route)
            state["fails"] = 0
            return body
        except TransientSpeechError:
            if attempt == 0:
                _sleep(RETRY_BACKOFF_SECONDS)
                route = _other_route(route)

    state["fails"] += 1
    cooldown = min(COOLDOWN_BASE_SECONDS * (2 ** (state["fails"] - 1)), COOLDOWN_MAX_SECONDS)
    state["until"] = _now() + cooldown
    raise SpeechThrottledError(cooldown) from None


def fallback_engine_names(name, settings):
    """موتورهای دیگه‌ای که *واقعاً تنظیم شده‌ان* (جایگزینِ موقتِ google)."""
    names = []
    if name != "openai":
        base = (settings.get("openai_base_url") or "").strip()
        if (settings.get("openai_api_key") or "").strip() or (
                base and base != OpenAIEngine.DEFAULT_BASE_URL and is_local_url(base)):
            names.append("openai")
    return names


def transcribe_with_fallback(name, settings, pcm, language, timeout):
    """
    با موتورِ انتخاب‌شده تشخیص می‌ده؛ اگه محدود/بی‌جواب بود و موتورِ دیگه‌ای
    تنظیم شده، همون رو امتحان می‌کنه. وگرنه SpeechThrottledError برمی‌گرده.
    """
    try:
        return create_engine(name, settings).transcribe(pcm, language, timeout)
    except SpeechThrottledError:
        for other in fallback_engine_names(name, settings):
            try:
                return create_engine(other, settings).transcribe(pcm, language, timeout)
            except SpeechToTextError:
                continue
        raise


# ---------------------------------------------------------------- موتورها


@register
class GoogleEngine(Engine):
    """
    Endpoint رایگانِ Google Web Speech (همون که SpeechRecognition صدا می‌زنه).

    بدنه PCM خامه با `audio/l16; rate=16000` (little-endian، مثل خروجی
    `rec`/WAV که مستندات همین endpoint با اون تأییدش کرده). جواب چند خط JSON
    جداست؛ خط اول معمولاً `{"result":[]}` خالیه و نتیجه‌ی واقعی بعدشه.
    """

    NAME = "google"
    SUPPORTS_AUTO_LANGUAGE = False
    ENDPOINT = "https://www.google.com/speech-api/v2/recognize"
    #: کلید عمومی‌ای که SpeechRecognition (و خودِ کرومیوم) استفاده می‌کنن.
    PUBLIC_KEY = config_defaults.GOOGLE_STT_PUBLIC_KEY
    FALLBACK_LANGUAGE = "en-US"

    def _key(self):
        return (self.settings.get("google_key") or "").strip() or self.PUBLIC_KEY

    def build_request(self, pcm, language):
        query = urllib.parse.urlencode({
            "client": "chromium",
            "lang": language or self.FALLBACK_LANGUAGE,
            "key": self._key(),
        })
        return urllib.request.Request(
            f"{self.ENDPOINT}?{query}",
            data=bytes(pcm),
            headers={
                "Content-Type": f"audio/l16; rate={SAMPLE_RATE}",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

    @staticmethod
    def parse_response(text):
        """
        بهترین متن از جواب چندخطی. "" یعنی گوگل چیزی نفهمید. جوابی که اصلاً
        JSON نیست (مثلاً صفحه‌ی HTML فیلترینگ) خطاست، نه «چیزی نفهمید».
        """
        saw_json = False
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            saw_json = True
            results = data.get("result") if isinstance(data, dict) else None
            if not isinstance(results, list) or not results:
                continue
            first = results[0]
            alternatives = first.get("alternative") if isinstance(first, dict) else None
            if not isinstance(alternatives, list):
                continue
            candidates = [a for a in alternatives
                          if isinstance(a, dict) and str(a.get("transcript") or "").strip()]
            if not candidates:
                continue
            scored = [a for a in candidates if isinstance(a.get("confidence"), (int, float))]
            best = max(scored, key=lambda a: a["confidence"]) if scored else candidates[0]
            return " ".join(str(best["transcript"]).split())
        if not saw_json and (text or "").strip():
            raise SpeechToTextError("unexpected answer from Google (not speech results)")
        return ""

    def transcribe(self, pcm, language, timeout):
        request = self.build_request(pcm, language)
        raw = perform_resilient(request, timeout, secrets=[self._key()])
        return self.parse_response(raw.decode("utf-8", "replace"))


def whisper_language(language):
    """fa-IR -> fa. Whisper فقط کد زبان (بدون منطقه) می‌خواد؛ "" یعنی تشخیص خودکار."""
    return (language or "").split("-")[0].strip().lower()


@register
class OpenAIEngine(Engine):
    """
    هر سرور سازگار با `POST /v1/audio/transcriptions` از OpenAI.

    openai_base_url مثل SDK خودِ OpenAI تا /v1 نوشته می‌شه:
      https://api.openai.com/v1           (پیش‌فرض)
      https://api.groq.com/openai/v1      (Groq، مدل whisper-large-v3)
      http://127.0.0.1:8000/v1            (faster-whisper محلی)
    آدرسی که خودش به /audio/transcriptions ختم بشه همون‌طور استفاده می‌شه، و
    آدرسی که اصلاً مسیر نداره /v1 می‌گیره.
    """

    NAME = "openai"
    SUPPORTS_AUTO_LANGUAGE = True
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "whisper-1"

    def _key(self):
        return (self.settings.get("openai_api_key") or "").strip()

    def endpoint(self):
        base = (self.settings.get("openai_base_url") or self.DEFAULT_BASE_URL).strip().rstrip("/")
        if base.endswith("/audio/transcriptions"):
            return base
        if urllib.parse.urlsplit(base).path in ("", "/"):
            base += "/v1"
        return base + "/audio/transcriptions"

    def build_request(self, pcm, language):
        fields = [
            ("model", (self.settings.get("openai_model") or self.DEFAULT_MODEL).strip()),
            ("response_format", "json"),
        ]
        code = whisper_language(language)
        if code:
            fields.append(("language", code))
        body, content_type = multipart_body(
            fields, [("file", "speech.wav", "audio/wav", wav_bytes(pcm))])
        headers = {
            "Content-Type": content_type,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self._key():
            headers["Authorization"] = f"Bearer {self._key()}"
        return urllib.request.Request(self.endpoint(), data=body, headers=headers, method="POST")

    @staticmethod
    def parse_response(text):
        try:
            data = json.loads(text)
        except ValueError:
            raise SpeechToTextError("unexpected answer from the transcription server") from None
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return " ".join(data["text"].split())
        raise SpeechToTextError("the transcription server answered without text")

    def transcribe(self, pcm, language, timeout):
        request = self.build_request(pcm, language)
        raw = perform(request, timeout, secrets=[self._key()])
        return self.parse_response(raw.decode("utf-8", "replace"))
