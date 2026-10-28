"""
شکل پیش‌فرض فایل‌های کانفیگ یه ربات، و قاعده‌ی اسم‌گذاری پوشه‌ها.

قبلاً این‌ها فقط داخل bot.py بودن. حالا که پلتفرم لایسنس هم باید ربات
بسازه (licensing/provisioning.py)، دو نسخه‌ی جدا خیلی زود از هم دور
می‌شدن: یه کلید جدید به shared_config اضافه می‌شد و ربات‌هایی که پلتفرم
ساخته بود بدون اون کلید بالا می‌آمدن. پس یه منبع حقیقت واحد اینجاست و هم
bot.py هم پلتفرم از همین استفاده می‌کنن.

ساختار پوشه‌ها:

    data/<host>_<port>/shared_config.json     تنظیمات مشترک همه‌ی ربات‌های اون سرور
    data/<host>_<port>/<bot_name>/identity.json  مشخصات خود ربات
    data/<host>_<port>/<bot_name>/license.json   (اختیاری) لایسنس این نمونه
"""

import copy
import json
import os
import re

# پوشه‌هایی توی data/ که سرور تیم‌تاک نیستن و نباید به‌عنوان گروهِ ربات
# خونده بشن. data/licensing مال خودِ پلتفرم لایسنسه (config.json، دیتابیس،
# کلیدها، رسیدها).
#
# این لیست بعد از یه خرابیِ واقعی اضافه شد: bot.py پوشه‌ی licensing رو یه
# «سرور با فرمت قدیمی» دید، config.json پلتفرم رو به‌جای کانفیگ ربات
# مهاجرت داد و **پاکش کرد** -- بعدش پلتفرم با «توکن تنظیم نشده» بالا
# نمی‌آمد و launcher هم یه ربات ارواح از روی همون پوشه استارت می‌کرد.
RESERVED_DATA_DIRS = {"licensing"}


def is_server_group_name(name):
    """
    data/<name> می‌تونه یه سرور تیم‌تاک باشه یا نه.

    اسم‌های شروع‌شده با «_» هم رد می‌شن: فایل/پوشه‌های داخلی خود پروژه
    (مثل data/_audio_lines.json) با همین قاعده اسم‌گذاری می‌شن.
    """
    return bool(name) and name not in RESERVED_DATA_DIRS and not name.startswith("_")


def looks_like_legacy_bot_config(data):
    """
    این dict واقعاً یه data/<host>_<port>/config.json از نسخه‌های قدیمیه؟

    فقط «فایل config.json داره» کافی نیست -- هر پوشه‌ی دیگه‌ای هم ممکنه
    فایلی به همین اسم داشته باشه. نشانه‌ی قطعی یه کانفیگ رباتِ قدیمی،
    بخش server با آدرس سروره.
    """
    if not isinstance(data, dict):
        return False
    server = data.get("server")
    return isinstance(server, dict) and bool(server.get("host"))


def server_folder_name(host, port):
    safe_host = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(host))
    return f"{safe_host}_{port}"


def safe_bot_folder_name(name):
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(name)).strip("_")
    return safe or "bot1"


def write_bot_files(data_dir, host, port, bot_name, nickname="Audio Player Bot",
                    username="", password="", channel_id=1, channel_password=""):
    """
    سرور (shared_config.json) و یه ربات (identity.json) می‌سازه -- همون
    ساختاری که ویزارد bot.py می‌سازه. idempotent: فایلِ موجود هیچ‌وقت
    بازنویسی نمی‌شه. دستگاه صدا روی پیش‌فرض می‌مونه (۰)؛ برای لاین
    اختصاصی `python manage.py line-add` یا bot.py.

    خروجی: (group_dir, bot_dir, created) که created لیستِ فایل‌های تازه‌ساخته است.
    """
    group_dir = os.path.join(data_dir, server_folder_name(host, port))
    bot_dir = os.path.join(group_dir, safe_bot_folder_name(bot_name))
    created = []

    shared_path = os.path.join(group_dir, "shared_config.json")
    if not os.path.isfile(shared_path):
        os.makedirs(group_dir, exist_ok=True)
        with open(shared_path, "w", encoding="utf-8") as f:
            json.dump(default_shared_config(host, port), f, ensure_ascii=False, indent=4)
        created.append(shared_path)

    identity_path = os.path.join(bot_dir, "identity.json")
    if not os.path.isfile(identity_path):
        identity = default_identity()
        identity["server"].update(nickname=nickname, username=username, password=password)
        identity["channel"].update(id=int(channel_id), password=channel_password)
        os.makedirs(bot_dir, exist_ok=True)
        with open(identity_path, "w", encoding="utf-8") as f:
            json.dump(identity, f, ensure_ascii=False, indent=4)
        created.append(identity_path)
    return group_dir, bot_dir, created


#: کلیدِ عمومیِ Web Speech (همون کلیدِ عمومیِ کرومیوم)؛ core/stt.py هم ازش می‌خونه.
GOOGLE_STT_PUBLIC_KEY = "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw"

# منبع مستندها (دستور md). آدرس از الگو ساخته می‌شه، پس عوض‌کردن
# منبع یا پسوند فایل فقط یه ویرایش کانفیگه. max_number=0 یعنی سقفی
# نداره -- توضیح کامل توی core/documentary.py.
DOCUMENTARY_DEFAULTS = {
    "url_template": "https://cfdl.ir/vmfiles/{n}.mkv",
    "min_number": 7,
    "max_number": 0,
    "title_template": "مستند {n}",
}


# منبع‌های IPTV (دستور tv). پیش‌فرض یه لیست عمومیِ ایرانِ iptv-org
# داره تا بدون هیچ تنظیمی هم کار کنه؛ توضیح کامل توی core/iptv.py.
IPTV_DEFAULTS = {
    "sources": [
        {"name": "IPTV-ORG: Iran", "url": "https://iptv-org.github.io/iptv/countries/ir.m3u"},
    ],
    "cache_minutes": 60,
    "max_channels": 5000,
    "page_size": 15,
}


# پخشِ لایو با قابلیتِ برگشت به عقب (دستور cld، core/live_dvr.py). تا وقتی
# فعاله یه yt-dlp پس‌زمینه با live_from_start=True مدام داره دانلود
# می‌کنه؛ برای این‌که یه سشنِ ول‌شده کل دیسک/رمِ سرور رو نخوره، دو سقفِ
# مستقل داریم (هرکدوم زودتر برسه دانلود متوقف می‌شه، ولی چیزی که تا اون
# لحظه دانلود شده برای پخش/سیک نگه داشته می‌شه -- توضیح کامل بالای
# core/live_dvr.py::_cap_reached).
LIVE_DVR_DEFAULTS = {
    "max_minutes": 120,     # سقفِ زمانیِ بافر (۲ ساعت)
    "max_megabytes": 300,   # سقفِ حجمِ فایلِ موقت روی دیسک
    "start_wait_seconds": 6,  # قبل از شروعِ پخش چقدر صبر کنه تا بافر اولیه آماده بشه
    "default_back_minutes": 10,  # cld بدونِ آرگومان: پخش از لبه‌ی لایو، با این‌قدر بافرِ عقب
    "max_back_minutes": 120,     # سقفِ آرگومانِ cld <minutes> (یوتیوب خودش تا ۱۲۰ ساعت نگه می‌داره)
    "backfill_timeout_seconds": 90,  # سقفِ انتظار برای دانلودِ بخشِ عقبِ اولیه
}


# رأی‌گیری برای رد کردن آهنگ (دستور vn، core/voteskip.py). ratio کسری از
# کاربرهای غیررباتِ کانال (به‌جز خودِ ربات) که باید *بیشتر* از اون رأی بدن
# تا آهنگ رد بشه: 0.5 یعنی «بیشتر از نصف». یه نفرِ تنها همیشه فوراً رد می‌کنه.
VOTE_SKIP_DEFAULTS = {
    "ratio": 0.5,
}


# زیرنویس (دستور sub، core/subtitles.py). default_language خالی یعنی «همون
# زبانِ ربات» (cfg["language"])؛ کاربر با `sub <lang>` زبانِ خودش رو می‌ده.
SUBTITLE_DEFAULTS = {
    "default_language": "",
}


# جستجوی صوتی (دستور vs، تنظیم با vss) -- توضیح کامل هر کلید توی
# core/voice_search.py و docs/VOICE_SEARCH.md. language خالی یعنی
# «همون زبان ربات» (fa -> fa-IR، en -> en-US) و service خالی یعنی
# «سرویسِ فعالِ جستجو». google_key کلید عمومیِ Web Speech است.
VOICE_SEARCH_DEFAULTS = {
    "engine": "google",
    "language": "",
    "service": "",
    "max_seconds": 10,
    "start_timeout_seconds": 8,
    "silence_seconds": 1.0,
    "min_seconds": 0.6,
    "request_timeout_seconds": 20,
    "announce": False,
    "intercept": True,
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "whisper-1",
    "google_key": GOOGLE_STT_PUBLIC_KEY,
}


def default_shared_config(host, port):
    return {
        "server": {"host": host, "port": port},
        "proxy": {"enabled": False, "url": None},
        "admins": [],
        "youtube_api": {"enabled": False, "key": ""},
        "status": {"visible": True, "idle_text": "Idle", "gender": "neutral",
                   "away_when_paused": False},
        "audio_normalize": False,
        "language": "en",
        "channel_messages_enabled": True,
        "roaming": {"enabled": True},
        "access": {"mode": "all"},
        "idle_channel": {"enabled": True, "pause_after_seconds": 0, "stop_after_seconds": 300, "resume_rewind_seconds": 4},
        "seek_default_seconds": 15,
        "reconnect_wait": {"first_seconds": 0, "repeat_seconds": 10},
        "cookies": {"enabled": True},
        "dl_auto_remove_minutes": 0,
        # تست سلامت موقع راه‌اندازی. audio_tone یه تُن ۰.۳ ثانیه‌ای روی
        # دستگاه خروجی پخش می‌کنه تا مطمئن شیم دستگاه واقعاً باز می‌شه؛
        # اگه خروجی اسپیکر واقعیه و نمی‌خوای صدا بشنوی، خاموشش کن.
        "selftest": {"enabled": True, "audio_tone": True, "quiet": False, "include_slow": True},
        "documentary": copy.deepcopy(DOCUMENTARY_DEFAULTS),
        "iptv": copy.deepcopy(IPTV_DEFAULTS),
        "live_dvr": copy.deepcopy(LIVE_DVR_DEFAULTS),
        "vote_skip": copy.deepcopy(VOTE_SKIP_DEFAULTS),
        "subtitles": copy.deepcopy(SUBTITLE_DEFAULTS),
        # تنظیمات مصرف منابع پخش‌کننده. پیش‌فرض‌ها عمداً کم‌مصرفن تا چند
        # ربات هم‌زمان روی یه سیستم ضعیف جا بشن؛ اگه سیستم قوی داری و
        # می‌خوای بافر بیشتری داشته باشی، همین‌ها رو بزرگ‌تر کن.
        "player": {
            "demuxer_max_bytes": "20MiB",
            "demuxer_max_back_bytes": "5MiB",
            "network_timeout": 30,
            "log_level": "warn",
            # اجازه‌ی صدا زدن yt-dlp توسط خودِ mpv. پیش‌فرض false: همه‌ی
            # لینک‌ها از قبل resolve شدن، و هوک ytdl خودِ mpv پروکسی/کوکی ما
            # رو نداره -- یعنی یه درخواست لختِ اضافه به یوتیوب. توضیح کامل
            # بالای Player.DEFAULT_ALLOW_MPV_YTDL.
            "allow_mpv_ytdl": False,
        },
        "voice_search": copy.deepcopy(VOICE_SEARCH_DEFAULTS),
    }


def default_identity():
    return {
        "server": {"nickname": "Audio Player Bot", "username": "", "password": ""},
        "channel": {"id": 1, "password": ""},
        "audio": {"input_device": 0, "output_device": 0},
        "last_state": {"volume": 50, "service": "", "service_index": 0},
        # (dl) این ربات یا از تایمر مشترکِ سرور (dl_auto_remove_minutes توی
        # shared_config) استفاده می‌کنه، یا از مقدار مخصوص خودش
        # (dl_auto_remove_minutes_own) -- بسته به dl_auto_remove_scope.
        "dl_auto_remove_scope": "shared",  # "shared" یا "per_bot"
        "dl_auto_remove_minutes_own": 0,
        # مدت نگه‌داری فایل توی پوشه‌ی downloads خودِ همین ربات (نه کانال
        # تیم‌تاک) بعد از آپلود موفق -- همیشه مخصوص خودِ همین رباته، هیچ‌وقت
        # مشترک نیست، چون هر ربات پوشه‌ی دانلود جدای خودش رو داره.
        "downloads_cleanup_minutes": 1440,
        # ادمین‌های مخصوص همین یه ربات (سطح دسترسیِ admin_bot، پایین‌تر از
        # admins توی shared_config که روی کل سرور اثر داره -- توضیح کامل
        # توی core/roles.py).
        "bot_admins": [],
        # پخش‌های زمان‌بندی‌شده‌ی همین ربات (دستور sch، core/scheduled_play.py).
        # مخصوص همین ربات است، نه مشترک بین ربات‌های یه سرور.
        "schedule": [],
    }


def feature_settings(bot, key, defaults):
    """تنظیماتِ یه قابلیت از bot.cfg[key]، با پر کردنِ جاهای خالی از defaults."""
    raw = {}
    if bot is not None and getattr(bot, "cfg", None):
        candidate = bot.cfg.get(key)
        if isinstance(candidate, dict):
            raw = candidate
    merged = dict(defaults)
    merged.update({k: v for k, v in raw.items() if v is not None})
    return merged


def positive_int_setting(settings, key, defaults):
    """مقدار صحیحِ >= 1 از تنظیمات؛ اگه خراب بود پیش‌فرض."""
    try:
        return max(1, int(settings[key]))
    except (TypeError, ValueError):
        return defaults[key]
