import json, os, time, sys

# ساختار فایل: import این ماژول هیچ اثر جانبی‌ای نداره (نه اتصال، نه ترد، نه
# گیت لایسنس، نه لود کتابخانه‌ی نیتیو)؛ همه‌ی راه‌اندازی ترتیبی توی main()
# (آخر فایل) انجام می‌شه. متغیرهایی که قبلاً لحظه‌ی import ساخته می‌شدن
# (cfg, t, player, ...) این‌جا با None اعلام شدن و main() به همون ترتیبِ قبل
# مقدار می‌دن.
import warnings

# PyInstaller موقع بالا آمدن یه هشدار deprecation از pkg_resources چاپ
# می‌کنه که ربطی به این برنامه نداره و برای کاربر نهایی فقط نویز و
# نگران‌کننده‌ست. خطاهای واقعی همچنان چاپ می‌شن.
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

from core.paths import force_utf8_console, get_base_dir, write_json_atomic

BASE_DIR = get_base_dir()
import threading
import urllib.parse
# این سه‌تا لحظه‌ی import کتابخانه‌ی نیتیو (TeamTalk5.dll / libmpv) رو لود می‌کنن
# و PATH رو دست می‌زنن، پس توی _load_native_modules() ایمپورت می‌شن.
TTBot = TeamTalkCommandError = ClientError = Player = None
from core.manager import ServiceManager, searchable_service_names
from core.playlist_utils import resolve_playlist
from core import proxy_state
from core import youtube_api_state
from core import logging_setup
from core import history
from core import roles
from core import scheduler
from core import workers
from core import i18n
from core.command_manager import CommandManager
from core import bot_context
from core import platform_paths
from core import audio_lines
from core import audio_setup
from core import command_helpers
from core import cookie_files
from core import status_line
from core import license_gate
from core import documentary
from core import iptv
from core import live_dvr
from core import voice_search
from core import subtitles
from core import scheduled_play
from core import selftest
from core import trackqueue
from core import track_meta
from core import config_defaults

bot = bot_context.bot

DATA_DIR = os.path.join(BASE_DIR, "data")

# قاعده‌ی اسم پوشه‌ها هم مشترکه (core/config_defaults.py) -- اگه پلتفرم
# لایسنس اسم پوشه رو یه‌جور دیگه بسازه، ربات هیچ‌وقت پیداش نمی‌کنه.
_server_folder_name = config_defaults.server_folder_name
_safe_bot_folder_name = config_defaults.safe_bot_folder_name

def _list_server_groups():
    """پوشه‌های data/<host>_<port>/ که shared_config.json دارن (یعنی یه سرورِ تنظیم‌شده‌ان)."""
    return [
        d for d in sorted(os.listdir(DATA_DIR))
        if config_defaults.is_server_group_name(d)
        and os.path.isfile(os.path.join(DATA_DIR, d, "shared_config.json"))
    ]

def _list_bots_in_group(group_dir):
    """زیرپوشه‌های یه گروه که identity.json دارن (یعنی یه ربات واقعی و کامله)."""
    if not os.path.isdir(group_dir):
        return []
    return [
        d for d in sorted(os.listdir(group_dir))
        if os.path.isfile(os.path.join(group_dir, d, "identity.json"))
    ]

def _resolve_group_and_bot_dirs():
    """
    انتخاب سرور+ربات با آرگومان‌های خط فرمان:
        python bot.py                            -> فقط اگه دقیقاً یه سرور با دقیقاً یه ربات وجود داشته باشه
        python bot.py <host_port>                 -> اگه اون سرور دقیقاً یه ربات داره
        python bot.py <host_port> <bot_name>       -> کاملاً مشخص، همیشه جواب می‌ده

    خروجی: (group_dir یا None, bot_dir یا None)
        - (None, None)              -> هیچ سروری نیست، ویزارد کامل (سرور جدید + اولین ربات)
        - (group_dir, None)         -> سرور هست ولی این ربات مشخص نیست/وجود نداره -> ویزارد «ربات جدید روی سرور موجود»
        - (group_dir, bot_dir)      -> همه‌چیز مشخصه، مستقیم اجرا می‌شه
    """
    groups = _list_server_groups()
    group_arg = sys.argv[1] if len(sys.argv) > 1 else None
    bot_arg = sys.argv[2] if len(sys.argv) > 2 else None

    if group_arg and group_arg in groups:
        group_name = group_arg
    elif group_arg:
        print(f"سروری با اسم پوشه‌ی '{group_arg}' زیر data/ پیدا نشد.")
        print("سرورهای موجود: " + (', '.join(groups) if groups else '(هیچی)'))
        sys.exit(1)
    elif len(groups) == 1:
        group_name = groups[0]
    elif len(groups) > 1:
        print("چندتا سرور توی data/ پیدا شد، باید یکیشو با آرگومان مشخص کنی:")
        for g in groups:
            print(f"  python bot.py {g}")
        sys.exit(1)
    else:
        return None, None

    group_dir = os.path.join(DATA_DIR, group_name)
    bots = _list_bots_in_group(group_dir)

    if bot_arg and bot_arg in bots:
        return group_dir, os.path.join(group_dir, bot_arg)
    elif bot_arg:
        print(f"روی سرور '{group_name}' رباتی با اسم '{bot_arg}' پیدا نشد.")
        print("ربات‌های موجود: " + (', '.join(bots) if bots else '(هیچی)'))
        sys.exit(1)
    elif len(bots) == 1:
        return group_dir, os.path.join(group_dir, bots[0])
    elif len(bots) > 1:
        print(f"سرور '{group_name}' چندتا ربات داره، باید یکیشو با آرگومان مشخص کنی:")
        for b in bots:
            print(f"  python bot.py {group_name} {b}")
        sys.exit(1)
    else:
        return group_dir, None

_ask = audio_setup.ask

# پیش‌فرض‌های کانفیگ توی core/config_defaults.py هستن تا پلتفرم لایسنس
# (که خودش هم ربات می‌سازه) دقیقاً همون شکل رو بسازه و دو نسخه از هم
# دور نشن.
_default_shared_config = config_defaults.default_shared_config
_default_identity = config_defaults.default_identity

def run_setup_wizard(group_dir=None):
    """
    group_dir=None  -> هیچ سروری نیست: هم سرور جدید ساخته می‌شه هم اولین ربات.
    group_dir=<...> -> سرور از قبل هست (shared_config.json دست‌نخورده می‌مونه)،
                        فقط یه ربات جدید (identity.json جدید) بهش اضافه می‌شه.
    خروجی: (group_dir, bot_dir)
    """
    if group_dir is None:
        print("هیچ سروری تنظیم نشده. اطلاعات زیر رو وارد کن تا ساخته بشه:\n")
        host = _ask("آدرس سرور تیم‌تاک")
        port = _ask("پورت (tcp=udp)", 10333, int)
        group_dir = os.path.join(DATA_DIR, _server_folder_name(host, port))
        os.makedirs(group_dir, exist_ok=True)

        shared = _default_shared_config(host, port)
        proxy_enabled = _ask("پروکسی فعال باشه؟ (y/n)", "n").lower() == "y"
        if proxy_enabled:
            shared["proxy"] = {"enabled": True, "url": _ask("لینک پروکسی (اختیاری)", "") or None}
        admins_raw = _ask("یوزرنیم مدیرها، با کاما جدا کن (اختیاری)", "")
        shared["admins"] = [a.strip() for a in admins_raw.split(",") if a.strip()]
        yt_api_key = _ask("YouTube Data API key (اختیاری، Enter برای رد شدن)", "")
        shared["youtube_api"] = {"enabled": bool(yt_api_key), "key": yt_api_key}
        shared["status"]["idle_text"] = _ask("متن استاتوس idle ربات‌ها", "Idle")

        with open(os.path.join(group_dir, "shared_config.json"), "w", encoding="utf-8") as f:
            json.dump(shared, f, ensure_ascii=False, indent=4)
        print(f"\nسرور جدید ساخته شد: {group_dir}")
    else:
        print(f"داریم یه ربات جدید به سرور موجود ({os.path.basename(group_dir)}) اضافه می‌کنیم.")
        print("تنظیمات مشترک این سرور (پروکسی/ادمین‌ها/زبان/...) دست‌نخورده می‌مونن؛")
        print("اینجا فقط مشخصات خودِ همین ربات جدید رو می‌پرسیم:\n")

    while True:
        bot_name_raw = _ask("یه اسم کوتاه برای این ربات (فقط اسم پوشه، مثلاً bot1)", "bot1")
        bot_name = _safe_bot_folder_name(bot_name_raw)
        bot_dir = os.path.join(group_dir, bot_name)
        if os.path.isfile(os.path.join(bot_dir, "identity.json")):
            print(f"یه ربات با این اسم از قبل روی این سرور هست ({bot_dir})؛ یه اسم دیگه انتخاب کن.")
            continue
        break

    identity = _default_identity()
    identity["server"]["nickname"] = _ask("نیک‌نیم ربات", "Audio Player Bot")
    identity["server"]["username"] = _ask("یوزرنیم لاگین")
    identity["server"]["password"] = _ask("پسورد")
    identity["channel"]["id"] = _ask("آیدی کانال پیش‌فرض", 1, int)
    identity["channel"]["password"] = _ask("پسورد کانال (اگه نداره خالی بذار)", "")

    from core import audio_setup
    identity["audio"] = audio_setup.choose_audio_devices(
        _ask,
        line_slug_hint=f"{os.path.basename(group_dir)}_{bot_name}",
        owner=f"{os.path.basename(group_dir)}/{bot_name}",
    )

    os.makedirs(bot_dir, exist_ok=True)
    with open(os.path.join(bot_dir, "identity.json"), "w", encoding="utf-8") as f:
        json.dump(identity, f, ensure_ascii=False, indent=4)

    print(f"\nربات '{bot_name}' ساخته شد: {bot_dir}")
    print("کوکی هر سرویس (اختیاری، مشترک بین همه‌ی ربات‌های این سرور) رو می‌تونی اینجا بذاری: "
          f"{os.path.join(group_dir, 'cookies', 'youtube.txt')} (یا instagram.txt و ...)\n")
    return group_dir, bot_dir

def _migrate_legacy_configs():
    """
    نسخه‌های قبلی این پروژه هر سرور رو با یه فایل تخت data/<host>_<port>/config.json
    نگه می‌داشتن (بدون امکان چند ربات روی یه سرور). اگه از این‌جور پوشه‌ها پیدا
    بشه، خودکار به ساختار جدید (shared_config.json + <bot_name>/identity.json)
    تبدیلش می‌کنیم تا تنظیمات/alias ها/دانلودهای قبلی از دست نره.
    """
    if not os.path.isdir(DATA_DIR):
        return
    for name in sorted(os.listdir(DATA_DIR)):
        # پوشه‌های رزروشده (مثل data/licensing) هیچ‌وقت سرور نیستن.
        if not config_defaults.is_server_group_name(name):
            continue
        group_dir = os.path.join(DATA_DIR, name)
        legacy_config = os.path.join(group_dir, "config.json")
        shared_config = os.path.join(group_dir, "shared_config.json")
        if not os.path.isfile(legacy_config) or os.path.isfile(shared_config):
            continue
        try:
            with open(legacy_config, "r", encoding="utf-8") as f:
                old_cfg = json.load(f)
        except Exception:
            continue

        # آخر این مهاجرت legacy_config پاک می‌شه، پس قبلش باید *مطمئن*
        # باشیم واقعاً کانفیگ یه ربات قدیمیه. یه بار همین چک نبود و
        # کانفیگ پلتفرم لایسنس (که فقط هم‌اسم بود) قربانی شد.
        if not config_defaults.looks_like_legacy_bot_config(old_cfg):
            continue

        bot_name = "bot1"
        bot_dir = os.path.join(group_dir, bot_name)
        os.makedirs(bot_dir, exist_ok=True)

        identity = {
            "server": {
                "nickname": old_cfg.get("server", {}).get("nickname", "Audio Player Bot"),
                "username": old_cfg.get("server", {}).get("username", ""),
                "password": old_cfg.get("server", {}).get("password", ""),
            },
            "channel": old_cfg.get("channel", {"id": 1, "password": ""}),
            "audio": old_cfg.get("audio", {"input_device": 0, "output_device": 0}),
            "last_state": old_cfg.get("last_state", {"volume": 50, "service_index": 0}),
        }
        shared = {k: v for k, v in old_cfg.items() if k not in ("channel", "audio", "last_state")}
        shared["server"] = {
            "host": old_cfg.get("server", {}).get("host"),
            "port": old_cfg.get("server", {}).get("port"),
        }

        with open(os.path.join(bot_dir, "identity.json"), "w", encoding="utf-8") as f:
            json.dump(identity, f, ensure_ascii=False, indent=4)
        with open(shared_config, "w", encoding="utf-8") as f:
            json.dump(shared, f, ensure_ascii=False, indent=4)

        if os.path.isfile(os.path.join(group_dir, "aliases.json")):
            try:
                os.replace(os.path.join(group_dir, "aliases.json"), os.path.join(bot_dir, "aliases.json"))
            except OSError:
                pass
        old_downloads = os.path.join(group_dir, "downloads")
        if os.path.isdir(old_downloads):
            try:
                os.replace(old_downloads, os.path.join(bot_dir, "downloads"))
            except OSError:
                pass

        try:
            os.remove(legacy_config)
        except OSError:
            pass

        print(f"[Migration] '{name}' از فرمت قدیمی به فرمت جدید (چندروباتی) منتقل شد -> {bot_dir}")

_group_dir = _bot_dir = None
SHARED_CONFIG_FILE = IDENTITY_FILE = None

def _select_bot():
    """مهاجرت قدیمی‌ها، انتخابِ سرور+ربات (یا ویزارد)، و مسیر فایل‌های کانفیگ."""
    global _group_dir, _bot_dir, SHARED_CONFIG_FILE, IDENTITY_FILE
    _migrate_legacy_configs()
    _group_dir, _bot_dir = _resolve_group_and_bot_dirs()
    if _group_dir is None:
        _group_dir, _bot_dir = run_setup_wizard(None)
    elif _bot_dir is None:
        _group_dir, _bot_dir = run_setup_wizard(_group_dir)

    SHARED_CONFIG_FILE = os.path.join(_group_dir, "shared_config.json")
    IDENTITY_FILE = os.path.join(_bot_dir, "identity.json")

_SHARED_DEFAULTS = _default_shared_config(None, None)
_IDENTITY_DEFAULTS = _default_identity()

def _deep_merge_defaults(target, defaults):
    changed = False
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
            changed = True
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            if _deep_merge_defaults(target[key], value):
                changed = True
    return changed

_IDENTITY_ONLY_KEYS = (
    "channel", "audio", "last_state",
    "dl_auto_remove_scope", "dl_auto_remove_minutes_own", "downloads_cleanup_minutes",
    "bot_admins",
    "schedule",
)

_config_write_lock = threading.Lock()

# آخرین محتوای shared_config.json همون‌طور که ما خوندیمش. برای تشخیص
# «کدوم کلید رو *ما* عوض کردیم» لازمه (توضیح کامل توی save_config).
_shared_snapshot = {}

def _snapshot(data):
    return json.loads(json.dumps(data))

def _atomic_write_json(path, data):
    """
    نوشتن اتمیک: اول توی یه فایل موقت، بعد جایگزینی. اگه چند ربات هم‌زمان
    روی فایل مشترک بنویسن (یا برق بره)، هیچ‌وقت یه JSON نصفه‌نیمه روی دیسک
    نمی‌مونه که دفعه‌ی بعد لود نشه.
    """
    write_json_atomic(path, data, per_process_tmp=True)

def load_config():
    global _shared_snapshot
    with open(SHARED_CONFIG_FILE, "r", encoding="utf-8") as f:
        shared = json.load(f)
    with open(IDENTITY_FILE, "r", encoding="utf-8") as f:
        identity = json.load(f)

    shared_changed = _deep_merge_defaults(shared, _SHARED_DEFAULTS)
    identity_changed = _deep_merge_defaults(identity, _IDENTITY_DEFAULTS)

    if shared_changed:
        _atomic_write_json(SHARED_CONFIG_FILE, shared)
    if identity_changed:
        _atomic_write_json(IDENTITY_FILE, identity)

    _shared_snapshot = _snapshot(shared)

    merged = dict(shared)
    merged["server"] = {**shared.get("server", {}), **identity.get("server", {})}
    for key in _IDENTITY_ONLY_KEYS:
        merged[key] = identity.get(key, _IDENTITY_DEFAULTS.get(key))
    return merged

def dl_auto_remove_minutes_effective():
    """
    مقدار واقعی‌ای که همین ربات باید ازش استفاده کنه: یا مشترک (shared_config،
    برای همه‌ی ربات‌های این سرور یکیه)، یا مخصوص خودش (per_bot، توی
    identity.json خودش) -- بسته به dl_auto_remove_scope.
    """
    if cfg.get("dl_auto_remove_scope") == "per_bot":
        return cfg.get("dl_auto_remove_minutes_own", 0)
    return cfg.get("dl_auto_remove_minutes", 0)

def save_config():
    """
    cfg فعلی رو دوباره به دو فایل تقسیم می‌کنه و ذخیره می‌کنه:
      - shared_config.json: هرچی «تنظیمات مشترک» محسوب می‌شه -- روی همه‌ی
        ربات‌های همین سرور اثر می‌ذاره.
      - identity.json: فقط مشخصات خودِ همین ربات (نیک/یوزر/پس/کانال/دیوایس/
        آخرین وضعیت/تنظیمات دانلود مخصوص خودش).
    """
    global _shared_snapshot
    with _config_write_lock:
        try:
            identity_out = {
                "server": {
                    "nickname": cfg["server"].get("nickname", ""),
                    "username": cfg["server"].get("username", ""),
                    "password": cfg["server"].get("password", ""),
                },
            }
            for key in _IDENTITY_ONLY_KEYS:
                identity_out[key] = cfg.get(key, _IDENTITY_DEFAULTS.get(key))
            _atomic_write_json(IDENTITY_FILE, identity_out)

            shared_out = {k: v for k, v in cfg.items() if k not in _IDENTITY_ONLY_KEYS}
            shared_out["server"] = {
                "host": cfg["server"].get("host"),
                "port": cfg["server"].get("port"),
            }

            # ادغام سه‌طرفه به‌جای بازنویسی کامل.
            #
            # قبلاً این تابع کل نسخه‌ی خودش رو روی shared_config.json
            # می‌نوشت. وقتی چند ربات روی یه سرور اجرا می‌شن، یعنی هر
            # تغییری که ربات دیگه توی فاصله‌ی بین آخرین بازخوانی ما و
            # این نوشتن انجام داده بود، بی‌صدا پاک می‌شد. حالا فقط
            # کلیدهایی رو می‌نویسیم که *خودمون* واقعاً عوض کردیم (یعنی
            # با snapshot لحظه‌ی خوندن فرق دارن)؛ بقیه دست‌نخورده از روی
            # دیسک برداشته می‌شن.
            try:
                with open(SHARED_CONFIG_FILE, "r", encoding="utf-8") as f:
                    disk = json.load(f)
            except Exception:
                disk = {}

            merged = dict(disk)
            for key, value in shared_out.items():
                if key not in merged or value != _shared_snapshot.get(key):
                    merged[key] = value

            _atomic_write_json(SHARED_CONFIG_FILE, merged)
            _shared_snapshot = _snapshot(merged)
            # عمداً _shared_config_mtime رو دست نمی‌زنیم: اگه توی همین
            # ادغام تغییرِ یه ربات دیگه وارد شده باشه، می‌خوایم حلقه‌ی
            # اصلی با reload_shared_config_if_changed اون رو *با همه‌ی
            # اثرات جانبیش* (زبان/پروکسی) هم اعمال کنه، نه فقط توی فایل.
        except Exception:
            logging_setup.log_exception()

def reload_shared_config_if_changed():
    """
    اگه یه ربات دیگه‌ی همین سرور shared_config.json رو عوض کرده باشه (مثلاً
    پروکسی رو عوض کرده)، این تابع (که توی لوپ اصلی صدا زده می‌شه) تغییرات رو
    توی همین پروسه هم زنده اعمال می‌کنه -- بدون نیاز به ری‌استارت.
    identity این ربات (نیک/کانال/دیوایس/last_state) دست‌نخورده می‌مونه.
    """
    global cfg, _shared_config_mtime, _shared_snapshot
    try:
        mtime = os.path.getmtime(SHARED_CONFIG_FILE)
    except OSError:
        return
    if mtime == _shared_config_mtime:
        return
    _shared_config_mtime = mtime
    try:
        with open(SHARED_CONFIG_FILE, "r", encoding="utf-8") as f:
            shared = json.load(f)
    except Exception:
        logging_setup.log_exception("reloading shared_config.json")
        return
    _deep_merge_defaults(shared, _SHARED_DEFAULTS)
    _shared_snapshot = _snapshot(shared)
    for key, value in shared.items():
        if key == "server":
            cfg["server"]["host"] = value.get("host", cfg["server"].get("host"))
            cfg["server"]["port"] = value.get("port", cfg["server"].get("port"))
        else:
            cfg[key] = value
    i18n.set_language(cfg.get("language", "en"))
    proxy_state.configure(cfg["proxy"].get("enabled", False), cfg["proxy"].get("url"))
    apply_fn = getattr(bot, "apply_proxy_to_player", None)
    if apply_fn:
        try:
            apply_fn()
        except Exception:
            logging_setup.log_exception("re-applying proxy after shared_config reload")

cfg = None
_shared_config_mtime = 0
_cookies_managed = False

def _init_config_and_dirs():
    """خوندن کانفیگ، راه‌اندازی لاگ/زبان و پوشه‌های سرور."""
    global cfg, _shared_config_mtime, _cookies_managed
    cfg = load_config()
    try:
        _shared_config_mtime = os.path.getmtime(SHARED_CONFIG_FILE)
    except OSError:
        _shared_config_mtime = 0

    logging_setup.setup()
    i18n.load_languages()
    i18n.set_language(cfg.get("language", "en"))

    bot.server_dir = _group_dir
    # کوکیِ مشترکِ سرور؛ فقط نصب‌های شخصی ازش استفاده می‌کنن (core/cookie_files.py).
    bot.cookies_dir = os.path.join(_group_dir, "cookies")
    os.makedirs(bot.cookies_dir, exist_ok=True)
    _cookies_managed = license_gate.is_managed(_bot_dir)

def _cookies_file_for(service_name):
    """
    فایل کوکی‌ای که این ربات برای یه سرویس استفاده می‌کنه. اول کوکیِ خودِ
    همین ربات؛ کوکیِ مشترکِ سرور فقط برای نصب‌های غیرمدیریت‌شده، تا کوکیِ
    یه مشتری هیچ‌وقت به ربات مشتریِ دیگه‌ای روی همون سرور نرسه.

    وقتی هیچ فایلی نیست، مسیرِ مخصوصِ خودِ ربات برمی‌گرده (که وجود نداره)
    -- صداکننده‌ها با os.path.exists چک می‌کنن.
    """
    found = cookie_files.resolve(_bot_dir, _group_dir, service_name, _cookies_managed)
    if found:
        return found
    try:
        return cookie_files.path_in(_bot_dir, service_name)
    except cookie_files.CookieError:
        return os.path.join(_bot_dir, "cookies", "_invalid_.txt")

def _migrate_legacy_cookies():
    """کوکی‌های قدیمی (یه فایل مشترک برای یوتیوب، یه فایل جدا برای اینستاگرام) رو به پوشه‌ی جدید منتقل می‌کنه."""
    old_youtube = os.path.join(_group_dir, "cookies.txt")
    new_youtube = _cookies_file_for("youtube")
    if os.path.isfile(old_youtube) and not os.path.isfile(new_youtube):
        try:
            os.replace(old_youtube, new_youtube)
            print(f"[Migration] کوکی یوتیوب منتقل شد -> {new_youtube}")
        except OSError:
            pass

    old_instagram = os.path.join(_group_dir, "instagram_cookies.txt")
    new_instagram = _cookies_file_for("instagram")
    if os.path.isfile(old_instagram) and not os.path.isfile(new_instagram):
        try:
            os.replace(old_instagram, new_instagram)
            print(f"[Migration] کوکی اینستاگرام منتقل شد -> {new_instagram}")
        except OSError:
            pass

def _init_cookies():
    bot.cookies_file_for = _cookies_file_for
    _migrate_legacy_cookies()
    bot.bot_dir = _bot_dir

t = player = manager = None

def _create_core_objects():
    """کلاینت تیم‌تاک، پلیر mpv و مدیر سرویس‌ها."""
    global t, player, manager
    t = TTBot()

    _player_cfg = cfg.get("player", {})
    # log_level="warn" (نه "info"): هر پیام لاگ mpv باید از مرز ctypes رد بشه و
    # یه رکورد پایتونی بسازه، در حالی که logging_setup هرچی زیر WARNING باشه رو
    # دور می‌ریزه. یعنی با "info" داشتیم برای چیزی که مستقیم سطل زباله می‌رفت
    # CPU خرج می‌کردیم.
    player = Player(
        log_handler=logging_setup.mpv_log_handler,
        log_level=_player_cfg.get("log_level", "warn"),
        demuxer_max_bytes=_player_cfg.get("demuxer_max_bytes"),
        demuxer_max_back_bytes=_player_cfg.get("demuxer_max_back_bytes"),
        network_timeout=_player_cfg.get("network_timeout"),
        allow_mpv_ytdl=_player_cfg.get("allow_mpv_ytdl"),
    )
    manager = ServiceManager()

license_state = None

def _license_gate_and_bind():
    """پروکسی، هم‌ترازی و گیتِ لایسنس، و وصل‌کردنِ اشیای اصلی به bot."""
    global license_state
    # --- لایسنس ---
    # اگه این نمونه از طریق پلتفرم فروش ساخته شده باشه، یه license.json کنار
    # identity.json هست و فقط سرویس‌ها/دستورهای خریداری‌شده لود می‌شن. اگه
    # نباشه (نصب شخصی، نسخه‌ی توسعه، نصب‌های قبل از لایسنس) ربات کامل و بدون
    # هیچ محدودیتی بالا میاد -- توضیح کامل توی core/license_gate.py.
    #
    # license.json همیشه از قبل روی دیسکه: یا پلتفرم مستقیم نوشتتش (میزبانی
    # روی سرور خودمون)، یا launcher.py قبل از استارت این پروسه از سرویس
    # اجاره‌ای (core/license_remote.py، Cloudflare KV) گرفته و نوشته. اینجا
    # فقط خونده می‌شه -- هیچ تماس شبکه‌ای جدیدی گرفته نمی‌شه.
    proxy_state.configure(cfg.get("proxy", {}).get("enabled", False), cfg.get("proxy", {}).get("url"))

    license_state = license_gate.load(_bot_dir)
    bot.license = license_state

    if license_state.blocks_startup():
        print(f"[Startup] this bot will not run: {license_state.status_text()}")
        if license_state.unlicensed:
            print(f"[Startup] a valid {license_gate.LICENSE_FILE_NAME} is required next to {IDENTITY_FILE}")
            print("[Startup] customers: buy or renew in the licensing Telegram bot.")
            print("[Startup] owner: python manage.py self-license <telegram_id>")
        else:
            print("[Startup] renew with /renew in the licensing Telegram bot.")
        sys.exit(3)

    print(f"[Startup] {license_state.status_text()}"
          + (f" (key {license_state.key})" if license_state.key else ""))

    # bot.cfg قبل از لودِ سرویس‌ها: _ytdlp_service._resolve_cookiefile تنظیمِ ck
    # رو از bot.cfg می‌خونه. قبلاً اینجا هنوز ست نشده بود، پس موقعِ استارت
    # ck نادیده گرفته می‌شد ولی «rs services» (بعد از ست‌شدنِ cfg) رعایتش
    # می‌کرد -- یعنی یوتیوب بعد از استارت کار می‌کرد و بعد از rs services نه.
    bot.cfg = cfg
    bot.services = license_gate.filter_services(license_state, manager.load_services())

    bot.t = t
    bot.player = player
    bot.cfg = cfg
    bot.i18n = i18n
    bot.manager = manager

# --- صف پخش ---
# mpv در هر لحظه فقط *یک* آیتم داره؛ صاحب حقیقت صف، core/trackqueue.py است.
# دلیلش و مزیتش کامل اون‌جا نوشته شده -- خلاصه‌اش: n دیگه به وضعیت داخلی mpv
# وابسته نیست، آیتم بعدی از قبل resolve می‌شه (پس n بدون تأخیر شروع می‌شه)،
# و رشد صف از روی شمارش واقعی انجام می‌شه نه حدس.
#
# منبع رشد: وقتی کاربر یه سرچ/پلی‌لیست پخش می‌کنه، اینجا ثبت می‌شه که
# آیتم‌های بیشتر از کجا باید بیان.
def _resolve_stub(stub):
    """
    یه stub رو به لینک قابل‌پخش تبدیل می‌کنه.

    اسم سرویس از خود stub خونده می‌شه (کلید _service که موقع رشد گذاشته
    می‌شه). اگه سرویس resolve_stub نداشت None برمی‌گرده و صف خودش اون آیتم
    رو رد می‌کنه.
    """
    if not isinstance(stub, dict):
        return None
    service = bot.services.get(stub.get("_service"))
    if service is None or not hasattr(service, "resolve_stub"):
        return None
    try:
        return service.resolve_stub(stub)
    except Exception:
        logging_setup.log_debug(f"resolve_stub failed ({stub.get('_service')})")
        return None


def _grow_queue(needed):
    """
    آیتم بیشتر برای صف. صف خودش این رو در پس‌زمینه صدا می‌زنه وقتی به آخر
    نزدیک می‌شه -- پس اینجا هیچ تصمیمی درباره‌ی «کِی» گرفته نمی‌شه، فقط «چی».

    برخلاف نسخه‌ی قبلی هیچ resolve ای اینجا انجام نمی‌شه: فقط stub برگشت
    داده می‌شه و صف موقع رسیدن کرسر (یا توی prefetch) resolveشون می‌کنه.
    همین تنها دلیلیه که این تابع به‌جای ~۷۰ خط، این اندازه‌ست.

    منبع از همون search_session / playlist_growth_session خونده می‌شه که
    p/pl از قبل پرش می‌کنن -- یعنی قرارداد قبلی دست‌نخورده می‌مونه.
    """
    needed = max(int(needed), 5)

    with bot.search_lock:
        search = dict(bot.search_session)
        playlist = dict(bot.playlist_growth_session)

    # ۱) سرچ متنی
    query = search.get("query")
    if query:
        service = bot.services.get(search.get("service"))
        if service is not None and hasattr(service, "search_batch"):
            already = len(search.get("stubs") or [])
            try:
                stubs = service.search_batch(query, count=already + needed) or []
            except Exception:
                logging_setup.log_debug(f"search_batch growth failed for '{query}'")
                stubs = []
            fresh = stubs[already:]
            if fresh:
                with bot.search_lock:
                    # اگه کاربر وسط کار چیز دیگه‌ای پخش کرده، نتیجه رو دور بریز.
                    if bot.search_session.get("query") != query:
                        return []
                    bot.search_session["stubs"] = stubs
                    bot.search_session["resolved_upto"] = len(stubs)
                # رشدِ سرچِ متنی -- مثلِ نتیجه‌ی اولیه‌ی همون سرچ، عمومیه.
                return _as_queue_items(fresh, search.get("service"), private=False)

    # ۲) پلی‌لیست بزرگ لینک‌مستقیم
    url = playlist.get("url")
    if url:
        service = bot.services.get(playlist.get("service"))
        loaded, total = int(playlist.get("loaded") or 0), int(playlist.get("total") or 0)
        if service is not None and hasattr(service, "grow_playlist") and loaded < total:
            try:
                stubs = service.grow_playlist(url, loaded, needed) or []
            except Exception:
                logging_setup.log_debug(f"grow_playlist failed for '{url}'")
                stubs = []
            if stubs:
                with bot.search_lock:
                    if bot.playlist_growth_session.get("url") != url:
                        return []
                    bot.playlist_growth_session["loaded"] = loaded + len(stubs)
                # رشدِ پلی‌لیستِ لینکِ مستقیم -- مثلِ خودِ لینک، خصوصیه.
                return _as_queue_items(stubs, playlist.get("service"), private=True)

    return []


def _as_queue_items(stubs, service_name, private):
    """
    stub های خام سرویس رو به شکلی که صف می‌فهمه تبدیل می‌کنه.

    private صراحتاً روی هر آیتم ثبت می‌شه (نه فقط پارامتر append/replace)
    چون _grow_now همیشه با append() صدا زده می‌شه که پیش‌فرضش private=True
    است؛ بدون این، رشدِ خودکارِ یه سرچِ عمومی هم خصوصی حساب می‌شد و k روی
    آیتم دوم به بعد همیشه «لینک خصوصیه» می‌گفت.
    """
    items = []
    for stub in stubs:
        if not isinstance(stub, dict):
            continue
        already_resolved = bool(stub.get("public_url") and stub.get("url"))
        item = {
            "title": stub.get("title"),
            # stubِ خام لینک صفحه‌ش رو توی webpage_url/url داره؛ ولی آیتمی که
            # سرویس همین الان resolve کرده (مثل رشد پلی‌لیست یوتیوب) توی url
            # لینک *استریم* داره و لینک عمومی توی public_url -- قبلاً همون
            # استریم به‌عنوان لینک عمومی ثبت می‌شد.
            "public_url": (stub.get("public_url") if already_resolved
                           else stub.get("webpage_url") or stub.get("url")),
            "service": service_name,
            "info": stub.get("info") or track_meta.from_info(stub),
            "private": private,
        }
        if already_resolved:
            item["url"] = stub["url"]
        else:
            item["stub"] = dict(stub, _service=service_name)
        items.append(item)
    return items


def _play_and_confirm(url):
    """
    مثلِ player.play، ولی اگه mpv واقعاً بازش نکنه (۴۰۳، لینکِ منقضی،
    قطعیِ شبکه) یه استثنا می‌ندازه تا trackqueue._play_index بگیردش و
    بره سراغِ آیتمِ بعدیِ صف -- دقیقاً همون تلاشی که از قبل برای آیتمِ
    خراب داشت، فقط قبلاً فقط استثنای *همزمانِ* خودِ فراخوانی رو می‌گرفت،
    نه شکستِ *غیرهمزمانِ* خودِ mpv یه لحظه بعد.

    بدونِ این، لینکِ خرابِ صف به‌عنوانِ «resolve موفق» گزارش می‌شد:
    broadcast_now_playing برای آهنگی که هیچ‌وقت واقعاً پخش نشد می‌رفت، و
    housekeeping یه تیک بعد mpv رو idle می‌دید و دوباره advance می‌کرد --
    یعنی «Now playing» تکراری/پشتِ‌سرهم برای دو آیتمِ متوالی و پرشِ
    خودکارِ غیرمنتظره‌ای که کاربر گزارش داد. تابعِ تأییدش (core/
    command_helpers.py::_confirm_playback) قبلاً فقط برای مسیرِ «لینکِ
    خام به mpv» استفاده می‌شد؛ برای لایوِ کند هم امنه چون فقط وقتی
    current_url زودهنگام None بمونه شکست حساب می‌کنه، نه صرفاً بافرکردنِ
    طولانی.
    """
    player.play(url)
    if not command_helpers._confirm_playback(bot):
        raise RuntimeError("mpv did not confirm playback")


def _init_queue():
    bot.queue = trackqueue.TrackQueue(
        play_fn=_play_and_confirm,
        resolve_fn=_resolve_stub,
        grow_fn=_grow_queue,
        submit_fn=workers.submit,
    )

    youtube_api_state.configure(cfg.get("youtube_api", {}).get("enabled", False), cfg.get("youtube_api", {}).get("key", ""))

def _apply_proxy_to_player():
    """
    پروکسی رو به خودِ mpv هم اعمال می‌کنه، نه فقط به yt-dlp/m3u8.
    توجه: تا اینجا پروکسی فقط برای گرفتن لینک پخش (جستجو/متادیتا) استفاده
    می‌شد، ولی خودِ استریم واقعی (googlevideo.com و مشابه) مستقیم و بدون
    پروکسی باز می‌شد؛ همینه که می‌تونه باعث «Connection failed» توی mpv بشه
    حتی وقتی جستجو با پروکسی مشکلی نداشته.
    """
    try:
        player.set_proxy(proxy_state.get_proxy_url())
    except Exception:
        logging_setup.log_exception()

# --- لاین صدا ---
# مقدار audio.input_device/output_device می‌تونه سه شکل داشته باشه:
#   "line:<slug>"  -> لاین صدای مدیریت‌شده (روی لینوکس اگه وجود نداشته باشه
#                     همین‌جا دوباره ساخته می‌شه، پس ربات بعد از ریبوت
#                     سرور بدون کار دستی بالا میاد)
#   اسم دستگاه     -> با اسم پیدا می‌شه، نه با شماره
#   عدد            -> شماره‌ی خام، فقط برای سازگاری با کانفیگ‌های قدیمی
# اسم بر شماره ترجیح داره چون شماره‌ی دستگاه‌ها روی لینوکس با هر ری‌استارت
# پالس‌اودیو عوض می‌شه و ربات به یه دستگاه کاملاً دیگه وصل می‌شد.
_last_state = None
_srv_list = []

def _init_audio_and_volume():
    """دستگاه‌های ورودی/خروجی، صدای آخرین وضعیت، و لیست سرویس‌های جستجوپذیر."""
    global _last_state, _srv_list
    _input_dev = cfg["audio"]["input_device"]
    try:
        # یه اسم ممکنه به چند دستگاه (WinMM/DirectSound/WASAPI یا ALSA/Pulse)
        # اشاره کنه و همه‌شون باز نشن؛ پس تا اولینی که واقعاً باز می‌شه جلو می‌ریم.
        _dev_id, _dev_name, _tried = audio_lines.open_input_device(t.set_input_device, _input_dev)
        # تست سلامت از روی همین می‌فهمه ورودی بازه؛ نباید دوباره بازش کنه.
        bot.audio_input = (_dev_id, _dev_name)
        if _tried:
            skipped = ", ".join(f"[{i}] {n}" for i, n, _e in _tried)
            print(f"[Startup] دستگاه ورودی صدا: [{_dev_id}] {_dev_name} "
                  f"(این‌ها باز نشدن و رد شدن: {skipped})")
    except Exception as e:
        logging_setup.log_debug(f"input device set failed ({_input_dev}), using default: {e}")
        print(f"[Startup] دستگاه ورودی صدا ({_input_dev}) تنظیم نشد؛ صدای ربات ممکنه توی کانال شنیده نشه: "
              f"{logging_setup.safe_error_text(e)}")

    output_dev = cfg["audio"]["output_device"]
    try:
        resolved_output = audio_lines.resolve_output_device(output_dev)
        if isinstance(resolved_output, int):
            player.set_output_device_by_index(resolved_output)
        else:
            player.set_output_device(str(resolved_output))
    except Exception as e:
        logging_setup.log_debug(f"output device set failed ({output_dev}), using default: {e}")
        print("[Startup] دستگاه خروجی صدای تنظیم‌شده در کانفیگ پیدا نشد، از دیوایس پیش‌فرض استفاده می‌شه.")

    _last_state = cfg.setdefault("last_state", {"volume": 50, "service_index": 0})
    try:
        player.volume = max(0, min(100, _last_state.get("volume", 50)))
    except Exception:
        logging_setup.log_exception()
    _srv_list = searchable_service_names(bot.services)

def _restore_service_index():
    """
    سرویس فعال با «اسم» ذخیره می‌شه، نه شماره.

    قبلاً فقط شماره (service_index) ذخیره می‌شد؛ ولی لیست سرویس‌ها از روی
    فایل‌های پوشه‌ی core/services ساخته می‌شه، پس اگه یه سرویس لود نشه
    (مثلاً radiojavan وقتی requests نصب نیست) همه‌ی شماره‌ها می‌لغزن و ربات
    روی یه سرویس کاملاً دیگه بالا میاد. با اسم، این اتفاق نمی‌افته.
    """
    if not _srv_list:
        return 0
    saved_name = _last_state.get("service")
    if saved_name in _srv_list:
        return _srv_list.index(saved_name)
    # سازگاری با کانفیگ‌های قدیمی که فقط شماره داشتن
    saved_index = _last_state.get("service_index", 0)
    if isinstance(saved_index, int) and 0 <= saved_index < len(_srv_list):
        return saved_index
    return 0

def _init_playback_state():
    bot.current_service_index = _restore_service_index()
    bot.reconnecting = False
    bot.track_meta = []
    bot.status_visible = cfg.get("status", {}).get("visible", True)
    bot.normalize_enabled = cfg.get("audio_normalize", False)
    bot.channel_messages_enabled = cfg.get("channel_messages_enabled", True)
    bot.playback_lock = threading.Lock()
    bot.last_channel_url = None
    bot.channel_playlist_index = None
    bot.last_started = None

    bot.playback_modes = {1: "single", 2: "playlist", 3: "repeat_track", 4: "repeat_playlist"}
    # فقط رفتارِ «آهنگ تموم شد» رو تعیین می‌کنه (core/trackqueue.py:
    # advance/on_track_finished) -- نه این‌که یه سرچ/پلی‌لیست چندتا آیتم
    # می‌گیره یا نه (E5؛ قبلاً bot.single_track_modes همین‌جا هم اثر می‌ذاشت).
    bot.playback_mode = 2

def _resolve_mode(query):
    """با عدد (1، 2) یا اسم (single، playlist) مُد رو پیدا می‌کنه؛ اگه نبود None."""
    query = (query or "").strip().lower()
    if query.isdigit() and int(query) in bot.playback_modes:
        return int(query)
    for num, name in bot.playback_modes.items():
        if name == query:
            return num
    return None

def _init_roam_state():
    bot.roam_timeout_seconds = 300
    bot.roam_lock = threading.Lock()
    bot.roam_state = {
        "active": False,
        "requester_uid": None,
        "requester_username": None,
        "origin_channel_id": None,
        "origin_channel_password": None,
        "deadline": None,
    }

def _roam_set_deadline():
    with bot.roam_lock:
        if bot.roam_state["active"] and bot.roam_state["deadline"] is None:
            bot.roam_state["deadline"] = time.time() + bot.roam_timeout_seconds

def _roam_clear_deadline():
    with bot.roam_lock:
        if bot.roam_state["active"]:
            bot.roam_state["deadline"] = None

def _return_home():
    """برگشت به کانال اصلی (قبل از come) و برگردوندن اسم به پیش‌فرض."""
    with bot.roam_lock:
        if not bot.roam_state["active"]:
            return
        origin_id = bot.roam_state["origin_channel_id"]
        origin_pw = bot.roam_state["origin_channel_password"] or ""
        bot.roam_state["active"] = False
        bot.roam_state["requester_uid"] = None
        bot.roam_state["requester_username"] = None
        bot.roam_state["deadline"] = None

    if origin_id is not None:
        _do_join(origin_id, origin_pw)
    try:
        t.set_name(cfg["server"]["nickname"])
    except Exception:
        logging_setup.log_debug("restoring nickname after roaming failed")

def _init_search_state():
    bot.search_batch_size = 5
    bot.search_lock = threading.Lock()
    bot.search_session = {
        "service": None,
        "query": None,
        "stubs": [],
        "resolved_upto": 0,
        "loading": False,
    }

def _channel_broadcast(text):
    """
    جایگزین t.channel_message مستقیم: اگه ارسال پیام توی کانال با دستور cm
    غیرمجاز شده باشه، هیچی فرستاده نمی‌شه (پیام‌های خصوصی/user_message تحت
    تأثیر این تنظیم نیستن).

    Resilient: اگه ارسال fail بشه (rate-limit، سرور موقتاً جواب نده، و...)
    exception رو قورت می‌ده و فقط log می‌کنه -- یه پیام اطلاع‌رسانی ناموفق
    نباید کل دستوری که صداش زده (پخش، جستجو، ...) رو بشکنه.
    """
    if not bot.channel_messages_enabled:
        return
    try:
        t.channel_message(text)
    except Exception:
        logging_setup.log_debug("channel_broadcast failed, message dropped")

def _apply_normalize():
    """یکسان‌سازی بلندی صدا (loudnorm) تا صدای فایل‌های مختلف موقع n/b یهو خیلی بلند/کم نشه."""
    try:
        player.set_normalize(bot.normalize_enabled)
    except Exception:
        logging_setup.log_exception()

def is_admin(username):
    return username in cfg.get("admins", [])

def _sender_allowed(uid, username):
    """
    بر اساس cfg["access"]["mode"] تعیین می‌کنه کاربری که بیرون از کانال
    خودِ رباته می‌تونه دستور بده یا نه:
      all            -> همه، فارغ از این‌که توی کانال باشن یا نه
      admins_outside -> فقط مدیرها می‌تونن از بیرون کانال دستور بدن
      none           -> هیچ‌کس از بیرون کانال نمی‌تونه (حتی مدیر)
    """
    mode = cfg.get("access", {}).get("mode", "all")
    if mode == "all":
        return True
    try:
        sender_channel = t.get_user_info(uid)["channel_id"]
        my_channel = t.get_user_info()["channel_id"]
    except Exception:
        return True
    if sender_channel == my_channel:
        return True
    if mode == "admins_outside":
        return is_admin(username)
    return False

def stop_player():
    """
    فقط متوقف کردن پخش فعلی برای باز شدن مسیر پخش جدید.

    mark_stopped لازمه: حلقه‌ی اصلی «mpv بیکار شد» رو به‌عنوان «آهنگ تموم
    شد» تفسیر می‌کنه و خودکار به آیتم بعدی می‌ره. بدون این، هر توقف عمدی
    (s، کانال خالی، پخش جدید) باعث یه پرش ناخواسته به آهنگ بعدی می‌شد.
    """
    try:
        queue = getattr(bot, "queue", None)
        if queue is not None:
            queue.mark_stopped()
    except Exception:
        pass
    try:
        player.stop()
    except Exception:
        logging_setup.log_debug("stop_player() failed")
    # توقفِ عمدی (s/ss، قطع‌اتصال، full_shutdown) نباید یه دانلودِ پس‌زمینه‌ی
    # DVR رو زنده نگه داره -- load_and_play فقط وقتی صدا زده می‌شه که پخشِ
    # *جدیدی* شروع بشه، نه وقتی فقط متوقف می‌شیم.
    try:
        live_dvr.clear(bot)
    except Exception:
        logging_setup.log_debug("live_dvr.clear() during stop_player() failed")

def full_shutdown():
    """قطع اتصال کامل ربات و پلیر جهت ری‌استارت تمیز"""
    stop_player()
    try:
        t.disconnect()
    except Exception:
        logging_setup.log_debug("disconnect during full_shutdown failed")

def format_time(seconds):
    if seconds is None or seconds < 0: return "0 seconds"
    seconds = int(seconds)
    periods = [('week', 604800), ('day', 86400), ('hour', 3600), ('minute', 60), ('second', 1)]
    result = []
    for name, count in periods:
        value = seconds // count
        if value > 0:
            result.append(f"{value} {name}{'s' if value > 1 else ''}")
            seconds %= count
    return ", ".join(result) if result else "0 seconds"

def _send_long_text(send_fn, text):
    """
    برای خروجی‌های لیست‌مانند (لیست پلی‌لیست‌ها، کانال‌های تلویزیونی، دستورات
    و ...) که می‌تونن راحت از ۵۱۲ کاراکتر رد بشن.

    قبلاً خودمون متن رو به تکه‌های ۴۰۰ کاراکتری می‌شکستیم و هرکدوم رو با
    send_fn جدا می‌فرستادیم -- یه لایه‌ی محافظتی اضافه، برای وقتی که سمت
    گیرنده تقسیم چندبخشیِ خودِ پروتکل تیم‌تاک (bMore) رو درست پیاده نکرده
    باشه. کلاینت رسمی این رو درست پیاده کرده و پیام رو دوباره یکپارچه
    نشون می‌ده؛ تکه‌کردنِ دستیِ ما همون چیزی بود که باعث می‌شد یه خروجیِ
    بلند (مثل q/help/al) به‌جای یه پیام، چندتا پیامِ جدا توی چت دیده بشه.
    حالا فقط یه‌بار send_fn صدا زده می‌شه؛ تقسیمِ واقعیِ بستهٔ پروتکل و
    retry/صف‌کردنِ شکست‌خورده‌ها از قبل توی core/teamtalk/ttbot.py
    (buildTextMessage/bMore، _send_chunks) درست پیاده شده -- اینجا دیگه
    لازم نیست دوباره انجام بشه.
    """
    try:
        send_fn(text)
    except Exception as e:
        # همون قاعده‌ی قبلی: شکستِ فرستادن نباید کل دستور رو با یه
        # command_error بترکونه -- ttbot خودش پیام رو صف کرده و دوباره
        # امتحان می‌کنه.
        logging_setup.log_debug(f"send_long_text failed (queued for retry by ttbot): {e}")

def _init_join_state():
    bot.self_initiated_join = False
    bot.last_join_time = 0

def _do_join(channel_id, password=""):
    """
    به‌جای صدا زدن مستقیم t.join، همیشه از این استفاده کن. این کمک می‌کنه
    توی رویداد user_join تشخیص بدیم که ورود ما به یه کانال، خودمون باعثش
    بودیم (connect اولیه/kicked-rejoin/come/back) یا یه ادمین دیگه ما رو
    move کرده (که در اون صورت باید به‌عنوان کانال خونه‌ی جدید ذخیره بشه).
    """
    bot.self_initiated_join = True
    try:
        result = t.join(channel_id, password)
        bot.last_join_time = time.time()
        return result
    finally:
        bot.self_initiated_join = False

_FATAL_RECONNECT_CODES = set()  # توی _load_native_modules پر می‌شه (به ClientError وابسته‌ست)

def connect_bot():
    try:
        # قطع اتصال قبلی (اگه وجود داشت). شکستنش عادیه (شاید اصلاً وصل
        # نبودیم)، پس فقط توی debug.log ثبت می‌شه نه به‌عنوان خطای مهم.
        t.disconnect()
    except Exception:
        logging_setup.log_debug("pre-connect disconnect failed (usually harmless)")
    logging_setup.set_operation(f"connecting to {cfg['server']['host']}:{cfg['server']['port']}")
    t.set_server(cfg["server"]["host"], cfg["server"]["port"], cfg["server"]["port"])
    t.connect()
    t.login(cfg["server"]["nickname"], cfg["server"]["username"], cfg["server"]["password"], "Audio Player Bot")
    _do_join(cfg["channel"]["id"], cfg["channel"].get("password", ""))
    _minimize_all_subscriptions()
    # سرور بعد از هر لاگین استاتوسِ قبلی رو نداره؛ بدون این، تا عوض‌شدنِ
    # آهنگ، ربات بی‌استاتوس می‌موند.
    status_line.invalidate()
    logging_setup.set_operation("idle")

def _minimize_and_verify(user_id, username=""):
    """
    اشتراک‌های غیرلازم یه کاربر رو قطع می‌کنه، بدون بلاک‌کردن.

    قبلاً اینجا منتظر تأیید سرور می‌موند و بعدش وضعیت رو می‌خوند و برای هر
    کاربر یه خط توی connection.log می‌نوشت. روی سرور شلوغ این یعنی هم
    دقیقه‌ها تأخیر توی استارت، هم صدها بار باز/بسته کردن فایل لاگ. حالا
    فقط دستور فرستاده می‌شه (که خودِ SDK ترتیبش رو تضمین می‌کنه) و نتیجه‌ی
    کلی یه‌جا لاگ می‌شه، نه تک‌تک.
    """
    return bool(t.minimize_subscriptions(user_id))

MINIMIZE_SUBS_BATCH_SIZE = 25    # این‌قدر پشت‌سرهم بدون مکث بفرست
MINIMIZE_SUBS_BATCH_PAUSE = 0.3  # بعد از هر batch این‌قدر صبر کن (ثانیه)

def _minimize_all_subscriptions():
    """
    این ربات فقط پخش می‌کنه؛ نیازی به گرفتن صدا/تصویر/دسکتاپ/فایل‌مدیا/پیام
    کانال از بقیه‌ی کاربرها نداره. برای صرفه‌جویی مصرف اینترنت/CPU، اشتراک
    این‌ها رو برای همه‌ی کاربرهای فعلی سرور قطع می‌کنیم (پیام خصوصی دست‌نخورده
    می‌مونه، چون دستورات از همون راه میان).

    نکته‌ی مهم: doUnsubscribe مثل هر دستور دیگه‌ای تابع محدودیت نرخِ خودِ
    سرور TeamTalk (AbusePrevention) هست. روی یه سرور با هزار کاربر، فرستادن
    هزار دستور پشت‌سرهم بدون هیچ مکثی می‌تونه از سقف نرخ سرور رد بشه --
    یعنی خیلی از این unsubscribe ها بی‌صدا نادیده گرفته می‌شن (SDK هنوزم
    cmd_id مثبت برمی‌گردونه چون دستور محلی صف شده، ولی سرور واقعاً اجراش
    نمی‌کنه)، بدون این‌که هیچ خطایی این‌جا دیده بشه. برای همین هر
    MINIMIZE_SUBS_BATCH_SIZE کاربر یه مکث کوتاه می‌ذاریم.
    """
    try:
        my_id = t.my_id()
        total = 0
        failed = 0
        for user in t.get_server_users():
            if user.get("user_id") == my_id:
                continue
            total += 1
            try:
                if not _minimize_and_verify(user["user_id"], user.get("username", "")):
                    failed += 1
            except Exception:
                failed += 1
            if total % MINIMIZE_SUBS_BATCH_SIZE == 0:
                time.sleep(MINIMIZE_SUBS_BATCH_PAUSE)
        logging_setup.log_info(f"minimized subscriptions for {total - failed}/{total} users")
    except Exception:
        logging_setup.log_exception("minimizing subscriptions for existing users")

def _initial_connect():
    """
    اتصال اولِ استارت، با تلاش مجدد.

    قبلاً connect_bot() مستقیم و بدون محافظ صدا زده می‌شد: اگه لحظه‌ی
    بالا اومدن ربات سرور در دسترس نبود (یا اینترنت هنوز وصل نشده بود)،
    کل پروسه با traceback می‌مرد -- در حالی که برای قطعی‌های بعد از
    استارت، منطق reconnect کامل از قبل وجود داشت. حالا استارت هم دقیقاً
    همون رفتار رو داره. فقط خطاهای دائمی سرور (بن/اکانت نامعتبر) باعث
    خروج می‌شن، چون تکرارشون بی‌فایده‌ست.
    """
    rw_cfg = cfg.get("reconnect_wait", {"first_seconds": 0, "repeat_seconds": 10})
    wait_seconds = rw_cfg.get("repeat_seconds", 10) or 10
    attempt = 0
    while True:
        attempt += 1
        try:
            connect_bot()
            if attempt > 1:
                logging_setup.log_info(f"connected on startup attempt {attempt}")
                print(f"[Connection] وصل شد (تلاش {attempt}).")
            return
        except TeamTalkCommandError as e:
            logging_setup.log_exception(f"initial connect attempt {attempt} rejected by server")
            if e.error_code in _FATAL_RECONNECT_CODES:
                print(f"[Connection] سرور اجازه نداد: {e.error_message or e.error_code}. "
                      "این خطا با تکرار درست نمی‌شه (یوزر/پسورد یا بن)، پس ربات بسته می‌شه.")
                sys.exit(1)
        except Exception:
            logging_setup.log_exception(f"initial connect attempt {attempt} failed")
        print(f"[Connection] اتصال اول ناموفق بود (تلاش {attempt})؛ {wait_seconds} ثانیه دیگه دوباره امتحان می‌کنم...")
        time.sleep(wait_seconds)

def _expand_item(url, title, public_url, private, verified=False):
    """
    یک آیتم رو باز می‌کنه: اگه m3u8/m3u ساده (نه HLS واقعی) بود به چند لینک
    جدا تبدیلش می‌کنه (که در اون صورت دیگه عنوان/لینک‌عمومیِ از قبل مشخصی
    نداریم، ولی وضعیت private همون می‌مونه)، وگرنه همون یک لینک با
    اطلاعاتش برمی‌گرده.

    verified=True یعنی این لینک از یه resolver مبتنی بر yt-dlp اومده
    (سرویس‌ها یا core/link_resolver.py) که خودش url رو از formats انتخاب
    کرده -- پس قطعاً یه استریم/فایل واقعیه، نه یه لیستِ متنیِ ساده‌ی
    لینک‌ها که تصادفاً پسوند .m3u8/.m3u داره. توی این حالت resolve_playlist
    اصلاً صدا زده نمی‌شه: یه دانلودِ کاملِ دیگه از خودِ لینک (که برای
    لایوهای یوتیوب/HLS چند ثانیه تمام‌عیار هدر می‌ره) فقط برای نتیجه‌ای که
    از قبل معلومه. لینک‌های خام/تشخیص‌داده‌شده-با-پسوند (که واقعاً ممکنه
    فایل .m3u باشن) verified=False می‌مونن و مثل قبل چک می‌شن.
    """
    if verified:
        return [(url, title, public_url, private)]

    try:
        urls = resolve_playlist(url)
    except Exception:
        urls = [url]

    if len(urls) == 1:
        return [(urls[0], title, public_url, private)]
    return [(u, None, None, private) for u in urls]

def load_and_play(items, private=True, service_name=None):
    """
    items می‌تونه یکی از این‌ها باشه:
      - str                                  یک لینک
      - dict {"url","title","public_url"}    یک لینک به‌همراه اطلاعات شناخته‌شده (مثلاً از سرویس جستجو)
      - list از موارد بالا                   پلی‌لیست (ترکیبی از str/dict هم مجازه)

    private=True یعنی این لینک‌ها شخصی/خصوصی‌ان (مثلاً کاربر مستقیم یه لینک
    فرستاده) و نباید با دستور k به کسی داده بشن. نتیجه‌ی سرویس‌های جستجو
    (مثل یوتیوب) باید با private=False صدا زده بشه.

    service_name (اختیاری): اسم سرویسی که این آیتم‌ها رو تولید کرده
    (مثلاً 'youtube', 'instagram', 'tiktok') -- روی هر آیتم توی track_meta
    ذخیره می‌شه تا پیام‌های "Now playing" (n/b) بتونن نشون بدن از کدوم
    سرویس اومده. None یعنی نامشخص (لینک مستقیم بدون سرویس مشخص).

    پلی‌لیست فعلی پلیر پاک می‌شه، آیتم اول پخش می‌شه و بقیه به صف پلی‌لیست
    اضافه می‌شن. نویگیشن با دستورات n/b انجام می‌شه.
    """

    if isinstance(items, (str, dict)):
        items = [items]

    normalized = []
    # متادیتای نرمال (core/track_meta.py) که سرویس به آیتم چسبونده؛ کلیدش
    # همون لینک قابل‌پخشه تا از _expand_item رد بشه و به صف برسه.
    info_by_url = {}
    # لینک‌هایی که یه resolver مبتنی بر yt-dlp (سرویس‌ها/link_resolver)
    # از قبل تأیید کرده -- توضیح کامل توی _expand_item.
    verified_urls = set()
    # هدرهای HTTP (user_agent/referrer) که resolver برای پخشِ اولین آیتم
    # لازم می‌دونه؛ همون مکانیزمِ IPTV (iptv.apply_stream_headers) اعمالشون می‌کنه.
    stream_headers = None
    for item in items:
        if stream_headers is None and isinstance(item, dict) and item.get("headers"):
            stream_headers = item["headers"]
        if isinstance(item, dict) and item.get("url") and item.get("info"):
            info_by_url[item["url"]] = item["info"]
        if isinstance(item, dict) and item.get("url") and item.get("verified_media"):
            verified_urls.add(item["url"])
        if isinstance(item, dict):
            url = item.get("url")
            title = item.get("title")
            public_url = item.get("public_url")
        else:
            url, title, public_url = item, None, None
        if url:
            normalized.append((url, title, public_url))

    expanded = []
    for url, title, public_url in normalized:
        expanded.extend(_expand_item(url, title, public_url, private, verified=url in verified_urls))

    if not expanded:
        raise ValueError("No playable link found.")

    # پخش هر چیزی که مستند نیست، حالت مستند رو می‌بنده -- وگرنه بعد از یه
    # سرچ معمولی، فرستادن یه عدد هنوز معنیِ «مستند» می‌داشت و کاربر به‌جای
    # پریدن به آیتم پلی‌لیست، یه مستند تحویل می‌گرفت.
    if service_name != documentary.SERVICE_NAME:
        documentary.clear(bot)
    # همون قاعده برای حالت تلویزیون (IPTV): پخش هر چیز دیگه‌ای هم لیستِ
    # شماره‌گذاری‌شده‌ی کانال‌ها رو می‌بنده هم هدرهای HTTP اختصاصیِ کانال
    # قبلی رو از روی پخش‌کننده پاک می‌کنه -- توضیح کامل توی core/iptv.py.
    if service_name != iptv.SERVICE_NAME:
        iptv.clear(bot)
        # بعد از clear (که هدرهای قبلی رو برمی‌گردونه) و قبل از شروعِ پخش؛
        # پخشِ بعدی با clear دوباره پیش‌فرض رو برمی‌گردونه.
        if stream_headers:
            iptv.apply_stream_headers(bot, stream_headers)
    # سشنِ DVR (core/live_dvr.py) هم همین قانون رو داره: پخشِ هر چیزِ دیگه‌ای
    # دانلودِ پس‌زمینه‌ی قبلی رو می‌بنده -- وگرنه یه دانلودِ یتیم روی سرور
    # باز می‌موند تا سقفِ منابعش برسه.
    if service_name != live_dvr.SERVICE_NAME:
        live_dvr.clear(bot)

    # هر پخشِ تازه (سرچ، لینک، کانال...) منبعِ رشدِ قبلی رو کنسل می‌کنه؛ وگرنه
    # صف با نتایج سرچِ قبلی قاطی می‌شد. منبع جدید بعدش توسط
    # start_growth_session / apply_playlist_growth ست می‌شه.
    with bot.search_lock:
        bot.search_session["query"] = None
        bot.search_session["stubs"] = []
        bot.playlist_growth_session["url"] = None

    with bot.playback_lock:
        bot.queue.mode = bot.playback_mode
        count, first = bot.queue.replace(
            [{"url": u, "title": ti, "public_url": pu, "info": info_by_url.get(u)}
             for u, ti, pu, _pr in expanded],
            private=expanded[0][3],
            service=service_name,
        )
        if first is None:
            raise ValueError("No playable link found.")

        # mpv دیگه پلی‌لیست نداره (هر لحظه فقط یک آیتم)، پس loop های خودش
        # باید خاموش باشن -- تکرار آهنگ/صف کار trackqueue است.
        player.loop_current_track = False
        player.loop_queue = False

        if player.is_paused:
            player.resume()

        bot.track_meta = bot.queue.meta()

    bot.last_started = {
        "url": first.url,
        "title": first.title,
        "public_url": first.public_url,
        "private": first.private,
    }

    if not first.private:  # private=False فقط برای نتایج سرویس‌های جستجو
        history.record(bot, first.title, first.public_url)

    _roam_clear_deadline()

    return count

ALIASES_FILE = None

def load_aliases():
    """
    aliases توی فایل جدا (data/aliases.json) نگه داشته می‌شه، نه توی
    config.json. دلیلش: وقتی چندسرور اضافه بشه، هر سرور قراره تنظیمات
    ریزش (از جمله aliases) کاملاً جدا باشه؛ فایل جدا این جدایی رو راحت‌تر
    می‌کنه تا یه کلید مشترک توی یه کانفیگ بزرگ.
    """
    if os.path.exists(ALIASES_FILE):
        try:
            with open(ALIASES_FILE, "r", encoding="utf-8") as f:
                bot.aliases = json.load(f)
        except Exception:
            bot.aliases = {}
    else:
        bot.aliases = {}

def save_aliases():
    with open(ALIASES_FILE, "w", encoding="utf-8") as f:
        json.dump(bot.aliases, f, ensure_ascii=False, indent=4)

def _init_aliases():
    global ALIASES_FILE
    ALIASES_FILE = os.path.join(_bot_dir, "aliases.json")
    bot.aliases = {}
    load_aliases()

RELOADERS = {}

def reloadable(name):
    def deco(func):
        RELOADERS[name] = func
        return func
    return deco

@reloadable("services")
def _reload_services():
    # فیلتر لایسنس باید بعد از هر reload دوباره اعمال بشه، وگرنه "rs services"
    # سرویس‌های خریداری‌نشده رو برمی‌گردوند.
    bot.services = license_gate.filter_services(license_state, manager.load_services())

@reloadable("languages")
def _reload_languages():
    i18n.load_languages()
    if not i18n.set_language(cfg.get("language", "en")):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

@reloadable("aliases")
def _reload_aliases():
    load_aliases()

command_manager = None

def _create_command_manager():
    global command_manager
    command_manager = CommandManager()

@reloadable("commands")
def _reload_commands():
    """
    دستورات پلاگین از پوشه‌ی commands/ رو (دوباره) لود می‌کنه و توی
    COMMANDS ثبت می‌کنه. فایل جدید اضافه کردی یا یه فایل قبلی رو عوض کردی؟
    فقط "rs commands" رو بفرست، نیازی به ری‌استارت کامل نیست.
    """
    plugin_commands = command_manager.load_commands()
    COMMANDS.update(plugin_commands)

    # لایسنس دستورها رو حذف نمی‌کنه؛ فقط سرویس‌ها قفل می‌شن. دستوری که به
    # یه سرویسِ نخریده نیاز داره موقع اجرا می‌گه «توی لایسنست نیست».

COMMANDS = {}

def _handle_number_command(uid, nickname, number):
    """
    عدد خام (بدون هیچ دستوری، مثلاً فقط '3'). سه معنی داره و ترتیبش مهمه:

      ۱. اگه توی حالت مستندیم (md پخش شده)، یعنی «مستند با این شماره».
      ۲. وگرنه اگه توی حالت تلویزیونیم (tv یه لیست نشون داده یا پخش کرده)،
         یعنی «کانال شماره‌ی X از همون لیست».
      ۳. وگرنه اگه یه پلی‌لیست چندآیتمی در جریانه، یعنی برو به اون آیتم.

    مستند و تلویزیون اول چک می‌شن چون هرکدوم همیشه تک‌آیتمی پخش می‌شن
    (queue_length == 1)، پس این معنی‌ها عملاً هیچ‌وقت با هم تعارض ندارن؛ ولی
    معنیِ صریح‌ترِ «حالت مستند/تلویزیون» همیشه باید برنده باشه.
    """
    number_ctx = {"uid": uid, "nickname": nickname}
    if documentary.is_active(bot):
        try:
            item = documentary.play(bot, number)
        except documentary.DocumentaryError as e:
            t.user_message(uid, str(e))
        except Exception as e:
            # از فایل زبان، نه رشته‌ی فارسیِ چسبیده به کد -- وگرنه ربات
            # انگلیسی‌زبان هم همین پیام فارسی رو می‌گرفت (E10).
            command_helpers.notify(bot, number_ctx, "documentary_play_failed",
                                   number=number, error=logging_setup.safe_error_text(e))
        else:
            documentary.announce_playing(bot, item, nickname)
        return

    if iptv.has_list(bot):
        try:
            channel = iptv.play(bot, number)
        except iptv.IPTVError as e:
            t.user_message(uid, str(e))
        except Exception as e:
            command_helpers.notify(bot, number_ctx, "generic_error", error=logging_setup.safe_error_text(e))
        else:
            iptv.announce_playing(bot, channel, nickname)
        return

    if bot.queue.length > 1:
        ok, track = bot.queue.jump(number)
        if ok:
            bot.track_meta = bot.queue.meta()
            # همون خطِ جمع‌وجورِ «Now playing» که n/b/p هم استفاده می‌کنن --
            # نه یه پیامِ جدا که فقط شماره رو تکرار کنه (E12).
            command_helpers.broadcast_now_playing(bot)
        else:
            t.user_message(uid, i18n.t("invalid_playlist_number"))
        return

    t.user_message(uid, i18n.t("unknown_command"))

def on_user_msg(event):
    p = event["params"]
    uid = p["user"]["user_id"]
    nickname = p["user"]["nickname"]
    username = p["user"]["username"]
    msg = p["message"]
    raw_msg = msg.strip()

    if not _sender_allowed(uid, username):
        t.user_message(uid, i18n.t("access_denied"))
        return

    if msg.startswith(" "):
        if raw_msg == "":
            cmd_name, args = "pause_toggle", []
        else:
            cmd_name, args = "p", raw_msg.split(" ")
    elif raw_msg.startswith("http"):
        cmd_name, args = None, None
    else:
        parts = raw_msg.split(" ")
        first_word = parts[0].lower()
        cmd_name = bot.aliases.get(first_word, first_word)
        args = parts[1:]
        # لینکِ بدونِ http:// (مثلاً instagram.com/... یا youtu.be/xyz)
        # هم همون مسیرِ لینکِ کامل رو بره -- فقط وقتی هیچ دستورِ واقعی‌ای
        # با این اسم نیست، تا اسمِ یه دستور تصادفاً قاپیده نشه.
        if cmd_name not in COMMANDS and command_helpers.looks_like_bare_link(raw_msg):
            cmd_name, args = None, None

    if cmd_name is None:
        # لینکِ پیست‌شده (بدون دستور) دقیقاً همون مسیرِ دستورِ صریحِ `u <لینک>`
        # رو می‌ره (core/command_helpers.py::run_link_command) -- قبلاً این
        # دو جا کدِ تقریباً یکسانِ جدا داشتن که به‌مرور از هم دور می‌شدن
        # (E13: کاربر نباید مجبور باشه بینِ «فقط پیستِ لینک» و «u فاصله
        # لینک» فرق قائل بشه).
        link_ctx = {"uid": uid, "nickname": nickname, "username": username, "bot": bot}
        link = command_helpers.normalize_pasted_link(raw_msg)

        def _handle_link():
            command_helpers.run_link_command(bot, link_ctx, link)

        threading.Thread(target=_handle_link, daemon=True).start()
        return

    entry = COMMANDS.get(cmd_name)
    if not entry:
        if cmd_name.isdigit():
            threading.Thread(target=_handle_number_command, args=(uid, nickname, int(cmd_name)), daemon=True).start()
            return
        t.user_message(uid, i18n.t("unknown_command"))
        return

    if entry["role"] != "normal" and not roles.has_role(bot, uid, username, entry["role"]):
        t.user_message(uid, i18n.t("admin_only"))
        return

    # دستور قفل‌شده (با lock/lck) صرف‌نظر از REQUIRED_ROLE اصلیش، فقط برای
    # admin_bot به بالا اجرا می‌شه.
    if cmd_name in bot.cfg.get("locked_commands", []) and not roles.has_role(bot, uid, username, "admin_bot"):
        t.user_message(uid, i18n.t("command_is_locked", command=cmd_name))
        return

    # دستور همیشه هست؛ اگه به یه سرویسِ نخریده (مستند، دانلود، ...) نیاز
    # داشته باشه، همین‌جا با دلیلِ واقعی جواب می‌گیره.
    needed_service = license_gate.service_for_command(cmd_name)
    if needed_service and not license_state.allows_service(needed_service):
        t.user_message(uid, license_gate.refusal_text(license_state, needed_service))
        return

    ctx = {"uid": uid, "nickname": nickname, "username": username, "raw": raw_msg, "args": args, "cmd": cmd_name, "bot": bot_context.bot}

    def _run_command():
        try:
            entry["handler"](ctx)
        except Exception as e:
            logging_setup.log_exception()
            t.user_message(uid, i18n.t("command_error", error=logging_setup.safe_error_text(e)))

    threading.Thread(target=_run_command, daemon=True).start()

def on_file_transfer(event):
    p = event["params"]
    with bot.download_lock:
        if bot.download_state["active"] and p.get("transfer_id") == bot.download_state.get("transfer_id"):
            size = p.get("size") or 0
            transferred = p.get("transferred") or 0
            bot.download_state["percent"] = round(transferred * 100 / size, 1) if size else None
            bot.download_state["eta_seconds"] = None

def _reconnect_full(reason):
    """
    تلاش می‌کنه تا وصل واقعی بشه (نه فقط یه بار امتحان کنه). برای دو حالت
    استفاده می‌شه: قطعی واقعی اتصال (connection_lost/failed)، و کیک از کل
    سرور (nSource == 0 توی رویداد kicked -- یعنی دیگه هیچ کانالی نداریم که
    بخوایم بهش برگردیم، چون اصلاً روی سرور نیستیم).

    اولین تلاش با reconnect_wait.first_seconds صبر می‌کنه (پیش‌فرض 0 = فوری)،
    بقیه‌ی تلاش‌ها با reconnect_wait.repeat_seconds (قابل تغییر با دستور rw).
    اگه سرور صریحاً بگه بن شدیم/اکانت نامعتبره/اجازه نداریم (نه فقط timeout)،
    دیگه ادامه نمی‌ده -- چون دیگه هیچ‌وقت جواب نمی‌ده و فقط اسپم می‌شه.
    """
    if bot.reconnecting:
        return
    bot.reconnecting = True
    try:
        rw_cfg = cfg.get("reconnect_wait", {"first_seconds": 0, "repeat_seconds": 10})
        stop_player()
        attempt = 0
        while True:
            attempt += 1
            wait_seconds = rw_cfg.get("first_seconds", 0) if attempt == 1 else rw_cfg.get("repeat_seconds", 10)
            logging_setup.log_info(f"{reason} - reconnect attempt {attempt} in {wait_seconds}s...")
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            try:
                connect_bot()
                logging_setup.log_info("reconnected successfully.")
                break
            except TeamTalkCommandError as e:
                logging_setup.log_exception(f"reconnect attempt {attempt} got a permanent server error ({reason})")
                if e.error_code in _FATAL_RECONNECT_CODES:
                    print(f"[Connection] نمی‌تونم دوباره وصل بشم؛ سرور گفت: {e.error_message or e.error_code}. "
                          "دیگه امتحان نمی‌کنم (نیاز به بررسی دستی داره).")
                    break
            except Exception:
                logging_setup.log_exception(f"reconnect attempt {attempt} failed ({reason})")
    finally:
        bot.reconnecting = False

def on_user_logged_in(event):
    user = event["params"].get("user") or {}
    user_id = user.get("user_id")
    if user_id and user_id != t.my_id():
        try:
            _minimize_and_verify(user_id, user.get("username", ""))
        except Exception:
            logging_setup.log_exception(f"minimizing subscriptions for user {user_id}")

def on_kicked(event):
    """
    channel_id == 0 یعنی از کل سرور کیک شدیم (نه فقط یه کانال)؛ اتصال
    دیگه معتبر نیست، پس باید یه reconnect کامل (connect+login+join) انجام
    بشه، نه فقط یه join روی اتصال مرده. channel_id != 0 یعنی فقط از یه
    کانال کیک شدیم ولی هنوز روی سرور هستیم، پس صرفاً دوباره join می‌کنیم.
    """
    channel_id = event["params"].get("channel_id")
    if not channel_id:
        _reconnect_full("kicked from server")
        return
    home_id = cfg.get("channel", {}).get("id", 1)
    home_pw = cfg.get("channel", {}).get("password", "")
    if not _do_join(home_id, home_pw):
        _do_join(1, "")

def on_self_moved(event):
    """
    اگه خودمون (نه یه کاربر دیگه) وارد یه کانال جدید بشیم بدون این‌که خودمون
    درخواستش داده باشیم (نه connect اولیه، نه kicked-rejoin، نه come/back)،
    یعنی یه ادمین دیگه ما رو move کرده؛ این کانال جدید رو به‌عنوان کانال
    خونه‌ی جدید توی کانفیگ ذخیره می‌کنیم.
    """
    user = event["params"].get("user") or {}
    if user.get("user_id") != t.my_id():
        return
    if bot.self_initiated_join:
        return
    with bot.roam_lock:
        if bot.roam_state["active"]:
            return

    new_channel_id = event["params"].get("channel_id")
    if new_channel_id and new_channel_id != cfg.get("channel", {}).get("id"):
        cfg.setdefault("channel", {})["id"] = new_channel_id
        cfg["channel"]["password"] = ""
        save_config()

def on_disconnect(event):
    _reconnect_full(event["event"])

def _register_event_handlers():
    """ثبت هندلرهای رویداد تیم‌تاک (بعد از اتصال اول، مثل قبل)."""
    t.subscribe("user_msg")(on_user_msg)
    t.subscribe("file_transfer")(on_file_transfer)
    t.subscribe("user_logged_in")(on_user_logged_in)
    t.subscribe("kicked")(on_kicked)
    t.subscribe("user_join")(on_self_moved)
    t.subscribe("connection_failed")(on_disconnect)
    t.subscribe("connection_lost")(on_disconnect)

DOWNLOAD_DIR = None
DOWNLOAD_MAX_BYTES = 100 * 1024 * 1024
DOWNLOAD_AUDIO_FORMAT = "mp3"
DOWNLOAD_AUDIO_QUALITY = "192"
# فرمت‌هایی که FFmpegExtractAudio (postprocessor خودِ yt-dlp) پشتیبانی می‌کنه.
DOWNLOAD_ALLOWED_FORMATS = ("mp3", "m4a", "opus", "vorbis", "wav", "flac", "aac", "alac")
DOWNLOADS_SWEEP_INTERVAL_SECONDS = 15 * 60

def _sweep_downloads():
    """
    فایل‌های قدیمی پوشه‌ی downloads همین ربات رو بر اساس *تاریخ خود فایل*
    پاک می‌کنه.

    قبلاً این کار با یه threading.Timer به‌ازای هر دانلود انجام می‌شد که دو
    مشکل داشت: (۱) هر تایمر یه ترد خوابیده‌ی واقعی بود، (۲) با هر ری‌استارت
    ربات همه‌ی تایمرها از بین می‌رفتن و فایل‌های قبلی *برای همیشه* روی دیسک
    می‌موندن. جاروکش مبتنی بر تاریخ فایل هیچ‌کدوم از این دو مشکل رو نداره.
    """
    try:
        minutes = cfg.get("downloads_cleanup_minutes", 1440)
        with bot.download_lock:
            busy = bot.download_state["active"]
        # وقتی یه دانلود/آپلود در جریانه دست نمی‌زنیم، تا فایل نیمه‌کاره‌ی
        # همون لحظه قربانی نشه.
        if minutes and minutes > 0 and not busy and os.path.isdir(DOWNLOAD_DIR):
            cutoff = time.time() - minutes * 60
            for fname in os.listdir(DOWNLOAD_DIR):
                path = os.path.join(DOWNLOAD_DIR, fname)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except OSError:
                    pass
    except Exception:
        logging_setup.log_exception("sweeping the downloads folder")
    finally:
        scheduler.schedule(DOWNLOADS_SWEEP_INTERVAL_SECONDS, _sweep_downloads)

def _start_download_sweeper():
    global DOWNLOAD_DIR
    DOWNLOAD_DIR = os.path.join(_bot_dir, "downloads")
    _sweep_downloads()

# --- رشد صف ---
# رشد واقعی الان کار خودِ صفه (core/trackqueue.py + _grow_queue بالا): صف
# می‌دونه چند آیتم تا آخر مونده و خودش در پس‌زمینه آیتم بیشتر می‌گیره.
#
# این چهار تابع فقط برای سازگاری موندن، چون دستورهای موجود (و هر پلاگین
# کاربر) ممکنه صداشون بزنن. کاری که می‌کنن: به صف می‌گن «الان یه نگاه به
# رشد بنداز» -- همون چیزی که قبلاً با ده‌ها خط heuristic انجام می‌شد.
#
# نسخه‌ی قبلی هر stub رو خودش resolve می‌کرد و مستقیم توی پلی‌لیست mpv
# می‌ریخت؛ یعنی برای یه صف ۴۰تایی، ۴۰ استخراج قبل از این‌که کاربر چیزی
# بشنوه -- و لینک‌های یوتیوب چند ساعته منقضی می‌شن، پس بخش زیادیش هدر بود.

def _grow_search_playlist(service_name, query, target_count=None, skip_id=None):
    """سازگاری: صف خودش رشد می‌کنه. True یعنی رشدی در جریان هست."""
    bot.queue.prefetch_async()
    return bot.queue.is_growing()


def _grow_search_playlist_async(service_name=None, query=None, skip_id=None, target_count=None):
    """سازگاری با نسخه‌ی قبلی؛ رشد الان خودکار و پس‌زمینه‌ست."""
    bot.queue.prefetch_async()


def _grow_playlist_queue(service_name=None, url=None, target_count=20):
    bot.queue.prefetch_async()
    return bot.queue.is_growing()


def _grow_playlist_queue_async(service_name=None, url=None, target_count=20):
    bot.queue.prefetch_async()

def _active_service():
    srv_list = searchable_service_names(bot.services)
    if not srv_list:
        return None, None
    name = srv_list[bot.current_service_index]
    return name, bot.services[name]

def _require_channel_service(ctx):
    """
    برای دستورات کانال لازمه: ۱) یه سرویس فعال باشه، ۲) قبلاً با p چیزی
    سرچ شده باشه (تا کانال مشخص باشه)، ۳) سرویس فعال از قابلیت کانال
    پشتیبانی کنه. اگه هرکدوم نبود، پیام مناسب می‌ده و None برمی‌گردونه.
    """
    name, service = _active_service()
    if not service:
        t.user_message(ctx["uid"], command_helpers.no_services_message(bot))
        return None, None
    if not bot.last_channel_url:
        t.user_message(ctx["uid"], i18n.t("need_search_first"))
        return None, None
    if not hasattr(service, "get_channel_videos"):
        t.user_message(ctx["uid"], i18n.t("channel_not_supported", service=name))
        return None, None
    return name, service

def _load_channel_playlist_by_index(uid, nickname, service, playlists, index):
    """
    playlist شماره‌ی index (۱-پایه) رو از لیست پلی‌لیست‌های کانال لود و پخش
    می‌کنه؛ در موفقیت ایندکس فعلی رو برای nn/bb ذخیره می‌کنه.
    """
    if index < 1 or index > len(playlists):
        t.user_message(uid, i18n.t("invalid_playlist_number"))
        return False

    target = playlists[index - 1]
    _channel_broadcast(i18n.t("loading_playlist", nickname=nickname, title=target["title"]))
    try:
        result = service.search(target["url"])
        load_and_play(result, private=False)
        bot.channel_playlist_index = index
        # همون خطِ جمع‌وجورِ مشترک (E12) به‌جای پیامِ جدایی که فقط تعداد رو می‌گفت.
        command_helpers.broadcast_now_playing(bot)
        return True
    except Exception as e:
        command_helpers.notify(bot, {"uid": uid, "nickname": nickname}, "generic_error",
                               error=logging_setup.safe_error_text(e))
        return False

import shutil
# پیدا کردن ffmpeg از core.platform_paths می‌آد تا روی ویندوز و لینوکس یه
# قاعده‌ی واحد داشته باشیم: اول نسخه‌ی همراه پروژه (bin/ffmpeg یا
# bin/ffmpeg.exe)، بعد نسخه‌ی نصب‌شده‌ی سیستم. روی لینوکس بیت اجرا هم
# همون‌جا درست می‌شه، وگرنه یه فایل کپی‌شده از ریپو با Permission denied
# رد می‌شد.
_FFMPEG_LOCAL_DIR = os.path.join(BASE_DIR, "bin")
_FFMPEG_LOCATION = None
_FFMPEG_AVAILABLE = False

def _detect_ffmpeg():
    global _FFMPEG_LOCATION, _FFMPEG_AVAILABLE
    _FFMPEG_LOCATION = platform_paths.ffmpeg_location()
    _FFMPEG_AVAILABLE = platform_paths.has_ffmpeg()
    if not _FFMPEG_AVAILABLE:
        print(f"[Startup] ffmpeg پیدا نشد (نه توی PATH، نه توی {_FFMPEG_LOCAL_DIR})؛ "
              "دستور dl فایل رو بدون تبدیل به mp3 (همون فرمت خام صوتی) آپلود می‌کنه.")

def _download_cache_key(url, audio_format, audio_quality):
    """
    کلید کش شامل فرمت/کیفیته، نه فقط لینک -- وگرنه اگه یه بار mp3/192
    دانلود بشه، درخواست بعدیِ همون لینک با flac یا 320 اشتباهی همون فایل
    قدیمی رو برمی‌گردوند.
    """
    import hashlib
    return hashlib.sha1(f"{url}|{audio_format}|{audio_quality}".encode("utf-8")).hexdigest()[:16]

def find_cached_download(url, audio_format=None, audio_quality=None):
    """
    اگه این لینک با همین فرمت/کیفیت قبلاً توی پوشه‌ی downloads همین ربات
    دانلود شده و هنوز اونجاست، مسیرش رو برمی‌گردونه (بدون دانلود دوباره).
    وگرنه None.
    """
    key = _download_cache_key(url, audio_format or DOWNLOAD_AUDIO_FORMAT, audio_quality or DOWNLOAD_AUDIO_QUALITY)
    if not os.path.isdir(DOWNLOAD_DIR):
        return None
    for fname in os.listdir(DOWNLOAD_DIR):
        if fname.startswith(key + "__"):
            path = os.path.join(DOWNLOAD_DIR, fname)
            if os.path.isfile(path):
                return path
    return None

def _download_track(url, audio_format=None, audio_quality=None):
    """
    فقط صدا دانلود می‌کنه (بدون تصویر). اگه ffmpeg نصب باشه، فایل واسط
    (معمولاً webm/opus) به فرمت درخواستی (پیش‌فرض mp3/192) تبدیل می‌شه.
    اگه ffmpeg نبود یا خودِ تبدیل به هر دلیلی خطا داد، بدون این‌که کل
    دانلود fail بشه، همون فایل خام صوتی (بدون تبدیل) برگردونده می‌شه --
    بهتره یه فایل با فرمت متفاوت آپلود بشه تا اصلاً هیچی آپلود نشه.
    """
    audio_format = audio_format or DOWNLOAD_AUDIO_FORMAT
    audio_quality = audio_quality or DOWNLOAD_AUDIO_QUALITY

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    from yt_dlp import YoutubeDL

    def _on_download_progress(d):
        if d.get("status") != "downloading":
            return
        with bot.download_lock:
            if not bot.download_state["active"]:
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            bot.download_state["percent"] = round(downloaded * 100 / total, 1) if total else None
            bot.download_state["eta_seconds"] = d.get("eta")

    cache_prefix = _download_cache_key(url, audio_format, audio_quality) + "__"

    def _opts(use_ffmpeg):
        o = {
            "quiet": True,
            "no_warnings": False,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(DOWNLOAD_DIR, cache_prefix + "%(title).90s.%(ext)s"),
            "noplaylist": True,
            "max_filesize": DOWNLOAD_MAX_BYTES,
            "logger": logging_setup.get_ytdlp_logger(),
            "progress_hooks": [_on_download_progress],
        }
        if use_ffmpeg:
            o["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": audio_quality,
            }]
            if _FFMPEG_LOCATION:
                o["ffmpeg_location"] = _FFMPEG_LOCATION
        proxy_url = proxy_state.get_proxy_url()
        if proxy_url:
            o["proxy"] = proxy_url
        return o

    use_ffmpeg = _FFMPEG_AVAILABLE
    try:
        with YoutubeDL(_opts(use_ffmpeg)) as ydl:
            info = ydl.extract_info(url, download=True)
            raw_path = ydl.prepare_filename(info)
    except Exception:
        if not use_ffmpeg:
            raise
        logging_setup.log_exception(f"download with ffmpeg conversion failed for '{url}', retrying without conversion")
        with YoutubeDL(_opts(False)) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)

    if not use_ffmpeg:
        return raw_path

    final_path = os.path.splitext(raw_path)[0] + f".{audio_format}"
    return final_path if os.path.exists(final_path) else raw_path

def _attach_bot_api():
    """API داخلیِ ربات رو روی bot می‌ذاره تا دستورهای core/commands ازش استفاده کنن."""
    bot.load_and_play = load_and_play
    bot.channel_broadcast = _channel_broadcast
    bot.full_shutdown = full_shutdown
    bot.apply_proxy_to_player = _apply_proxy_to_player
    bot.apply_normalize = _apply_normalize
    bot.save_config = save_config
    bot.save_aliases = save_aliases
    bot.is_admin = is_admin
    bot.user_role = lambda uid, username: roles.user_role(bot, uid, username)
    bot.has_role = lambda uid, username, required_role: roles.has_role(bot, uid, username, required_role)
    bot.format_time = format_time
    bot.send_long_text = _send_long_text
    bot.do_join = _do_join
    bot.return_home = _return_home
    bot.find_cached_download = find_cached_download
    bot.dl_auto_remove_minutes_effective = dl_auto_remove_minutes_effective
    bot.stop_player = stop_player
    bot.active_service = _active_service
    bot.require_channel_service = _require_channel_service
    bot.load_channel_playlist_by_index = _load_channel_playlist_by_index
    bot.grow_search_playlist = _grow_search_playlist
    bot.grow_search_playlist_async = _grow_search_playlist_async
    bot.grow_playlist_queue_async = _grow_playlist_queue_async
    bot.roam_set_deadline = _roam_set_deadline
    bot.data_dir = DATA_DIR
    bot.resolve_mode = _resolve_mode
    bot.download_track = _download_track
    bot.download_dir = DOWNLOAD_DIR
    bot.download_allowed_formats = DOWNLOAD_ALLOWED_FORMATS
    bot.download_default_format = DOWNLOAD_AUDIO_FORMAT
    bot.download_default_quality = DOWNLOAD_AUDIO_QUALITY
    bot.commands = COMMANDS
    bot.reloaders = RELOADERS
    bot.start_time = time.time()

# --- تست سلامت راه‌اندازی ---
# بیشتر خرابی‌های این ربات ساکتن: بالا میاد، توی کانال دیده می‌شه، ولی صدا
# هیچ‌جا نمی‌ره (لاین صدا بعد از ریبوت رفته، شماره‌ی دستگاه عوض شده، ...).
# اینجا همون چیزهایی که واقعاً استفاده می‌شن امتحان می‌شن -- روی همین
# player و t زنده، نه یه نمونه‌ی تازه -- تا اگه خراب بود همین لحظه معلوم
# بشه. هیچ‌وقت جلوی اجرا رو نمی‌گیره؛ فقط گزارش می‌ده.
def _run_startup_selftest():
    _selftest_cfg = cfg.get("selftest", {}) if isinstance(cfg.get("selftest"), dict) else {}
    if _selftest_cfg.get("enabled", True):
        try:
            bot.selftest_report = selftest.run(
                bot=bot,
                player=player,
                tt=t,
                play_tone=_selftest_cfg.get("audio_tone", True),
                include_slow=_selftest_cfg.get("include_slow", True),
            )
            selftest.print_report(
                bot.selftest_report,
                only_problems=_selftest_cfg.get("quiet", False),
            )
            for _problem in bot.selftest_report.failures:
                logging_setup.log_warning(_problem.line(), context="startup selftest")
        except Exception:
            logging_setup.log_exception("startup selftest")
    else:
        bot.selftest_report = None

MAIN_LOOP_WAIT_MS = 250        # چقدر منتظر رویداد بمونیم
HOUSEKEEPING_INTERVAL = 0.5    # هر چند ثانیه وضعیت پلیر/میکروفون بررسی بشه
IDLE_CHECK_INTERVAL = 2.0      # هر چند ثانیه خالی بودن کانال بررسی بشه
SHARED_CONFIG_CHECK_INTERVAL = 5.0
JOIN_SETTLE_SECONDS = 3

def _handle_track_finished():
    """
    توی یه تردِ پس‌زمینه‌ی جدا صدا زده می‌شه (نه ترد حلقه‌ی اصلی)، چون
    on_track_finished حالا از play_fn (بالا: _play_and_confirm) می‌خواد
    مطمئن بشه mpv واقعاً باز کرده -- این تأیید می‌تونه چند ثانیه (لایوِ
    کند) طول بکشه. اگه این‌جا مستقیم توی حلقه‌ی اصلی صدا زده می‌شد، ترد
    اصلی همون چند ثانیه هیچ پیامی از هیچ کاربری رو پردازش نمی‌کرد.
    """
    try:
        advanced, next_track = bot.queue.on_track_finished()
    except Exception:
        logging_setup.log_exception("advancing to the next track")
        advanced, next_track = False, None
    if advanced and next_track is not None:
        bot.track_meta = bot.queue.meta()
        # last_track_info رو همین‌جا (سریع) ست می‌کنیم تا fallbackِ
        # «now_playing»ی حلقه‌ی اصلی با پیامِ کاملی که broadcast_now_playing
        # می‌فرسته قاطی نشه (اون منتظرِ duration هم می‌مونه -- E12).
        bot.last_track_info = command_helpers.current_display_title(bot)
        command_helpers.broadcast_now_playing(bot)
    elif not bot.queue.is_growing():
        # واقعاً ته صفه و چیزی هم در راه نیست.
        bot.queue.mark_stopped()


def _main_loop():
    """حلقه‌ی اصلی: رویدادهای SDK + کارهای دوره‌ای. هیچ‌وقت برنمی‌گرده."""
    pending_title = ""
    # چند ثانیه به mpv مهلت می‌دیم عنوان فایل رو بخونه، قبل از این‌که به
    # لینک خام به‌عنوان «عنوان» رضایت بدیم. جزئیات کنار محل استفاده.
    TITLE_WAIT_SECONDS = 6.0
    title_wait_file = None
    title_wait_until = 0.0
    _last_shared_config_check = 0.0
    _last_housekeeping = 0.0
    _last_idle_check = 0.0
    # چند دور پشت‌سرهم mpv بیکار دیده شده. یه دور کافی نیست: mpv بین دو آیتم
    # لحظه‌ای بیکار به‌نظر می‌رسه و یه پرش زودهنگام، آهنگ بعدی رو نصفه می‌کرد.
    _idle_ticks = 0

    # --- ریتم حلقه‌ی اصلی ---------------------------------------------------
    # قبلاً حلقه با handle_messages(50ms) + sleep(0.1) کار می‌کرد، یعنی حدود ۷
    # دور در ثانیه، و *هر دور* چند property از mpv (هر کدوم یه IPC از طریق
    # ctypes) و یه get_channel_users کامل از SDK خونده می‌شد. این تنها دلیل
    # مصرف CPU ربات در حالت بیکاری بود.
    #
    # حالا:
    #   - تنها نقطه‌ی انتظار، خودِ handle_messages است که روی صف رویداد SDK
    #     بلاک می‌شه. یعنی وقتی پیامی هست *فوراً* بیدار می‌شیم (تأخیر کمتر از
    #     قبل)، و وقتی نیست عملاً هیچ CPU ای مصرف نمی‌شه.
    #   - کارهای دوره‌ای (وضعیت پخش، میکروفون، کانال خالی) با فاصله‌ی مشخص
    #     انجام می‌شن، نه هر دور.
    t.mic_open = False

    while True:
        t.handle_messages(MAIN_LOOP_WAIT_MS)

        now = time.time()
        if now - _last_housekeeping < HOUSEKEEPING_INTERVAL:
            continue
        _last_housekeeping = now

        if now - _last_shared_config_check > SHARED_CONFIG_CHECK_INTERVAL:
            _last_shared_config_check = now
            reload_shared_config_if_changed()

        # وضعیت پلیر فقط یک‌بار در هر دور خونده می‌شه (قبلاً بعضی‌هاش دو بار
        # هم خونده می‌شد) و بین همه‌ی بخش‌های پایین به اشتراک گذاشته می‌شه.
        current_file = player.current_url
        is_paused = player.is_paused

        # زیرنویس زنده (core/subtitles.py): تا وقتی کسی `sub` رو روشن نکرده
        # همین یه خط برمی‌گرده و هیچ هزینه‌ای نداره.
        subtitles.safe_tick(bot, current_file, is_paused)

        # --- پایان طبیعی آهنگ -> آیتم بعدی ---
        # قبلاً این کار خودکار توسط پلی‌لیست داخلی mpv انجام می‌شد. الان mpv هر
        # لحظه فقط یک آیتم داره، پس پیشروی کار ماست (توضیح کامل توی
        # core/trackqueue.py).
        #
        # mark_stopped توی stop_player تضمین می‌کنه توقف *عمدی* (s، کانال خالی،
        # پخش جدید) با «آهنگ تموم شد» قاطی نشه.
        if current_file is None and bot.queue.active:
            _idle_ticks += 1
            if _idle_ticks >= 2:
                _idle_ticks = 0
                # پس‌زمینه: تأییدِ پخش (_play_and_confirm) می‌تونه چند ثانیه
                # طول بکشه و نباید حلقه‌ی اصلی (پیامِ بقیه‌ی کاربرها) رو
                # بلاک کنه. queue._nav_lock خودش جلوی هم‌پوشانیِ چند تلاشِ
                # هم‌زمان رو می‌گیره (n دستی هم از همین قفل استفاده می‌کنه).
                threading.Thread(target=_handle_track_finished, daemon=True).start()
        else:
            _idle_ticks = 0

        idle_cfg = cfg.get("idle_channel", {})
        if (
            idle_cfg.get("enabled", True)
            and current_file is not None
            and (now - bot.last_join_time) > JOIN_SETTLE_SECONDS
            and (now - _last_idle_check) >= IDLE_CHECK_INTERVAL
        ):
            # آستانه‌های این بخش برحسب ده‌ها ثانیه‌ان (پیش‌فرض ۶۰ و ۳۰۰)، پس
            # چک کردنش هر ۲ ثانیه دقیقاً همون نتیجه رو می‌ده ولی به‌جای ~۷ بار
            # در ثانیه، نصفِ یک بار در ثانیه لیست کاربرهای کانال رو از SDK
            # می‌گیره.
            _last_idle_check = now
            try:
                others = t.get_channel_users(exclude_self=True)
            except Exception:
                logging_setup.log_debug("idle-channel: get_channel_users failed, skipping this check")
                others = None
            if others is not None:
                player_state_changed = False
                if not others:
                    if bot.empty_channel_since is None:
                        bot.empty_channel_since = now
                    elapsed = now - bot.empty_channel_since
                    pause_after = idle_cfg.get("pause_after_seconds", 0)
                    stop_after = idle_cfg.get("stop_after_seconds", 300)
                    if elapsed >= stop_after:
                        stop_player()
                        bot.auto_paused_for_empty = False
                        bot.empty_channel_since = None
                        player_state_changed = True
                    elif elapsed >= pause_after and not is_paused:
                        player.pause()
                        bot.auto_paused_for_empty = True
                        player_state_changed = True
                else:
                    if bot.auto_paused_for_empty:
                        # کاربر تنها ممکنه واقعاً رفته باشه یا فقط اینترنتش قطع
                        # شده باشه (سرور تا nUserTimeout صبر می‌کنه قبل از
                        # حذف واقعیش از کانال -- server_properties()['user_timeout']).
                        # برای هر دو حالت، چند ثانیه عقب‌تر از سر می‌گیریم تا
                        # چیزی که حین قطعی/غیبت از دست رفته رو از دست ندن.
                        rewind = idle_cfg.get("resume_rewind_seconds", 4)
                        if rewind > 0:
                            try:
                                player.seek_relative(-rewind)
                            except Exception:
                                logging_setup.log_debug("idle-channel: resume rewind seek failed")
                        player.resume()
                        bot.auto_paused_for_empty = False
                        player_state_changed = True
                    bot.empty_channel_since = None

                # فقط وقتی واقعاً چیزی عوض کردیم دوباره از mpv می‌پرسیم.
                if player_state_changed:
                    current_file = player.current_url
                    is_paused = player.is_paused

        if current_file is not None:
            pos = bot.queue.index
            current_meta = None
            if pos is not None and 0 <= pos < len(bot.track_meta):
                current_meta = bot.track_meta[pos]
            # عنوان «واقعی» یعنی چیزی که از سرویس یا از خود mpv اومده -- ولی
            # هیچ‌وقت لینک خامِ یه ترک خصوصی: media-title خودِ mpv بدون
            # متادیتا به آدرس برمی‌گرده، و این هم روی استاتوس می‌نشست هم توی
            # کانال پخش می‌شد.
            real_title = command_helpers.display_title(
                {k: v for k, v in (current_meta or {}).items() if k != "fallback_label"},
                player.now_playing_title)
            if real_title == i18n.t("private_track_label"):
                real_title = None   # هنوز منتظر عنوان واقعی بمون
            fallback_label = command_helpers.display_title(current_meta)

            # mpv متادیتا رو غیرهمزمان می‌خونه، پس چند تیکِ اول معمولاً هنوز
            # عنوان ندارن. قبلاً همون لحظه fallback (لینک خام) هم روی استاتوس
            # می‌نشست و هم توی چت broadcast می‌شد، و چند ثانیه بعد با عنوان
            # واقعی عوض می‌شد: برای کاربر عادی یه پیام بی‌معنی و یه استاتوس
            # که خودبه‌خود تغییر می‌کرد.
            #
            # پس تا سقف مهلت صبر می‌کنیم. بعد از مهلت، fallback رو قبول
            # می‌کنیم تا برای فایل‌هایی که واقعاً عنوان ندارن بی‌صدا نمونیم.
            if current_file != title_wait_file:
                title_wait_file = current_file
                title_wait_until = now + TITLE_WAIT_SECONDS

            if real_title:
                pending_title = real_title
            elif now < title_wait_until:
                pending_title = None          # هنوز منتظریم؛ این تیک رو رد کن
            else:
                pending_title = fallback_label or "..."

            if pending_title is not None:
                status_text = i18n.t("status_paused" if is_paused else "status_playing",
                                     title=pending_title)

                # وقتی یه جابه‌جایی (دستی یا خودکار) در جریانه، مسئولِ خودش
                # (n/b یا _handle_track_finished) به‌محضِ تمام‌شدن
                # broadcast_now_playing رو صدا می‌زنه. اگه این‌جا هم زودتر
                # پیامِ کوتاه بفرستیم، برای یه آهنگ دو پیامِ Now playing
                # پشتِ‌سرهم می‌رفت (کوتاه، بعد کامل) -- باگی که کاربر گزارش
                # داد. پس تا وقتی navigation در جریانه، last_track_info رو
                # هم دست‌نمی‌زنیم تا بعداً همین مقایسه درست کار کنه.
                if pending_title != bot.last_track_info and not bot.queue.is_navigating:
                    _channel_broadcast(i18n.t("now_playing", title=pending_title))
                    bot.last_track_info = pending_title

                status_line.apply(t, cfg, status_text, paused=is_paused,
                                  visible=bot.status_visible)
        else:
            status_text = cfg.get("status", {}).get("idle_text", "Idle")
            bot.last_track_info = ""
            pending_title = ""
            # صف فقط وقتی پاک می‌شه که واقعاً چیزی نمونده باشه؛ وگرنه یه وقفه‌ی
            # کوتاه بین دو آهنگ، کل صف رو از دید دستورها (q/i/dl) پاک می‌کرد.
            if not bot.queue.active and bot.queue.length == 0:
                bot.track_meta = []
            _roam_set_deadline()

            status_line.apply(t, cfg, status_text, visible=bot.status_visible)

        with bot.roam_lock:
            roam_deadline = bot.roam_state["deadline"] if bot.roam_state["active"] else None
        if roam_deadline is not None and now > roam_deadline:
            _return_home()

        # is_buffering فقط وقتی پرسیده می‌شه که اصلاً چیزی برای پخش هست --
        # وگرنه جوابش از پیش معلومه و یه IPC بی‌خودی با libmpv بود.
        should_mic_on = current_file is not None and not is_paused and not player.is_buffering
        if should_mic_on != t.mic_open:
            try:
                t.set_microphone(should_mic_on)
            except Exception:
                logging_setup.log_exception()


def _configure_process():
    """
    روی ویندوز وقتی خروجی به فایل/پایپ هدایت می‌شه (اجرا به‌عنوان سرویس، یا
    `python bot.py > log.txt`)، پایتون به‌جای کنسول یونیکد از کدپیج سیستم
    استفاده می‌کنه -- که مثلاً cp1256 است و حرف فارسی رو نمی‌تونه encode کنه.
    نتیجه: همون اولین print فارسی (پیام‌های استارت/ویزارد) کل ربات رو با
    UnicodeEncodeError می‌کشه. این چند خط جلوش رو می‌گیره.
    """
    force_utf8_console()


def _load_native_modules():
    """ایمپورت TeamTalk/mpv (لود کتابخانه‌ی نیتیو) -- قبلاً بالای فایل بود."""
    global TTBot, TeamTalkCommandError, ClientError, Player, _FATAL_RECONNECT_CODES
    from core.teamtalk.ttbot import TTBot, TeamTalkCommandError
    from core.teamtalk.TeamTalk5 import ClientError
    from core.mpv.player import Player
    _FATAL_RECONNECT_CODES = {
        ClientError.CMDERR_INVALID_USERNAME,
        ClientError.CMDERR_INVALID_ACCOUNT,
        ClientError.CMDERR_SERVER_BANNED,
        ClientError.CMDERR_NOT_AUTHORIZED,
    }


def main():
    """
    راه‌اندازی صریح و به‌ترتیبِ ربات (قبلاً همه‌ی این‌ها به ترتیب خطوطِ فایل
    موقع import اجرا می‌شد). ترتیب دقیقاً همونه؛ عوضش نکن:
    کانفیگ -> شیءهای اصلی -> لایسنس -> صف/پروکسی/صدا -> اتصال اول ->
    هندلرها -> جاروکش دانلود -> API روی bot -> تست سلامت -> حلقه.
    """
    _configure_process()
    _load_native_modules()
    os.makedirs(DATA_DIR, exist_ok=True)
    _select_bot()
    _init_config_and_dirs()
    _init_cookies()
    _create_core_objects()
    _license_gate_and_bind()
    _init_queue()
    _apply_proxy_to_player()
    _init_audio_and_volume()
    _init_playback_state()
    _init_roam_state()
    _init_search_state()
    _apply_normalize()
    _init_join_state()
    _initial_connect()
    _init_aliases()
    _create_command_manager()
    _register_event_handlers()
    _start_download_sweeper()
    _detect_ffmpeg()
    _attach_bot_api()
    _reload_commands()
    # جستجوی صوتی (roadmap C3): رویدادهای صدا/وضعیت/قطع‌اتصالِ لازم رو subscribe
    # می‌کنه؛ منطق کامل توی core/voice_search.py، این فقط یه‌بار وصلش می‌کنه.
    voice_search.install(bot)
    # زیرنویس (sub): خروج از سرور/قطع اتصال وضعیتِ کاربرها رو پاک می‌کنه؛
    # پخشِ زمان‌بندی‌شده (sch): برنامه‌های ذخیره‌شده‌ی این ربات رو دوباره تنظیم می‌کنه.
    subtitles.install(bot)
    scheduled_play.install(bot)
    _run_startup_selftest()
    print("Bot is running and waiting for messages...")
    _main_loop()


if __name__ == "__main__":
    main()
