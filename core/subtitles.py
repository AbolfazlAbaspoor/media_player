"""
زیرنویس زنده‌ی آهنگِ در حال پخش، به‌صورت پیام خصوصی (دستور sub).

    sub            روشن/خاموش (برای هر کاربر جدا؛ پیش‌فرض خاموش)
    sub <lang>     زبان رو ست می‌کنه و روشن می‌کنه (مثلاً sub fa، sub en)

## چطور کار می‌کنه

  * برای آیتمِ فعلی، زیرنویس با yt-dlp گرفته می‌شه (writesubtitles +
    writeautomaticsub + subtitleslangs؛ مثلِ سرویس یوتیوب: پروکسیِ
    core.proxy_state، کوکیِ همون سرویس، js runtime). **زیرنویسِ دستی بر
    خودکار ارجحیت داره.** هیچ‌چیز روی دیسک نوشته نمی‌شه: متنِ VTT/SRT فقط
    توی حافظه parse می‌شه و با عوضِ شدنِ آهنگ دور ریخته می‌شه.
  * هر cue (شروع، پایان، متن) در لحظه‌ی خودش -- با bot.player.position_seconds --
    به هر کاربری که روشنش کرده *خصوصی* فرستاده می‌شه.
  * pause، seek (به جلو و عقب) و عوض‌شدنِ آهنگ (زیرنویسِ آیتم جدید از نو
    گرفته و هم‌زمان می‌شه) پوشش داده شدن -- منطقِ زمان‌بندی توی Cursor است
    که کاملاً خالصه (بدون شبکه/mpv) و آفلاین تست می‌شه.

## هزینه (این پروژه برای هزاران ربات روی یه سرور طراحی شده)

هیچ ترد یا تایمرِ جدایی نداریم. tick() از همون حلقه‌ی housekeepingِ
bot.py (هر نیم‌ثانیه) صدا زده می‌شه و تا وقتی حتی یه کاربر زیرنویس رو روشن
نکرده، همون خطِ اول برمی‌گرده: نه IPCِ mpv، نه شبکه، نه حافظه. گرفتنِ
زیرنویس (شبکه) توی استخرِ مشترکِ core.workers انجام می‌شه نه توی حلقه.

## حریمِ خصوصی

وضعیتِ هر کاربر فقط توی حافظه و به‌ازای یوزرنیمِ تیم‌تاکشه؛ با خروج از
سرور (user_logged_out) یا قطعِ اتصالِ خودِ ربات پاک می‌شه.
"""

import bisect
import collections
import html
import re
import threading

from core import config_defaults
from core import error_reasons
from core import i18n
from core import logging_setup
from core import net
from core import proxy_retry
from core import workers
from core import ytdlp_opts

Cue = collections.namedtuple("Cue", "start end text")

# سقفِ حجمِ فایلِ زیرنویس (بایت)؛ یه سرورِ بدجنس/فایلِ عظیم حافظه رو پر نکنه.
MAX_SUBTITLE_BYTES = 2 * 1024 * 1024

# سقفِ طولِ متنِ هر پیامِ زیرنویس (یه cue خراب نباید یه دیوار متن بشه).
MAX_CUE_CHARS = 300

# ترجیحِ فرمت: vtt اول (یوتیوب همیشه داره)، بعد srt.
_FORMAT_PREFERENCE = ("vtt", "srt")

_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8}){0,2}$")


# ------------------------------------------------------------- parse

_TIMESTAMP_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?$")
_TAG_RE = re.compile(r"<[^>]*>")
_ASS_RE = re.compile(r"\{[^}]*\}")
_SPACE_RE = re.compile(r"\s+")


def _parse_timestamp(token):
    """'00:01:02.500' / '01:02,500' / '01:02.5' -> ثانیه (float)، یا None."""
    match = _TIMESTAMP_RE.match((token or "").strip())
    if not match:
        return None
    hours, minutes, seconds, frac = match.groups()
    millis = int((frac or "0").ljust(3, "0"))
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + millis / 1000.0


def _clean_line(line):
    """تگ‌های استایل (<c>, <i>, <00:00:01.000>, {\\an8}) و اینتیتی‌ها رو برمی‌داره."""
    line = _TAG_RE.sub("", line)
    line = _ASS_RE.sub("", line)
    line = html.unescape(line).replace("\xa0", " ")
    return _SPACE_RE.sub(" ", line).strip()


def _timing(line):
    """خطِ «شروع --> پایان [تنظیمات]» -> (start, end)، یا None اگه این شکلی نیست."""
    if "-->" not in line:
        return None
    start_raw, _, rest = line.partition("-->")
    rest = rest.strip().split()
    start = _parse_timestamp(start_raw)
    end = _parse_timestamp(rest[0]) if rest else None
    if start is None or end is None:
        return None
    return start, max(end, start)


def parse_cues(text):
    """
    متنِ VTT یا SRT -> لیستِ Cue(start, end, text) مرتب بر اساسِ شروع.

    text هر cue ممکنه چند خط داشته باشه (با 
)، تا dedupe_rolling بتونه
    خط‌به‌خط مقایسه کنه. cue بدونِ متنِ واقعی (فقط تگ) حذف می‌شه. بلوک‌های
    WEBVTT/NOTE/STYLE/REGION چون قبلشون هیچ خطِ زمانی نیست خودبه‌خود رد
    می‌شن، و شماره‌ی ردیفِ SRT cue رو تموم می‌کنه.

    جداکننده‌ی cueها فقط خطِ *کاملاً خالی*ـه، نه هر خطِ سفیدنما: زیرنویسِ
    خودکارِ یوتیوب بعد از هر خطِ زمانی یه خطِ تک‌فاصله‌ای می‌ذاره، و اگه اون
    جداکننده حساب می‌شد متنِ واقعیِ cue به یه بلوکِ بی‌زمان می‌افتاد و گم می‌شد.
    """
    if not text:
        return []
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cues = []
    current = None  # [start, end, [خطوط]]

    def flush():
        if current is not None:
            body = [clean for clean in (_clean_line(item) for item in current[2]) if clean]
            if body:
                cues.append(Cue(current[0], current[1], "\n".join(body)))

    for position, line in enumerate(lines):
        timing = _timing(line)
        if timing is not None:
            flush()
            current = [timing[0], timing[1], []]
        elif line == "":
            # خطِ خالیِ بلافاصله بعد از خطِ زمانی (هنوز هیچ متنی نیومده) جداکننده
            # حساب نمی‌شه: اگه یه پروکسی/ادیتور «خطِ تک‌فاصله»ی یوتیوب رو به
            # خطِ خالی تبدیل کرده باشه، متنِ واقعی همچنان مالِ همین cue است.
            if current is None or any(item.strip() for item in current[2]):
                flush()
                current = None
        elif current is not None:
            if line.strip().isdigit() and position + 1 < len(lines) and _timing(lines[position + 1]):
                flush()
                current = None
            else:
                current[2].append(line)
    flush()
    cues.sort(key=lambda cue: cue.start)
    return cues


def dedupe_rolling(cues):
    """
    تکرارهای «رولینگ» زیرنویسِ خودکار رو حذف می‌کنه.

    یوتیوب برای زیرنویس خودکار هر cue رو دوخطی می‌سازه: خطِ اولش عیناً
    خطِ دومِ cueِ قبلیه و فقط خطِ دوم تازه‌ست (و بین این‌ها cueهای ۱۰ میلی‌ثانیه‌ای
    که همون متن رو تکرار می‌کنن). هر خط فقط یک‌بار -- اولین‌باری که
    می‌آد -- نگه داشته می‌شه. اگه متنِ تازه ادامه‌ی همون خطِ قبلی باشه (رشدِ
    کلمه‌به‌کلمه) فقط بخشِ اضافه می‌مونه. مقایسه با خطوطِ *خامِ* cueِ قبلی
    انجام می‌شه نه با چیزی که قبلاً فرستادیم.
    """
    out = []
    previous = []
    for cue in cues:
        lines = cue.text.split("\n")
        fresh = []
        for line in lines:
            if line in previous:
                continue
            for old in previous:
                if old and line.startswith(old) and len(line) > len(old):
                    line = line[len(old):].strip()
                    break
            if line:
                fresh.append(line)
        previous = lines
        if fresh:
            out.append(Cue(cue.start, cue.end, "\n".join(fresh)))
        elif out and cue.end > out[-1].end:
            # cue کاملاً تکراری بود: فقط پنجره‌ی نمایشِ cueِ قبلی رو دراز می‌کنه.
            out[-1] = out[-1]._replace(end=cue.end)
    return out


def merge_repeats(cues):
    """دو cueِ پشت‌سرهمِ هم‌متن که زمانشون به هم می‌رسه یکی می‌شن (برای زیرنویسِ دستی هم امنه)."""
    out = []
    for cue in cues:
        if out and out[-1].text == cue.text and cue.start <= out[-1].end:
            out[-1] = out[-1]._replace(end=max(out[-1].end, cue.end))
        else:
            out.append(cue)
    return out


def message_text(cue):
    """متنِ پیامِ خصوصیِ یه cue (چندخطی -> یک خط، با سقفِ طول)."""
    text = cue.text.replace("\n", " ")
    return text if len(text) <= MAX_CUE_CHARS else text[:MAX_CUE_CHARS - 1] + "…"


# ---------------------------------------------------------- زمان‌بندی

class Cursor:
    """
    مکان‌نمای پخشِ زیرنویس برای *یک کاربر* روی یک لیستِ cue.

    poll(position) cueهایی رو برمی‌گردونه که از poll قبلی تا حالا به
    موعدشون رسیدن. حالت‌ها:

      * عادی: فقط cueهای تازه‌ای که شروعشون به position رسیده (هر cue فقط
        یک‌بار). اگه حلقه‌ی اصلی یه لحظه گیر کرده باشه حداکثر MAX_CATCHUP
        تای آخر رو می‌فرسته، نه یه سیل پیام.
      * pause: position تکون نمی‌خوره، پس چیزی تازه به موعد نمی‌رسه.
      * seek (عقب‌تر از BACK_TOLERANCE یا جلوتر از SEEK_GAP ثانیه) یا
        اولین poll: هم‌زمان‌سازیِ دوباره -- کرسر به position می‌پره و فقط
        cueِ در حالِ نمایش (اگه باشه) یک‌بار فرستاده می‌شه.
    """

    SEEK_GAP = 4.0
    BACK_TOLERANCE = 0.75
    MAX_CATCHUP = 2

    def __init__(self, cues):
        self.cues = cues
        self._starts = [cue.start for cue in cues]
        self._next = 0
        self._last_position = None

    def poll(self, position):
        if position is None:
            return []
        last = self._last_position
        self._last_position = position
        started = bisect.bisect_right(self._starts, position)
        if last is None or position < last - self.BACK_TOLERANCE or position - last > self.SEEK_GAP:
            self._next = started
            if started and self.cues[started - 1].end > position:
                return [self.cues[started - 1]]
            return []
        due = self.cues[self._next:started]
        self._next = max(self._next, started)
        return due[-self.MAX_CATCHUP:]


# ---------------------------------------------------- انتخابِ زیرنویس

def normalize_language(text):
    """'FA' / 'en_US' -> 'fa' / 'en-us'؛ کدِ نامعتبر -> None."""
    text = (text or "").strip()
    if not _LANG_RE.match(text):
        return None
    return text.replace("_", "-").lower()


def _match_language(table, lang):
    """کلیدِ جدول (مثلاً subtitles/automatic_captions) که به lang می‌خوره، یا None."""
    if not isinstance(table, dict) or not table:
        return None
    by_lower = {str(key).lower(): key for key in table}
    if lang in by_lower:
        return by_lower[lang]
    base = lang.split("-")[0]
    candidates = sorted((key for key in by_lower
                         if key == base or key.startswith(base + "-") or key.split("-")[0] == base),
                        key=lambda key: (len(key), key))
    return by_lower[candidates[0]] if candidates else None


def _pick_format(formats):
    by_ext = {}
    for fmt in formats or []:
        if isinstance(fmt, dict) and fmt.get("url") and fmt.get("ext"):
            by_ext.setdefault(str(fmt["ext"]).lower(), fmt)
    for ext in _FORMAT_PREFERENCE:
        if ext in by_ext:
            return by_ext[ext]
    return None


def choose_subtitle(info, lang):
    """
    از info ِ yt-dlp بهترین زیرنویس برای lang رو برمی‌گردونه:
    {"url", "ext", "kind": "manual"|"auto", "lang"} یا None. دستی همیشه بر
    خودکار می‌چربه، حتی اگه کدِ زبانِ خودکار دقیق‌تر جور باشه.
    """
    if not isinstance(info, dict):
        return None
    for kind, table in (("manual", info.get("subtitles")), ("auto", info.get("automatic_captions"))):
        key = _match_language(table, lang)
        if key is None:
            continue
        fmt = _pick_format(table[key])
        if fmt:
            return {"url": fmt["url"], "ext": str(fmt["ext"]).lower(), "kind": kind, "lang": key}
    return None


def _ytdlp_options(bot, lang):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [lang],
        "socket_timeout": 15,
        "retries": 2,
        "logger": logging_setup.get_ytdlp_logger(),
    }
    # همون کوکیِ سرویس یوتیوب (proxy رو proxy_retry خودش با وضعیتِ زنده‌ی
    # core.proxy_state اضافه می‌کنه).
    youtube = (getattr(bot, "services", None) or {}).get("youtube")
    cookiefile = getattr(youtube, "_cookiefile", None)
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return ytdlp_opts.with_js_runtime(opts)


def fetch_cues(bot, url, lang):
    """
    زیرنویسِ lang برای صفحه‌ی url: لیستِ Cue (خالی = چنین زیرنویسی نیست).
    خطای شبکه/yt-dlp raise می‌شه؛ فراخوان متنش رو هیچ‌وقت نشون نمی‌ده.
    """
    info = proxy_retry.extract_pooled("subtitles", _ytdlp_options(bot, lang), url, label="subtitles")
    chosen = choose_subtitle(info, lang)
    if chosen is None:
        return []
    _, body = net.fetch(chosen["url"], label="subtitles", max_bytes=MAX_SUBTITLE_BYTES)
    cues = parse_cues(body.decode("utf-8", errors="replace"))
    if chosen["kind"] == "auto":
        cues = dedupe_rolling(cues)
    return merge_repeats(cues)


# --------------------------------------------------------- وضعیتِ ربات

class _Ready:
    def __init__(self, cues):
        self.cues = cues


_LOADING = object()
_MISSING = object()


class _Failed:
    def __init__(self, reason=None):
        self.reason = reason


class _User:
    __slots__ = ("uid", "lang", "enabled", "cursor", "cursor_key", "notified_key")

    def __init__(self, uid, lang):
        self.uid = uid
        self.lang = lang
        self.enabled = True
        self.cursor = None
        self.cursor_key = None
        self.notified_key = None


class _State:
    def __init__(self):
        self.lock = threading.RLock()
        self.users = {}
        self.key = None
        self.tracks = {}


def _peek(bot):
    return getattr(bot, "_subtitle_state", None)


def _state(bot):
    st = _peek(bot)
    if st is None:
        st = bot._subtitle_state = _State()
    return st


def settings(bot):
    return config_defaults.feature_settings(bot, "subtitles", config_defaults.SUBTITLE_DEFAULTS)


def default_language(bot):
    configured = normalize_language(settings(bot).get("default_language"))
    if configured:
        return configured
    return normalize_language((getattr(bot, "cfg", None) or {}).get("language")) or "en"


def enabled_count(bot):
    st = _peek(bot)
    if st is None:
        return 0
    with st.lock:
        return sum(1 for user in st.users.values() if user.enabled)


def _reset_track(st, key):
    """آهنگِ تازه: زیرنویس‌ها و مکان‌نماها و «یک‌بار گفتن»ها از نو."""
    st.key = key
    st.tracks = {}
    for user in st.users.values():
        user.cursor = None
        user.cursor_key = None
        user.notified_key = None


def enable(bot, uid, username, lang=None):
    """کاربر رو (با زبانِ lang، یا آخرین زبانِ خودش/پیش‌فرض) روشن می‌کنه؛ زبانِ مؤثر."""
    st = _state(bot)
    with st.lock:
        user = st.users.get(username)
        if user is None:
            user = st.users[username] = _User(uid, lang or default_language(bot))
        else:
            user.uid = uid
            if lang:
                user.lang = lang
        user.enabled = True
        user.cursor = None
        user.cursor_key = None
        user.notified_key = None
        return user.lang


def disable(bot, username):
    st = _peek(bot)
    if st is None:
        return
    with st.lock:
        user = st.users.get(username)
        if user is not None:
            user.enabled = False
            user.cursor = None


def toggle(bot, uid, username):
    """(روشن؟، زبان)."""
    st = _state(bot)
    with st.lock:
        user = st.users.get(username)
        if user is not None and user.enabled:
            disable(bot, username)
            return False, user.lang
    return True, enable(bot, uid, username)


def forget(bot, username):
    """خروج از سرور: هیچ اثری از کاربر نمی‌مونه."""
    st = _peek(bot)
    if st is not None:
        with st.lock:
            st.users.pop(username, None)


def forget_all(bot):
    st = _peek(bot)
    if st is not None:
        with st.lock:
            st.users.clear()
            st.tracks = {}
            st.key = None


# ---------------------------------------------------------------- tick

def _track_key(bot, current_file):
    return (bot.queue.epoch, bot.queue.index, current_file)


def _current_public_url(bot):
    index = bot.queue.index
    meta = bot.track_meta[index] if index is not None and 0 <= index < len(bot.track_meta) else {}
    url = meta.get("public_url")
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else None


def _load(bot, st, key, lang, url):
    """(توی ترد کارگر) زیرنویس رو می‌گیره و نتیجه رو اگه هنوز همون آهنگه ثبت می‌کنه."""
    try:
        cues = fetch_cues(bot, url, lang)
        result = _Ready(cues) if cues else _MISSING
    except Exception as e:
        logging_setup.log_debug(f"subtitles: fetch failed ({logging_setup.safe_error_text(e)})")
        result = _Failed(error_reasons.describe(e))
    with st.lock:
        if st.key == key and st.tracks.get(lang) is _LOADING:
            st.tracks[lang] = result


def _ensure_loading(bot, st, key, lang):
    with st.lock:
        if lang in st.tracks:
            return
        url = _current_public_url(bot)
        if url is None:
            st.tracks[lang] = _MISSING
            return
        st.tracks[lang] = _LOADING
    try:
        workers.submit(_load, bot, st, key, lang, url)
    except Exception:
        with st.lock:
            st.tracks[lang] = _Failed()


def _send(bot, user, text):
    try:
        bot.t.user_message(user.uid, text)
    except Exception:
        logging_setup.log_debug("subtitles: private message failed")


def _notice_for(state, lang):
    if state is _MISSING:
        return i18n.t("sub_none", lang=lang)
    if isinstance(state, _Failed):
        text = i18n.t("sub_failed")
        return f"{text} ({state.reason})" if state.reason else text
    return None


def tick(bot, current_file, is_paused):
    """
    از حلقه‌ی housekeeping صدا زده می‌شه. بدونِ کاربرِ روشن تقریباً رایگانه.
    current_file همون player.current_url ِ همین دوره‌ست (None = چیزی پخش نمی‌شه).
    """
    st = _peek(bot)
    if st is None:
        return
    with st.lock:
        active = [(name, user) for name, user in st.users.items() if user.enabled]
    if not active:
        # حافظه‌ی زیرنویسِ آخرین آهنگ رو برای کسی نگه نمی‌داریم.
        if st.tracks:
            with st.lock:
                st.tracks = {}
                st.key = None
        return
    if current_file is None:
        with st.lock:
            _reset_track(st, None)
        return

    key = _track_key(bot, current_file)
    with st.lock:
        if key != st.key:
            _reset_track(st, key)
    for lang in {user.lang for _, user in active}:
        _ensure_loading(bot, st, key, lang)

    position = None
    if not is_paused:
        try:
            position = bot.player.position_seconds
        except Exception:
            position = None

    for _, user in active:
        with st.lock:
            state = st.tracks.get(user.lang)
            if isinstance(state, _Ready):
                if user.cursor_key != (key, user.lang):
                    user.cursor = Cursor(state.cues)
                    user.cursor_key = (key, user.lang)
                due = user.cursor.poll(position) if position is not None else []
                notice = None
            else:
                due = []
                notice = None
                if state is not None and state is not _LOADING and user.notified_key != key:
                    user.notified_key = key
                    notice = _notice_for(state, user.lang)
        if notice:
            _send(bot, user, notice)
        for cue in due:
            _send(bot, user, message_text(cue))


def safe_tick(bot, current_file, is_paused):
    """
    tick برای حلقه‌ی اصلی: هیچ‌وقت exception نمی‌ده. تیک هر نیم‌ثانیه صدا
    زده می‌شه، پس یه باگِ ماندگار نباید لاگ رو سیل کنه: فقط اولین خطا با
    traceback کامل ثبت می‌شه و بقیه debug.
    """
    try:
        tick(bot, current_file, is_paused)
    except Exception:
        if getattr(bot, "_subtitle_tick_failed", False):
            logging_setup.log_debug("subtitles tick failed again")
        else:
            bot._subtitle_tick_failed = True
            logging_setup.log_exception("subtitles tick")


# -------------------------------------------------------------- نصب

def install(bot):
    """یه‌بار موقعِ بالا اومدنِ ربات: رویدادهای خروج/قطعِ اتصال رو وصل می‌کنه."""
    bot.t.subscribe("user_logged_out")(lambda event: _on_logged_out(bot, event))
    # بعد از اتصالِ دوباره‌ی ربات شناسه‌ها معتبر نیستن و خروج‌های بین راه
    # رو ندیدیم؛ پس همه از نو روشن می‌کنن.
    bot.t.subscribe("connection_lost")(lambda event: forget_all(bot))
    bot.t.subscribe("connection_failed")(lambda event: forget_all(bot))
    bot.t.subscribe("kicked")(lambda event: _on_kicked(bot, event))


def _on_logged_out(bot, event):
    user = (event.get("params") or {}).get("user") or {}
    if user.get("username"):
        forget(bot, user["username"])


def _on_kicked(bot, event):
    # channel_id == 0 یعنی از کل سرور کیک شدیم؛ کیک از یه کانال اتصال رو نمی‌بره.
    if not (event.get("params") or {}).get("channel_id"):
        forget_all(bot)
