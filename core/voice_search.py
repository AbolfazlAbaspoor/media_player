"""
جستجوی صوتی: دستور `vs` صدای *همون یه نفر* رو ضبط می‌کنه، به متن تبدیل
می‌کنه، و دقیقاً همون کاری رو می‌کنه که `p <متن>` می‌کرد. تنظیماتش با
دستور `vss` (توضیح کامل توی docs/VOICE_SEARCH.md).

## مدل کلی

    vs  →  claim کردن تنها-یک-سشن  →  اشتراکِ صدای کاربر + روشن‌کردنِ
    audio block  →  صبر برای شروعِ حرف‌زدن (start_timeout)  →  جمع‌کردنِ
    صدا تا پایانِ حرف‌زدن (+ کمی مکث برای مطمئن‌شدن) یا سقفِ max_seconds
    →  همیشه: قطع اشتراک/رویداد  →  اگه خیلی کوتاه بود دور ریخته می‌شه
    →  تبدیل به ۱۶کیلوهرتز/مونو/۱۶بیتی  →  core/stt.py  →  اجرای همون
    مسیرِ جستجوی p (bot.commands["p"]) -- **نه یه پایپ‌لاینِ جستجوی جدا**.

رویدادهای تیم‌تاک (صدا/تغییرِ وضعیت/قطع‌اتصال) روی نخِ حلقه‌ی اصلی می‌رسن؛
دستورِ vs خودش روی نخِ مخصوصِ خودش (هر دستوری جدا thread داره، طبق
bot.py) منتظر می‌مونه. واسطِ بینشون یه `queue.Queue` سادهه -- تایمرها هم
همینجا (timeout روی queue.get)ان، نه توی حلقه‌ی اصلیِ ttbot.

## یک سشن در یک لحظه

`bot._voice_search_session` وضعیتِ سشنِ درحال‌اجرا رو نگه می‌داره (None
یعنی خالی). فقط یه نفر می‌تونه claim کنه؛ بقیه «مشغوله» می‌شنون. تمیزکاریِ
انتهایی (unsubscribe/disable/release) توی finally است، پس با هر خروجی
(موفق، timeout، خطا، لغو، قطع‌اتصال، رفتنِ کاربر) قطعاً اجرا می‌شه.

## ایمنیِ پخش (چرا صدای کاربر توی خروجیِ ربات نمیاد)

ربات فقط پخش می‌کنه؛ به‌طور عادی هیچ دستگاه خروجیِ تیم‌تاکی باز نداره. طبقِ
تحقیقی که توی core/teamtalk/ttbot.py (بالای بخشِ «جستجوی صوتی») مستند شده،
AudioBlock/USERSTATE_VOICE فقط وقتی میان که یه دستگاه خروجی باز باشه --
برای همین یه دستگاهِ *مجازیِ* تیم‌تاک باز می‌شه (فقط decode، بدون رسیدن به
هیچ کارت صدای واقعی)، نه یه دستگاه واقعی. mute/volume=0 عمداً استفاده
نشده: طبق همون تحقیق، توی این نسخه‌ی SDK بهره‌ی mute/volume روی خودِ
AudioBlock هم اثر می‌ذاره (فقط سکوت ضبط می‌شد).

## لایسنس

`voice_search` توی CAPABILITY_SERVICES و `cap_voice_search` توی
CAPABILITY_OF_FEATURE (licensing/catalog.py) ثبته. دیسپچرِ bot.py قبل از
اجرای `vs`/`vss` این رو چک می‌کنه -- برخلاف iptv/documentary، جستجوی صوتی
هیچ مسیرِ جایگزینی (مثل «عدد خام») نداره که از این چک رد بشه، پس نیازی به
چکِ دومِ داخلِ همین فایل نیست.

## حریمِ خصوصی

صدا **هیچ‌وقت** روی دیسک نوشته نمی‌شه: PCM/WAV/multipart فقط توی حافظه
ساخته می‌شن (core/stt.py) و با پایانِ سشن (موفق یا نه) از حافظه هم پاک
می‌شن. هیچ لاگی صدای خام یا متنِ تشخیص‌داده‌شده رو ذخیره نمی‌کنه؛ تنها اثرِ
یه جستجوی صوتی توی لاگ‌ها، همون برچسبِ عملیاتِ لحظه‌ای‌ست (مثل «در حالِ
تشخیصِ گفتار») -- دقیقاً هم‌سطحِ چیزی که `p <متن>` هم برای جستجوی متنی
لاگ می‌کنه.
"""

import queue
import sys
import threading
import time
from array import array

from core import command_helpers
from core import config_defaults
from core import i18n
from core import logging_setup
from core import manager
from core import stt

#: مقدارِ ثابتِ StreamType.STREAMTYPE_VOICE (core/teamtalk/TeamTalk5.py). عمداً
#: از اونجا import نمی‌شه: این ماژول نباید به بارگذاریِ DLL تیم‌تاک وابسته
#: باشه، چون تست‌های آفلاین (بدونِ DLL) باید بتونن همین منطق رو مستقیم اجرا
#: کنن. core/teamtalk/ttbot.py قبل از رسیدن به اینجا همه‌چیز رو به int/bool/bytes
#: ساده تبدیل می‌کنه.
STREAM_TYPE_VOICE = 1

DEFAULTS = config_defaults.VOICE_SEARCH_DEFAULTS

#: ترتیبِ نمایش توی «vss» (بدون آرگومان).
SETTINGS_ORDER = (
    "engine", "language", "service",
    "max_seconds", "start_timeout_seconds", "silence_seconds", "min_seconds",
    "request_timeout_seconds", "announce", "intercept",
    "openai_base_url", "openai_api_key", "openai_model", "google_key",
)

#: کلیدهایی که مقدارشون توی چت هیچ‌وقت کامل نشون داده نمی‌شه.
SECRET_KEYS = frozenset({"openai_api_key", "google_key"})

_BOOL_KEYS = frozenset({"announce", "intercept"})
#: کلید -> (حداقل, حداکثر) مجاز.
_RANGE_KEYS = {
    "max_seconds": (1.0, 120.0),
    "start_timeout_seconds": (1.0, 120.0),
    "silence_seconds": (0.1, 10.0),
    "min_seconds": (0.0, 10.0),
    "request_timeout_seconds": (1.0, 120.0),
}

_LANGUAGE_RE_SOURCE = r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$"

USAGE_VS = "vs [cancel | <language, e.g. en / fa-IR>]"
USAGE_VSS = "vss [<key> <value>]"


class VoiceSearchError(Exception):
    """خطای قابل‌نمایش به کاربر (busy/توی کانالم نیستی/خیلی کوتاه/...)."""


# ---------------------------------------------------------------- تنظیمات

def settings(bot):
    """تنظیماتِ جستجوی صوتی، با پر کردنِ جاهای خالی از پیش‌فرض (مثل iptv.settings)."""
    return config_defaults.feature_settings(bot, "voice_search", DEFAULTS)


def default_language_for_bot(bot):
    """زبانِ پیش‌فرض وقتی کلیدِ language خالیه: زبانِ خودِ ربات (fa->fa-IR, en->en-US)."""
    code = "en"
    try:
        code = (i18n.current_language() or ("en",))[0]
    except Exception:
        pass
    return {"fa": "fa-IR", "en": "en-US"}.get(code, "en-US")


def effective_language(bot, override=None):
    override = (override or "").strip()
    if override:
        return override
    configured = (settings(bot).get("language") or "").strip()
    return configured or default_language_for_bot(bot)


def looks_like_language_code(text):
    import re
    return bool(re.match(_LANGUAGE_RE_SOURCE, (text or "").strip()))


def validate(key, raw_value):
    """
    (value, error) رو برمی‌گردونه -- همیشه دقیقاً یکیشون None نیست. error
    (اگه باشه) یه کدِ ساده‌ست (نه متنِ نهایی)، چون ترجمه‌ش وظیفه‌ی
    commands/vss.py با i18n است:

        "unknown_key"        کلید ناشناخته
        "bool"                باید true/false باشه
        "number"              باید عدد باشه
        "range:{lo}:{hi}"    عدد بیرونِ بازه‌ی مجاز
        "choice:{a,b,c}"     یکی از این‌ها باید باشه (مثلاً اسمِ موتور)
    """
    if key not in DEFAULTS:
        return None, "unknown_key"

    if key == "engine":
        names = stt.engine_names()
        value = (raw_value or "").strip().lower()
        if value not in names:
            return None, "choice:" + ",".join(names)
        return value, None

    if key in _BOOL_KEYS:
        low = (raw_value or "").strip().lower()
        if low not in ("true", "false"):
            return None, "bool"
        return low == "true", None

    if key in _RANGE_KEYS:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None, "number"
        lo, hi = _RANGE_KEYS[key]
        if not (lo <= value <= hi):
            return None, f"range:{lo:g}:{hi:g}"
        return value, None

    # رشته‌ای: language/service/openai_base_url/openai_api_key/openai_model/google_key.
    # اعتبارسنجیِ سخت‌گیرانه ندارن -- سرویس/زبانِ نامعتبر همون لحظه‌ی اجرا با
    # یه پیامِ روشن مشخص می‌شه، نه این‌که از تنظیم کردنش جلوگیری بشه.
    return (raw_value or "").strip(), None


def set_setting(bot, key, raw_value):
    """(ok, error, value). ok=True یعنی ذخیره و save_config شد."""
    value, error = validate(key, raw_value)
    if error is not None:
        return False, error, None
    bot.cfg.setdefault("voice_search", {})[key] = value
    bot.save_config()
    return True, None, value


def mask_value(key, value):
    """مقدارِ نمایشیِ یه کلید -- کلیدهای حساس هیچ‌وقت کامل چاپ نمی‌شن."""
    if key not in SECRET_KEYS or not value:
        return value
    text = str(value)
    if len(text) <= 6:
        return "*" * len(text)
    return text[:3] + "*" * max(3, len(text) - 5) + text[-2:]


def display_settings(bot):
    """[(key, masked_value), ...] به ترتیبِ SETTINGS_ORDER، برای دستورِ vss."""
    current = settings(bot)
    return [(key, mask_value(key, current.get(key))) for key in SETTINGS_ORDER]


# ------------------------------------------------------------- نصب/اتصال

def install(bot):
    """
    یه‌بار موقعِ بالا اومدنِ ربات صدا زده می‌شه (بوت.py، کنارِ جایی که
    دستورها لود می‌شن). این توابع همیشه سبک و بی‌خطرن -- فقط وقتی یه سشن
    واقعاً فعاله کاری می‌کنن -- پس نیازی به unsubscribe کردنشون نیست؛
    مسیرِ per-session (subscribe/unsubscribe صدای *کاربر*) کاملاً جداست.
    """
    bot.t.subscribe("user_state_changed")(lambda event: _on_state_changed(bot, event))
    bot.t.subscribe("user_audio_block")(lambda event: _on_audio_block(bot, event))
    bot.t.subscribe("user_left")(lambda event: _on_user_left(bot, event))
    bot.t.subscribe("connection_lost")(lambda event: _on_disconnect(bot, event))
    bot.t.subscribe("connection_failed")(lambda event: _on_disconnect(bot, event))
    bot.t.subscribe("kicked")(lambda event: _on_disconnect(bot, event))


def _active_session(bot):
    return getattr(bot, "_voice_search_session", None)


def _on_state_changed(bot, event):
    session = _active_session(bot)
    if session is None:
        return
    user = (event.get("params") or {}).get("user") or {}
    if user.get("user_id") != session.uid:
        return
    session.queue.put(("talking", bool(user.get("talking"))))


def _on_audio_block(bot, event):
    session = _active_session(bot)
    if session is None:
        return
    block = event.get("params") or {}
    if block.get("user_id") != session.uid:
        return
    if block.get("stream_type") != STREAM_TYPE_VOICE:
        return
    session.queue.put(("audio", block))


def _on_user_left(bot, event):
    session = _active_session(bot)
    if session is None:
        return
    user = (event.get("params") or {}).get("user") or {}
    if user.get("user_id") != session.uid:
        return
    session.queue.put(("gone", None))


def _on_disconnect(bot, event):
    session = _active_session(bot)
    if session is None:
        return
    session.queue.put(("gone", None))


# ------------------------------------------------------------------ سشن

_claim_lock = threading.Lock()


class _Session:
    def __init__(self, uid, nickname, username):
        self.uid = uid
        self.nickname = nickname
        self.username = username
        self.queue = queue.Queue()
        # همیشه ۱۶کیلوهرتز/مونو (هر بلوک موقعِ رسیدن تبدیل می‌شه -- _append_block).
        self.buffer = bytearray()
        self.sample_rate = None
        self.channels = None
        # فقط برای لاگِ تشخیصی وقتی ضبط «خیلی کوتاه»/خالی تموم می‌شه -- نه
        # خودِ صدا، فقط شمارش و فرمت‌ها.
        self.blocks_seen = 0
        self.blocks_empty = 0
        self.formats = set()
        self.talking_events = 0
        self.intercept = False
        self.output_was_open = None
        self.audio_blocks_enabled = None


def _try_claim(bot, session):
    with _claim_lock:
        if _active_session(bot) is not None:
            return False
        bot._voice_search_session = session
        return True


def _release_claim(bot):
    with _claim_lock:
        bot._voice_search_session = None


def is_busy(bot):
    return _active_session(bot) is not None


def cancel(bot, ctx):
    """`vs cancel`: سشنِ درحال‌اجرا (هرکی شروعش کرده) رو متوقف می‌کنه."""
    session = _active_session(bot)
    if session is None:
        bot.t.user_message(ctx["uid"], i18n.t("vs_cancel_nothing"))
        return
    session.queue.put(("gone", None))
    if ctx["uid"] != session.uid:
        bot.t.user_message(ctx["uid"], i18n.t("vs_cancelled"))


def _append_block(session, block):
    """
    یه بلوکِ صدا رو -- همین لحظه -- به ۱۶کیلوهرتز/مونو تبدیل و به بافر اضافه
    می‌کنه.

    قبلاً فرمتِ *اولین* بلوک قفل می‌شد و هر بلوکِ بعدی با نرخ/کانالِ متفاوت
    بی‌سروصدا دور ریخته می‌شد. اگه اولین بلوک یه نشانگرِ خالیِ شروع/پایانِ
    استریم بود یا کدکِ کانال پارامترِ دیگه‌ای داشت (بسته به سرور/کانال)، *همه‌ی*
    صدای واقعی دور ریخته می‌شد و نتیجه همیشه «خیلی کوتاه» بود. حالا هر بلوک
    جدا تبدیل می‌شه، پس تفاوتِ فرمت هیچ صدایی رو گم نمی‌کنه؛ بلوکِ خالی/بی‌نرخ
    هم فقط شمرده می‌شه و هیچ قفلی نمی‌زنه.
    """
    session.blocks_seen += 1
    pcm = block.get("pcm") or b""
    sample_rate = int(block.get("sample_rate") or 0)
    channels = max(1, int(block.get("channels") or 1))
    if not pcm or sample_rate <= 0:
        session.blocks_empty += 1
        return
    session.formats.add((sample_rate, channels))
    session.buffer.extend(to_mono16k(pcm, sample_rate, channels))
    session.sample_rate = stt.SAMPLE_RATE
    session.channels = 1


def _diagnostics(session, outcome):
    """یه خطِ کوتاه برای لاگ (بدونِ صدا یا متن): چرا ضبط خالی/کوتاه موند."""
    formats = ", ".join(f"{rate}Hz/{ch}ch" for rate, ch in sorted(session.formats)) or "none"
    return (f"outcome={outcome} blocks={session.blocks_seen} empty={session.blocks_empty} "
            f"talking_events={session.talking_events} formats={formats} "
            f"captured_bytes={len(session.buffer)} intercept={session.intercept} "
            f"output_was_open={session.output_was_open} "
            f"audio_blocks_enabled={session.audio_blocks_enabled}")


def _report_failure(bot, ctx, session, outcome, key, extra=""):
    """
    پیامِ «خیلی کوتاه/حرفی نشنیدم» به کاربر، و همون خطِ تشخیصی توی لاگ.

    اگه درخواست‌کننده ادمینِ رباته، همون خط (فقط شمارش/فرمت، نه صدا و نه متن)
    توی پیامِ خصوصیِ خودش هم میاد: مشکلی که فقط روی یه سرور پیش میاد رو
    بدونِ سر زدن به فایلِ لاگِ اون سرور می‌شه تشخیص داد.
    """
    details = _diagnostics(session, outcome) + extra
    logging_setup.log_warning(details, context="voice search")
    uid = ctx["uid"]
    bot.t.user_message(uid, i18n.t(key))
    try:
        from core import roles
        is_admin = roles.has_role(bot, uid, ctx.get("username"), "admin_bot")
    except Exception:
        is_admin = False
    if is_admin:
        bot.t.user_message(uid, i18n.t("vs_diagnostics", details=details))


def _collect(session, cfg):
    """
    (pcm, sample_rate, channels, outcome). outcome یکی از:
    "no_speech" | "gone" | "end_of_speech" | "max_duration".
    """
    start_timeout = float(cfg.get("start_timeout_seconds") or DEFAULTS["start_timeout_seconds"])
    max_seconds = float(cfg.get("max_seconds") or DEFAULTS["max_seconds"])
    silence_seconds = float(cfg.get("silence_seconds") or DEFAULTS["silence_seconds"])

    deadline = time.monotonic() + start_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return b"", None, None, "no_speech"
        try:
            kind, payload = session.queue.get(timeout=remaining)
        except queue.Empty:
            return b"", None, None, "no_speech"
        if kind == "gone":
            return b"", None, None, "gone"
        if kind == "audio":
            # بلوک‌ها معمولاً کمی زودتر از خودِ USERSTATE_VOICE می‌رسن؛
            # به‌جای دورریختنِ اولین تکه‌ی صدا، همینو شروعِ حرف‌زدن می‌گیریم.
            _append_block(session, payload)
            break
        if kind == "talking":
            session.talking_events += 1
            if payload:
                break

    end_deadline = time.monotonic() + max_seconds
    silence_deadline = None
    while True:
        now = time.monotonic()
        if now >= end_deadline:
            return bytes(session.buffer), session.sample_rate, session.channels, "max_duration"
        wait_for = end_deadline - now
        if silence_deadline is not None:
            wait_for = min(wait_for, max(0.0, silence_deadline - now))
        try:
            kind, payload = session.queue.get(timeout=max(0.0, wait_for))
        except queue.Empty:
            if silence_deadline is not None and time.monotonic() >= silence_deadline:
                return bytes(session.buffer), session.sample_rate, session.channels, "end_of_speech"
            continue
        if kind == "gone":
            return bytes(session.buffer), session.sample_rate, session.channels, "gone"
        if kind == "audio":
            _append_block(session, payload)
            continue
        if kind == "talking":
            session.talking_events += 1
            if payload:
                silence_deadline = None
            elif silence_deadline is None:
                silence_deadline = time.monotonic() + silence_seconds


# --------------------------------------------------------- تبدیلِ PCM (فقط stdlib)
#
# audioop عمداً استفاده نشده: توی 3.11 منسوخه و توی نسخه‌های بعدی حذف
# می‌شه. array/struct همون کارِ لازم (میکس کاناله‌ها، resample) رو با
# stdlib خالص انجام می‌دن.

def _samples_from_pcm16(data):
    samples = array("h")
    usable = len(data) - (len(data) % 2)
    if usable > 0:
        samples.frombytes(bytes(data[:usable]))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _pcm16_from_samples(samples):
    if sys.byteorder != "little":
        samples = array("h", samples)
        samples.byteswap()
    return samples.tobytes()


def _downmix(samples, channels):
    if channels <= 1 or not samples:
        return samples
    frames = len(samples) // channels
    mono = array("h", bytes(2 * frames))
    for i in range(frames):
        base = i * channels
        mono[i] = int(sum(samples[base:base + channels]) / channels)
    return mono


def _resample(samples, src_rate, dst_rate):
    if not samples or not src_rate or src_rate == dst_rate:
        return samples
    src_n = len(samples)
    if src_n == 1:
        return samples
    dst_n = max(1, round(src_n * dst_rate / src_rate))
    out = array("h", bytes(2 * dst_n))
    scale = (src_n - 1) / max(1, dst_n - 1)
    for i in range(dst_n):
        pos = i * scale
        idx0 = int(pos)
        idx1 = idx0 + 1 if idx0 + 1 < src_n else idx0
        frac = pos - idx0
        out[i] = int(samples[idx0] + (samples[idx1] - samples[idx0]) * frac)
    return out


def to_mono16k(pcm, sample_rate, channels):
    """
    PCM شونزده‌بیتیِ خام (هر نرخ/تعداد کانالی) رو به ۱۶کیلوهرتز/مونو/۱۶بیتیِ
    little-endian تبدیل می‌کنه -- دقیقاً فرمتی که core/stt.py می‌خواد. کل
    کار توی حافظه‌ست؛ هیچ فایلی خونده/نوشته نمی‌شه.
    """
    if not pcm or not sample_rate or not channels:
        return b""
    samples = _samples_from_pcm16(bytes(pcm))
    samples = _downmix(samples, max(1, int(channels)))
    samples = _resample(samples, int(sample_rate), stt.SAMPLE_RATE)
    return _pcm16_from_samples(samples)


def pcm_duration_seconds(pcm, sample_rate, channels):
    if not pcm or not sample_rate or not channels:
        return 0.0
    frame = 2 * max(1, int(channels))
    return len(pcm) / (frame * sample_rate)


# --------------------------------------------------------------- چرخه‌ی اصلی

def _can_intercept(bot):
    try:
        return bool(bot.t.is_server_admin())
    except Exception:
        return False


def _recording_blocked(bot):
    try:
        return bool(bot.t.recording_blocked())
    except Exception:
        # نتونستیم بفهمیم (مثلاً SDK قدیمی)؛ ادعایِ «ممنوع» نمی‌کنیم.
        return False


def _user_in_my_channel(bot, uid):
    try:
        info = bot.t.get_user_info(uid)
    except Exception:
        return False
    try:
        return info.get("channel_id") == bot.t.get_my_channel_id()
    except Exception:
        return False


def start(bot, ctx, language_override=None):
    """
    نقطه‌ی ورودِ دستورِ `vs`/`vs <lang>`. بلاکه (تا آخرِ ضبط+تشخیص+جستجو)،
    ولی چون هر دستور روی نخِ خودشه (bot.py)، این هیچ چیز دیگه‌ای رو معطل
    نمی‌کنه.
    """
    uid, nickname, username = ctx["uid"], ctx["nickname"], ctx["username"]
    if language_override is not None and not looks_like_language_code(language_override):
        bot.t.user_message(uid, i18n.t("usage_generic", usage=USAGE_VS))
        return

    cfg = settings(bot)
    session = _Session(uid, nickname, username)
    if not _try_claim(bot, session):
        bot.t.user_message(uid, i18n.t("vs_busy"))
        return

    opened_output = False
    holding = False
    subscribed = False
    intercept = False

    try:
        if not _user_in_my_channel(bot, uid):
            if not (cfg.get("intercept") and _can_intercept(bot)):
                bot.t.user_message(uid, i18n.t("vs_not_in_channel"))
                return
            intercept = True

        # «No recording»: تیم‌تاک بلوک‌های صدا رو به ربات نمی‌ده، پس ضبط
        # همیشه خالی می‌موند و پیامِ گمراه‌کننده‌ی «خیلی کوتاه» می‌اومد.
        # همین اول با دلیلِ واقعی و راه‌حل جواب می‌دیم.
        if _recording_blocked(bot):
            bot.t.user_message(uid, i18n.t("vs_no_recording"))
            return

        session.intercept = intercept
        session.output_was_open = bool(bot.t.sound_output_ready())
        if not session.output_was_open:
            opened_output = bool(bot.t.open_virtual_sound_output())

        bot.t.hold_voice(uid)
        holding = True
        session.audio_blocks_enabled = bool(bot.t.enable_audio_blocks(uid, True))
        subscribed = bool(bot.t.listen_to_voice(uid, intercept=intercept))
        if not subscribed:
            bot.t.user_message(uid, i18n.t("vs_subscribe_failed"))
            return

        bot.t.user_message(uid, i18n.t("vs_listening", seconds=int(cfg["start_timeout_seconds"])))
        pcm, sample_rate, channels, outcome = _collect(session, cfg)
    finally:
        if subscribed:
            bot.t.stop_listening_to_voice(uid, intercept=intercept)
        bot.t.enable_audio_blocks(uid, False)
        if holding:
            bot.t.release_voice(uid)
        if opened_output:
            bot.t.close_sound_output()
        _release_claim(bot)

    # اگه توی try یکی از return های زودهنگام (نبودن توی کانال/subscribe
    # ناموفق) اجرا شده باشه، finally بالا اجرا شده و start() از همون‌جا
    # برگشته -- کدِ زیر اصلاً اجرا نمی‌شه، پس outcome همیشه از _collect میاد.
    if outcome == "gone":
        bot.t.user_message(uid, i18n.t("vs_stopped"))
        return
    if outcome == "no_speech":
        _report_failure(bot, ctx, session, outcome, "vs_no_speech")
        return

    duration = pcm_duration_seconds(pcm, sample_rate, channels)
    if duration < float(cfg.get("min_seconds") or 0):
        # اگه با وجودِ حرف‌زدن باز هم این پیام اومد، خطِ تشخیصی می‌گه بلوک‌های
        # صدا اصلاً رسیدن یا نه، خالی بودن یا چه فرمتی داشتن.
        _report_failure(bot, ctx, session, outcome, "vs_too_short",
                        f" duration={duration:.2f}s min_seconds={cfg.get('min_seconds')}")
        return

    language = effective_language(bot, language_override)
    mono16k = to_mono16k(pcm, sample_rate, channels)
    # از این به بعد pcm خام دیگه لازم نیست؛ صریح رهاش می‌کنیم (GC) تا عمرش
    # توی حافظه هرچی کوتاه‌تر باشه.
    del pcm
    _recognize_and_search(bot, ctx, cfg, language, mono16k)


def _recognize_and_search(bot, ctx, cfg, language, pcm16k):
    uid = ctx["uid"]
    engine_name = (cfg.get("engine") or DEFAULTS["engine"]).strip().lower()
    timeout = float(cfg.get("request_timeout_seconds") or DEFAULTS["request_timeout_seconds"])

    try:
        logging_setup.set_operation(f"voice search: recognizing speech via {engine_name} for {ctx.get('username')}")
        text = stt.transcribe_with_fallback(engine_name, cfg, pcm16k, language, timeout)
    except stt.SpeechThrottledError:
        # پیامِ روشنِ i18n به‌جای متنِ خامِ خطا؛ بدون کلید و بدون آدرس. فقط
        # عددِ ثانیه از exception خونده می‌شه (نه متنش).
        seconds = sys.exc_info()[1].retry_after
        bot.t.user_message(uid, i18n.t("vs_throttled", seconds=seconds))
        return
    except Exception as e:
        # همیشه از safe_error_text، حتی برای SpeechToTextError: خودِ کلاسش
        # از ValueError ارث می‌بره (core/stt.py) دقیقاً برای این‌که
        # safe_error_text پیامِ کوتاه و تمیزش رو عیناً نشون بده، ولی هیچ
        # متنِ خامِ exception ای هیچ‌وقت مستقیم (بدون رد شدن از این تابع) به
        # کاربر نرسه.
        bot.t.user_message(uid, i18n.t("vs_recognize_failed", error=logging_setup.safe_error_text(e)))
        return
    finally:
        logging_setup.set_operation("idle")

    text = " ".join((text or "").split())
    if not text:
        bot.t.user_message(uid, i18n.t("vs_not_understood"))
        return

    bot.t.user_message(uid, i18n.t("vs_heard", text=text))
    if cfg.get("announce"):
        try:
            command_helpers.notify(bot, ctx, "vs_announce_heard", nickname=ctx.get("nickname"), text=text)
        except Exception:
            logging_setup.log_debug("[voice_search] announce failed")

    _run_search(bot, ctx, cfg, text)


def _run_search(bot, ctx, cfg, text):
    """
    دقیقاً همون مسیرِ دستورِ `p <text>` رو صدا می‌زنه (bot.commands["p"]) --
    نه یه پیاده‌سازیِ دومِ جستجو. service تنظیم‌شده (اگه خالی نباشه) فقط
    موقتاً current_service_index رو عوض می‌کنه، دقیقاً برای همین یه صدا زدن،
    و بعدش برمی‌گردونتش.
    """
    p_entry = (getattr(bot, "commands", None) or {}).get("p")
    if not p_entry:
        bot.t.user_message(ctx["uid"], i18n.t("vs_recognize_failed", error="'p' command unavailable"))
        return

    search_ctx = dict(ctx)
    search_ctx["args"] = text.split()
    search_ctx["raw"] = text
    search_ctx["cmd"] = "p"

    service_name = (cfg.get("service") or "").strip()
    original_index = getattr(bot, "current_service_index", 0)
    switched = False
    if service_name:
        try:
            names = manager.searchable_service_names(bot.services)
            if service_name in names:
                bot.current_service_index = names.index(service_name)
                switched = True
        except Exception:
            logging_setup.log_debug(f"[voice_search] could not select configured service '{service_name}'")

    try:
        p_entry["handler"](search_ctx)
    finally:
        if switched:
            bot.current_service_index = original_index
