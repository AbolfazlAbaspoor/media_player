"""
پیدا کردن باینری‌ها و کتابخانه‌های نیتیو (TeamTalk SDK، libmpv، ffmpeg، و
ابزارهای کمکیِ دانلودی مثل deno/xray) روی هر سیستم‌عاملی، با یه قاعده‌ی
واحد -- چهار حالت استقرار ممکنه، به ترتیب اولویت:

    ۱. کپیِ دستیِ کاربر کنار فایل اجرایی -- تا مشتری بتونه بدون بیلد
       مجدد یه DLL/so جدیدتر جایگزین کنه. همیشه برنده‌ست.
    ۲. اجرای مستقیم از سورس -- کنار خود پوشه‌ها (core/teamtalk/, core/mpv/, bin/).
    ۳. بیلدِ onedir با PyInstaller 6+ -- فایل‌های --add-binary زیر
       پوشه‌ی _internal/ در می‌آن، نه کنار خود فایل اجرایی.
    ۴. بیلدِ onefile -- فایل‌ها توی پوشه‌ی موقتِ sys._MEIPASS باز می‌شن.

## چرا این فایل اصلاً لازمه

هم TeamTalk5.py و هم mpv.py کتابخانه‌ی نیتیوشون رو *لحظه‌ی import* لود
می‌کنن. یعنی هر تنظیمی (اضافه‌کردن مسیر DLL روی ویندوز، یا پیدا کردن
مسیر مطلق .so روی لینوکس) باید *قبل* از اون import انجام شده باشه --
برای همین core/teamtalk/__init__.py و core/mpv/__init__.py اولین کاری که می‌کنن
صدا زدن همین ماژوله.

## E16: چرا نسخه‌ی قبلی توی بیلدِ کامپایل‌شده اشتباه می‌کرد

این فایل مسیرها رو با core.paths.get_base_dir() می‌ساخت -- یعنی پوشه‌ی
خودِ فایل اجرایی. برای بیلدِ onedir این غلطه: PyInstaller 6 فایل‌های
--add-binary رو زیر _internal/ می‌ذاره، نه کنار .exe. یعنی مثلاً
teamtalk_library_path() دنبال «<پوشه‌ی exe>/teamtalk/TeamTalk5.dll»
می‌گشت درحالی‌که فایل واقعی «<پوشه‌ی exe>/_internal/teamtalk/TeamTalk5.dll»
بود -- پیدا نمی‌شد، و launcher هشدار «libmpv پیدا نشد» می‌داد و
ffmpeg_location() هم ffmpeg باندل‌شده رو برای yt-dlp گم می‌کرد، با اینکه
هر دو واقعاً توی بسته بودن.

راه‌حل: NATIVE_COMPONENTS و find_native_component() پایین‌تر -- تنها
جایی که این تصمیم گرفته می‌شه، هم کنار فایل اجرایی (get_base_dir) رو
چک می‌کنه هم داخل باندل (core.paths.bundle_dir؛ در onedir جدید همون
_internal/ از طریق sys._MEIPASS، در onefile پوشه‌ی موقتِ استخراج). در
اجرای مستقیم از سورس این دو یکی‌ان، پس رفتار قبلی دست‌نخورده می‌مونه.
"""

import os
import platform
import shutil
import stat
import sys

from core.paths import bundle_dir, get_base_dir


def system_name():
    """"windows" / "linux" / "macos" / یا هر چیز دیگه‌ای با حروف کوچک."""
    name = platform.system().lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return name or "unknown"


IS_WINDOWS = system_name() == "windows"
IS_LINUX = system_name() == "linux"
IS_MACOS = system_name() == "macos"


def _project_dir(*parts):
    return os.path.join(get_base_dir(), *parts)


def _ensure_executable(path):
    """
    روی لینوکس یه فایل که از یه زیپ/ریپو کپی شده ممکنه بیت اجرا نداشته
    باشه؛ به‌جای اینکه بعداً با Permission denied بمیریم، همین‌جا درستش
    می‌کنیم. روی ویندوز بی‌اثره.
    """
    if IS_WINDOWS or not path or not os.path.isfile(path):
        return path
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except Exception:
        pass
    return path


# --------------------------------------------- ثبتِ فایل‌های نیتیو (E16)

def _os_key():
    """
    مثل system_name()، ولی هر بار مستقیم از sys.platform محاسبه می‌شه --
    نه یه ثابتِ سطح ماژول مثل IS_WINDOWS. تنها دلیلش تست‌پذیریه: تست‌ها
    می‌تونن با patch کردن sys.platform رفتار هر سه سیستم‌عامل رو شبیه‌سازی
    کنن، بدون نیاز به ری‌لود کردن ماژول. برای هر تصمیم دیگه‌ای همون
    system_name()/IS_WINDOWS/IS_LINUX/IS_MACOS استفاده کن.
    """
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


#: تنها منبعِ «فلان فایل نیتیو کجاست»: زیرپوشه‌ش کنار پروژه، و اسم‌های
#: ممکنش روی هر سیستم‌عامل. build/build.py، build/package_rental.py،
#: پیدا کردنِ زمان اجرا (پایین‌تر)، و لودرهای core/teamtalk/TeamTalk5.py و
#: core/mpv/mpv.py همه از همین یه دیکشنری می‌خونن -- عوض‌کردن یه اسم فایل یا
#: جابه‌جاییِ یه پوشه فقط همین‌جا لازمه، نه توی پنج جای مختلف.
#:
#: "deno" و "xray" رو هنوز خودِ ربات لود نمی‌کنه -- install.py (E9)
#: دانلودشون می‌کنه و کنار ffmpeg توی bin/ می‌ذاره. ثبتشون این‌جا فقط
#: برای اینه که مقصدِ نصب (E9) و جستجوی زمان اجرا (js_runtime پایین‌تر،
#: و فیچر V2Ray آینده) از یه منبع واحد بخونن، نه یه لیست مسیرِ جدا.
NATIVE_COMPONENTS = {
    "teamtalk": {
        "subdir": "core/teamtalk",
        "names": {
            "windows": ("TeamTalk5.dll",),
            "linux": ("libTeamTalk5.so",),
            "macos": ("libTeamTalk5.dylib",),
        },
    },
    "mpv": {
        "subdir": "core/mpv",
        "names": {
            "windows": ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll"),
            # نکته‌ی مهم لینوکس: خیلی از توزیع‌ها فقط libmpv.so.2 دارن و
            # libmpv.so (سیم‌لینک بدون نسخه) فقط توی پکیج -dev هست. پس
            # نباید فقط روی ctypes.util.find_library('mpv') حساب کرد.
            "linux": ("libmpv.so.2", "libmpv.so.1", "libmpv.so"),
            "macos": ("libmpv.2.dylib", "libmpv.dylib"),
        },
    },
    "ffmpeg": {
        "subdir": "bin",
        "names": {
            "windows": ("ffmpeg.exe",),
            "linux": ("ffmpeg",),
            "macos": ("ffmpeg",),
        },
    },
    "deno": {
        "subdir": "bin",
        "names": {
            "windows": ("deno.exe",),
            "linux": ("deno",),
            "macos": ("deno",),
        },
    },
    "xray": {
        "subdir": "bin",
        "names": {
            "windows": ("xray.exe",),
            "linux": ("xray",),
            "macos": ("xray",),
        },
    },
    # موتور OCR برای بررسی خودکار رسید (licensing/receipts.py، اختیاری --
    # اگه نباشه بررسی رسید غیرفعال می‌مونه، نه اینکه ربات بالا نیاد).
    # روی ویندوز یه نصبِ کامل (نه فقط یه فایل تکی) توی زیرپوشه‌ی خودش
    # می‌شینه، برخلاف ffmpeg/mpv که یه باینریِ پرتابل کنار bin/ کپی می‌شن.
    "tesseract": {
        "subdir": "tesseract",
        "names": {
            "windows": ("tesseract.exe",),
            "linux": ("tesseract",),
            "macos": ("tesseract",),
        },
    },
}


def native_component_subdir(component):
    """پوشه‌ی کنار پروژه‌ای که فایل‌های component توش می‌شینن (مثلاً "mpv")."""
    return os.path.normpath(NATIVE_COMPONENTS[component]["subdir"])


def native_component_names(component, os_key=None):
    """اسم‌های ممکنِ component روی یه سیستم‌عامل (پیش‌فرض: همین سیستم)."""
    names = NATIVE_COMPONENTS[component]["names"]
    return names.get(os_key or _os_key(), names["linux"])


def native_component_all_names(component):
    """
    اسم‌های ممکنِ component روی *هر* سیستم‌عاملی که پشتیبانی می‌شه، بدون
    تکرار -- برای build.py که با یه اسکریپت هم روی ویندوز هم لینوکس
    بیلد می‌کنه و باید هر فایلی که ممکنه کنار پروژه باشه رو با isfile
    چک کنه، نه فقط اسمِ سیستم‌عامل فعلی.
    """
    seen = []
    for names in NATIVE_COMPONENTS[component]["names"].values():
        for name in names:
            if name not in seen:
                seen.append(name)
    return tuple(seen)


def _native_search_dirs(subdir):
    """
    پوشه‌های نامزد برای فایل‌های نیتیو، به ترتیب اولویت:

      ۱. get_base_dir() -- کنار فایل اجرایی (بیلدشده) یا ریشه‌ی پروژه
         (اجرای مستقیم از سورس). کپی‌ای که کاربر همین‌جا بذاره همیشه
         برنده‌ست -- دقیقاً همون چیزی که مشتری برای جایگزینیِ یه DLL
         جدیدتر بدون بیلد مجدد لازم داره.
      ۲. bundle_dir() -- داخل باندل PyInstaller: در onedir (نسخه‌ی ۶
         به‌بعد) پوشه‌ی _internal/ از طریق sys._MEIPASS، در onefile پوشه‌ی
         موقتِ استخراج (هم از طریق sys._MEIPASS).

    در اجرای مستقیم از سورس این دو تا یکی‌ان، پس فقط یه‌بار چک می‌شه.
    این دقیقاً همون قاعده‌ی core.paths.resource_dir() است؛ فرقش اینه که
    فایل‌های نیتیو چند اسمِ ممکن دارن (پایین‌تر) و نبودشون باید None
    برگردونه، نه یه مسیر پیش‌فرض برای ساختن.
    """
    external = os.path.join(get_base_dir(), subdir)
    bundled = os.path.join(bundle_dir(), subdir)
    if bundled == external:
        return (external,)
    return (external, bundled)


def find_native_component(component):
    """
    مسیر مطلق فایل نیتیوِ component (یکی از کلیدهای NATIVE_COMPONENTS)
    اگه همراه پروژه یا کنار فایل اجرایی باشه؛ وگرنه None.

    تنها تابعی که این تصمیم رو می‌گیره: چک‌های missing_runtime_
    requirements/describe_runtime، ffmpeg_location/ffmpeg_binary،
    teamtalk_library_path، mpv_library_path، js_runtime، لودرهای خودِ
    core/teamtalk/TeamTalk5.py و core/mpv/mpv.py، هشدار launcher، و مقصدهای
    build/build.py و build/package_rental.py همه از همین (یا از
    NATIVE_COMPONENTS بالا) می‌خونن -- هیچ‌کدوم دوباره لیست مسیر نمی‌سازه.

    چهار حالت استقرار پوشش داده می‌شه (بالای فایل توضیح داده شده). اسمِ
    فایل بر اساس سیستم‌عاملِ واقعیِ لحظه‌ی صدازدن انتخاب می‌شه (_os_key)،
    نه یه ثابتِ سطح ماژول -- برای تست‌پذیری با patch کردن sys.platform.
    """
    names = native_component_names(component)
    for directory in _native_search_dirs(native_component_subdir(component)):
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def _bundled_or_system_binary(name):
    """نسخه‌ی همراه پروژه (اولویت)، وگرنه نسخه‌ی PATH؛ None اگه هیچ‌کدوم نبود."""
    candidate = find_native_component(name)
    if candidate:
        return _ensure_executable(candidate)
    return shutil.which(name) or None


# ---------------------------------------------------------------- ffmpeg

def ffmpeg_binary():
    """
    مسیر کامل خود فایل اجرایی ffmpeg، یا None اگه هیچ‌جا نبود.
    اولویت با نسخه‌ی همراه پروژه/کنار فایل اجرایی‌ست (find_native_component)
    تا نسخه‌ی نصب‌شده‌ی سیستم (PATH).
    """
    return _bundled_or_system_binary("ffmpeg")


def ffmpeg_location():
    """
    چیزی که yt-dlp به‌عنوان ffmpeg_location می‌خواد: *پوشه‌ی* ffmpeg، نه
    خود فایل. اگه ffmpeg از PATH پیدا شده باشه None برمی‌گردونه (یعنی
    yt-dlp خودش از PATH پیداش کنه).
    """
    candidate = find_native_component("ffmpeg")
    return os.path.dirname(candidate) if candidate else None


def has_ffmpeg():
    return ffmpeg_binary() is not None


# ------------------------------------------------------------ tesseract

def tesseract_binary():
    """
    مسیر کامل فایل اجرایی tesseract، یا None اگه هیچ‌جا نبود. اولویت با
    نسخه‌ی همراه پروژه/کنار فایل اجرایی‌ست (install.py می‌تونه ویندوزش رو
    اونجا نصب کرده باشه)، وگرنه نسخه‌ی نصب‌شده‌ی سیستم (PATH -- روی لینوکس
    apt/dnf همیشه همین‌جا می‌ذارتش).
    """
    return _bundled_or_system_binary("tesseract")


def has_tesseract():
    return tesseract_binary() is not None


# ------------------------------------------------------- TeamTalk SDK

def teamtalk_library_names():
    return native_component_names("teamtalk")


def teamtalk_library_path():
    """مسیر مطلق کتابخانه‌ی SDK اگه همراه پروژه/کنار فایل اجرایی باشه، وگرنه None."""
    return find_native_component("teamtalk")


# ------------------------------------------------------------- libmpv

def mpv_library_names():
    return native_component_names("mpv")


def mpv_library_path():
    """مسیر مطلق libmpv اگه همراه پروژه/کنار فایل اجرایی باشه، وگرنه None."""
    return find_native_component("mpv")


# ------------------------------------------------ آماده‌سازی قبل از import

_prepared = False


def prepare_native_libraries():
    """
    قبل از import شدن TeamTalk5/mpv صدا زده می‌شه (از core/teamtalk/__init__.py و
    core/mpv/__init__.py). فقط کاری می‌کنه که لودرِ خود سیستم‌عامل بتونه
    کتابخانه‌های همراه پروژه رو پیدا کنه؛ خود لود کردن کار همون ماژول‌هاست
    (که خودشون هم، برای پشتیبانیِ درستِ override کنار فایل اجرایی، از
    find_native_component بالا استفاده می‌کنن -- این تابع فقط یه لایه‌ی
    دفاعیِ اضافه‌ست برای وابستگی‌های *غیرمستقیمِ* همون DLLها).
    """
    global _prepared
    if _prepared:
        return
    _prepared = True

    # هم کنار فایل اجرایی هم داخل باندل، برای هر سه کلیدی که واقعاً لود
    # می‌شن -- در اجرای مستقیم از سورس این‌ها با هم یکی‌ان.
    project_lib_dirs = []
    for key in ("teamtalk", "mpv", "ffmpeg"):
        project_lib_dirs.extend(_native_search_dirs(native_component_subdir(key)))
    seen = set()
    unique_dirs = []
    for d in project_lib_dirs:
        if d not in seen:
            seen.add(d)
            unique_dirs.append(d)

    if IS_WINDOWS:
        # هم add_dll_directory (روش درست از پایتون ۳.۸ به بعد) و هم PATH:
        # mpv.py خودش صریحاً روی %PATH% حساب می‌کنه.
        for d in unique_dirs:
            if not os.path.isdir(d):
                continue
            try:
                os.add_dll_directory(d)
            except (AttributeError, OSError):
                pass
            if d not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    else:
        # روی لینوکس/مک تغییر LD_LIBRARY_PATH بعد از استارت پروسه دیگه اثری
        # روی لودر نداره، پس کتابخانه‌ها با مسیر *مطلق* لود می‌شن (کاری که
        # TeamTalk5.py و mpv.py بعد از پچ همین ریپو انجام می‌دن). فقط
        # مطمئن می‌شیم ffmpeg همراه پروژه قابل اجرا باشه.
        binary = ffmpeg_binary()
        if binary:
            _ensure_executable(binary)


def missing_runtime_requirements():
    """
    لیست چیزهایی که برای اجرا لازمن ولی پیدا نشدن، به‌صورت متن خوانا.
    launcher و ربات لایسنس ازش برای یه پیام خطای مفید استفاده می‌کنن،
    به‌جای یه ImportError خام وسط اجرا.
    """
    problems = []

    if teamtalk_library_path() is None:
        names = " یا ".join(teamtalk_library_names())
        problems.append(
            f"کتابخانه‌ی TeamTalk SDK ({names}) توی پوشه‌ی core/teamtalk/ نیست. "
            "از bearware.dk نسخه‌ی مخصوص همین سیستم‌عامل رو دانلود کن و اونجا بذار."
        )

    if mpv_library_path() is None:
        import ctypes.util
        if not ctypes.util.find_library("mpv"):
            loadable = False
            for name in mpv_library_names():
                try:
                    ctypes.CDLL(name)
                    loadable = True
                    break
                except OSError:
                    continue
            if not loadable:
                if IS_LINUX:
                    problems.append("libmpv پیدا نشد. روی دبیان/اوبونتو: sudo apt install libmpv2 (یا libmpv1)")
                else:
                    problems.append("libmpv پیدا نشد؛ فایلش رو کنار پوشه‌ی core/mpv/ بذار.")

    if not has_ffmpeg():
        if IS_LINUX:
            problems.append("ffmpeg پیدا نشد. روی دبیان/اوبونتو: sudo apt install ffmpeg")
        else:
            problems.append("ffmpeg پیدا نشد؛ توی PATH نصبش کن یا فایلش رو توی bin/ بذار.")

    return problems


def describe_runtime():
    """یه خلاصه‌ی تک‌خطی برای لاگ استارت‌آپ."""
    return (
        f"{system_name()} / python {sys.version_info.major}.{sys.version_info.minor} / "
        f"teamtalk={'bundled' if teamtalk_library_path() else 'system'} / "
        f"mpv={'bundled' if mpv_library_path() else 'system'} / "
        f"ffmpeg={'yes' if has_ffmpeg() else 'no'}"
    )


def js_runtime():
    """
    مقداری که yt-dlp به‌عنوان js_runtimes می‌خواد (همون چیزی که پرچمِ خط
    فرمانِ --js-runtimes می‌سازه): دیکشنری از اسمِ runtime به تنظیماتش
    (مثل {"deno": {"path": "..."}})، یا دیکشنریِ خالی اگه هیچ‌کدوم پیدا
    نشد. yt-dlp ۲۰۲۶ بدون این، برای استخراج یوتیوب هشدار «No supported
    JavaScript runtime» می‌ده.

    وصل‌کردنش به گزینه‌های واقعیِ yt-dlp (ydl_opts["js_runtimes"]) کار جای
    دیگه‌ایه؛ این تابع فقط *پیدا می‌کنه*، تصمیم نمی‌گیره.

    اولویت:
      ۱. deno ای که کنار پروژه/فایل اجرایی باشه (چیزی که install.py
         می‌تونه دانلود کرده باشه)، وگرنه deno ای که خودِ سیستم نصبش
         کرده و توی PATH است.
      ۲. node روی PATH -- yt-dlp با اون هم کار می‌کنه، فقط deno رو
         ترجیح می‌ده.
      وگرنه {} (yt-dlp خودش با همون هشدار رفتار فعلی رو ادامه می‌ده).
    """
    path = find_native_component("deno") or shutil.which("deno")
    if path:
        return {"deno": {"path": path}}
    path = shutil.which("node")
    if path:
        return {"node": {"path": path}}
    return {}
