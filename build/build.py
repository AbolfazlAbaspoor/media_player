"""
بیلد فایل اجرایی مستقل، روی ویندوز و لینوکس با یک دستور:

    python build/build.py               # ربات + پلتفرم
    python build/build.py bot           # فقط ربات
    python build/build.py license       # فقط پلتفرم لایسنس
    python build/build.py --onefile     # همه‌چیز توی یه فایل (کندتر بالا میاد)
    python build/build.py --clean       # پاک‌کردن dist/build قبل از بیلد

## نکته‌ی مهم: کراس‌کامپایل ممکن نیست

PyInstaller باینری همون سیستمی رو می‌سازه که روش اجرا می‌شه. برای نسخه‌ی
ویندوزی باید روی ویندوز بیلد کنی و برای لینوکسی روی لینوکس. همین اسکریپت
روی هر دو کار می‌کنه و خودش تفاوت‌ها رو (پسوند فایل، جداکننده‌ی مسیر
`--add-data`، اسم کتابخونه‌های نیتیو) هندل می‌کنه.

## چه چیزهایی داخل بیلد می‌رن

  * پوشه‌های `commands/`, `core/services/`, `languages/` به‌صورت *داده*
    (نه کد کامپایل‌شده) — چون در زمان اجرا با importlib از روی فایل خونده
    می‌شن و PyInstaller نمی‌تونه حدس بزنه لازمشون داریم.
  * کتابخونه‌های نیتیو (TeamTalk SDK، libmpv، ffmpeg) اگه همراه پروژه باشن
    -- ولی فقط برای هدفی که واقعاً در زمان اجرا لودشون می‌کنه. TARGETS[key]["native"]
    مشخص می‌کنه کدوم؛ جزئیات و شواهدش توی docs/BUILD.md. مثلاً ttbot-manage
    این‌ها رو نداره چون دستورهای devices/selftest نبودشون رو با یه پیام
    روشن گزارش می‌دن، نه کرش -- و همین باعث شده بود UPX ساعت‌ها روی
    باینری‌های بی‌مصرف این هدف گیر کنه.

## چه چیزهایی *بیرون* می‌مونن

  * پوشه‌ی `data/` — کانفیگ و دیتای هر نصب، نه بخشی از برنامه. کنار فایل
    اجرایی ساخته می‌شه (core/paths.py برای حالت frozen همین‌طور حساب می‌کنه).
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BUILD_DIR)
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
WORK_DIR = os.path.join(BUILD_DIR, "_work")

# برای import کردن core.platform_paths -- این اسکریپت با `python
# build/build.py` اجرا می‌شه (نه به‌صورت ماژول)، پس فقط پوشه‌ی build/ خودکار
# روی sys.path میاد، نه ریشه‌ی پروژه.
sys.path.insert(0, PROJECT_DIR)
from core import platform_paths  # noqa: E402
from core.paths import force_utf8_console  # noqa: E402

force_utf8_console()

IS_WINDOWS = platform.system().lower().startswith("win")
# جداکننده‌ی --add-data روی ویندوز ";" و روی بقیه ":" است.
DATA_SEP = ";" if IS_WINDOWS else ":"

# پوشه‌هایی که در زمان اجرا با importlib/os.listdir خونده می‌شن، پس باید
# به‌عنوان داده کنار برنامه باشن.
DATA_DIRS = ["commands", "languages", os.path.join("core", "services")]

# کتابخونه‌های نیتیو، اگه همراه پروژه باشن. نبودنشون خطا نیست: روی لینوکس
# معمولاً از پکیج سیستم استفاده می‌شه.
#
# کلیددار (نه یه لیست تخت) چون هر هدف توی TARGETS فقط زیرمجموعه‌ای از
# این‌ها رو لازم داره -- ببین TARGETS[...]["native"] و توضیح بالای آن.
#
# اسم‌های فایل از core.platform_paths.NATIVE_COMPONENTS می‌آد (E16) -- تنها
# منبع این اسم‌ها، تا لیستِ این‌جا و لیستِ چک‌های زمان اجرا از هم عقب
# نیفتن. هر دو اسمِ ممکن (ویندوز/لینوکس) قید می‌شه چون این اسکریپت با یه
# کد روی هر دو سیستم‌عامل بیلد می‌کنه؛ os.path.isfile پایین‌تر خودش فیلتر
# می‌کنه کدوم واقعاً کنار پروژه‌ست.
NATIVE_FILES = {
    key: [os.path.join(platform_paths.native_component_subdir(key), name)
          for name in platform_paths.native_component_all_names(key)]
    for key in ("teamtalk", "mpv", "ffmpeg", "xray")
}

#: ماژول‌هایی که PyInstaller با آنالیز استاتیک برمی‌داره ولی در عمل هیچ‌وقت
#: اجرا نمی‌شن. هر کدوم ده‌ها مگابایت به بسته اضافه می‌کرد.
#:
#:   * moviepy/numpy — instagrapi فقط توی مسیرهای *آپلود* (clip/igtv/video/
#:     story) و اون‌هم داخل تابع importشون می‌کنه. ربات ما فقط لاگین و
#:     دانلود می‌کنه، پس این مسیرها اصلاً صدا زده نمی‌شن.
#:     numpy خودش openblas رو هم می‌کِشه: ۴۰+۳۵ مگ.
#:
#:   * playwright — درایورش یه Node.js کامل (۸۹ مگ) است، ولی *مرورگر* توی
#:     بسته نیست و مرورگر جدا نصب می‌شه. یعنی روی سیستم مشتری این قابلیت
#:     در هر حالت fail می‌کرد؛ ۱۰۱ مگ می‌داد و هیچ کاری نمی‌کرد.
#:     core/browser_extract.py خودش ImportError رو تمیز هندل می‌کنه.
#:     اگه یه روز مرورگر رو هم با بسته فرستادی، از این لیست درش بیار.
#:   * tkinter/tcl/tk — ربات کنسولیه و هیچ GUI ای نداره. PyInstaller از روی
#:     PIL.ImageTk برمی‌داشتش — ۷ مگ برای چیزی که هیچ‌وقت import نمی‌شه.
BOT_EXCLUDES = ["moviepy", "numpy", "playwright", "tkinter"]

# هر هدف فقط native هایی که *واقعاً* در زمان اجرا لود می‌کنه رو می‌گیره --
# نه همه‌چیز رو، صرفاً چون اسمش «ربات‌ـمانند» است. تشخیص از روی ایمپورت
# واقعی داده شده (نه حدس از روی اسم فایل)، جزئیات و شواهد توی docs/BUILD.md:
#
#   * bot        -> import مستقیم (bot.py: core.teamtalk.ttbot،
#                   core.teamtalk.TeamTalk5، core.mpv.player) + ffmpeg واقعی برای
#                   yt-dlp. تنها هدفی که واقعاً صدا پخش/ضبط می‌کنه.
#   * launcher   -> ربات رو به‌عنوان *پروسه‌ی جدا* بالا می‌آره (bot.py یا
#                   ttbot.exe کنارش)، نه import مستقیم. خودش هیچ‌جا
#                   teamtalk/mpv رو import نمی‌کنه؛ چک‌های
#                   platform_paths فقط یه هشدار چاپ می‌کنن و جلوی بالا
#                   اومدن رباتها رو نمی‌گیرن.
#   * license    -> license_server.py هم مثل launcher فقط bot.py رو
#                   به‌عنوان پروسه‌ی جدا (از طریق licensing/supervisor.py)
#                   بالا می‌آره؛ خودش هیچ import ای از teamtalk/mpv نداره.
#   * manage     -> core/audio_lines.py توابع دستگاه‌ها (list_output_devices
#                   برای mpv، list_sound_devices برای teamtalk) رو *تابعی*
#                   و توی try/except import می‌کنه و نبودشون رو با یه
#                   پیام روشن («پیدا نشد — libmpv/TeamTalk SDK سر جاشه؟»)
#                   گزارش می‌ده، نه کرش. cmd_selftest هم player=None,
#                   tt=None می‌ده، یعنی هیچ‌وقت واقعاً دستگاه رو باز نمی‌کنه.
# xray: هسته‌ی V2Ray (core/xray_proxy.py)، با پروسه‌ی جدا اجرا می‌شه؛ فقط bot.
NATIVE_BOT_FULL = ["teamtalk", "mpv", "ffmpeg", "xray"]

TARGETS = {
    "bot": {
        "script": "bot.py",
        "name": "ttbot",
        "console": True,
        # core.services فقط به‌صورت *داده* کپی می‌شه (چون با importlib از روی
        # فایل خونده می‌شه)، پس خودِ پکیج توی باندل نیست. سرویس‌های
        # جدید از `core.services._ytdlp_service` ارث می‌برن، و بدون این خط
        # همه‌شون توی بیلد با ImportError رد می‌شن -- درحالی که توی
        # اجرای عادی سالمن، پس موقع توسعه دیده نمی‌شه.
        "hidden": ["yt_dlp", "cryptography.fernet", "nacl.public",
                   "core.services", "core.services._ytdlp_service"],
        "excludes": BOT_EXCLUDES,
        "native": NATIVE_BOT_FULL,
    },
    "launcher": {
        "script": "launcher.py",
        "name": "ttbot-launcher",
        "console": True,
        "hidden": [],
        "excludes": BOT_EXCLUDES,
        # ربات رو با subprocess.Popen بالا می‌آره (launcher.py:_bot_command)،
        # نه import؛ خودش هیچ‌وقت DLL/so ای رو لود نمی‌کنه.
        "native": [],
    },
    "license": {
        "script": "license_server.py",
        "name": "ttbot-license",
        "console": True,
        "hidden": ["telegram", "telegram.ext", "pytesseract", "PIL", "PIL.Image"],
        # همون منطق launcher: ربات‌های مشتری از طریق licensing/supervisor.py
        # به‌صورت پروسه‌ی جدا بالا می‌آن (subprocess روی bot.py)، نه import.
        "native": [],
    },
    "manage": {
        "script": "manage.py",
        "name": "ttbot-manage",
        "console": True,
        # همون دلیل هدف bot: selftest این‌جا هم سرویس‌ها رو لود می‌کنه.
        "hidden": ["nacl.public", "core.services", "core.services._ytdlp_service"],
        # devices/selftest دستگاه‌ها رو *تابعی* و با try/except چک می‌کنن
        # (core/audio_lines.py) و نبودن SDK/mpv رو با پیام روشن گزارش
        # می‌دن، نه کرش -- دقیقاً همون چیزی که یه بار ۱۴۰+ مگ باینری
        # بی‌مصرف رو زیر UPX برای این هدف چند ساعت هنگ کرده بود.
        "native": [],
    },
}


#: جاهایی که دنبال upx می‌گردیم. نبودنش خطا نیست -- فقط بیلد
#: بزرگ‌تر درمیاد.
UPX_DIRS = [
    os.environ.get("UPX_DIR", ""),
    os.path.join(BUILD_DIR, "upx"),
]

#: این‌ها فشرده نمی‌شن. DLL های رانتایم ویندوز با UPX خراب
#: می‌شن (لودر ویندوز خودش بازشون می‌کنه و با بسته‌ی UPX کنار
#: نمی‌آد)، و باقی‌مونده هم اونقدر کوچیکن که ارزشش رو نداره.
UPX_EXCLUDE = [
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "python311.dll",
    "api-ms-win-*.dll",
    "ucrtbase.dll",
]


def _find_upx():
    """
    مسیر پوشه‌ی upx، یا None.

    چرا ارزشش رو داره: حجم بسته رو تقریباً نصف می‌کنه، چون
    سنگین‌ترین فایل‌ها (libmpv و TeamTalk و ffmpeg) همه بایناری
    نیتیون و خوب فشرده می‌شن.

    هزینه‌ش: هر فایل موقع لود توی حافظه باز می‌شه، پس بالا آمدن
    یکی دو ثانیه کندتر می‌شه. و بعضی آنتی‌ویروس‌ها به فایلِ
    UPX شده مشکوک می‌شن -- اگه مشتری گزارش داد، با --no-upx
    بیلد کن.
    """
    name = "upx.exe" if IS_WINDOWS else "upx"
    for directory in UPX_DIRS:
        if directory and os.path.isfile(os.path.join(directory, name)):
            return directory
    found = shutil.which(name)
    return os.path.dirname(found) if found else None


def _check_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("PyInstaller نصب نیست:  pip install pyinstaller")
        return False


def _add_data_args(native_keys=()):
    """
    آرگومان‌های --add-data/--add-binary برای یه هدف.

    native_keys فقط همون کلیدهایی از NATIVE_FILES است که TARGETS[key]["native"]
    اعلام کرده -- یعنی هدفی که مثلاً "teamtalk" رو نخواسته، حتی اگه فایلش
    کنار پروژه باشه، اصلاً بررسی نمی‌شه.
    """
    args = []
    for relative in DATA_DIRS:
        source = os.path.join(PROJECT_DIR, relative)
        if os.path.isdir(source):
            args += ["--add-data", f"{source}{DATA_SEP}{relative}"]
        else:
            print(f"  (رد شد، وجود نداره: {relative})")

    for key in native_keys:
        found = False
        for relative in NATIVE_FILES.get(key, []):
            source = os.path.join(PROJECT_DIR, relative)
            if os.path.isfile(source):
                target = os.path.dirname(relative) or "."
                args += ["--add-binary", f"{source}{DATA_SEP}{target}"]
                print(f"  + {relative}")
                found = True
        if not found:
            # نبودنِ کامپوننت خطا نیست (لینوکس از پکیج سیستم استفاده می‌کنه)،
            # ولی بی‌صدا رد شدنش باعث می‌شد بسته‌ی بدون xray/ffmpeg ناخواسته
            # ساخته بشه.
            print(f"  !! هشدار: کامپوننت نیتیو «{key}» کنار پروژه پیدا نشد و "
                  f"داخل بسته نمی‌ره (مسیرهای بررسی‌شده: "
                  f"{', '.join(NATIVE_FILES.get(key, []))})")
    return args


def build_command(key, onefile=False, use_upx=True):
    """
    دستور کامل PyInstaller برای یه هدف، *بدون اجراش*.

    از build_target() جدا شده تا تست‌ها (tests/test_build_targets.py)
    بتونن بدون بیلد واقعی چک کنن که مثلاً هدف‌های بی‌صدا (launcher/license/
    manage) هیچ --add-binary ای برای ffmpeg/mpv/teamtalk توی دستورشون
    نیست -- دقیقاً همون چیزی که این تابع تضمین می‌کنه.
    """
    target = TARGETS[key]
    script = os.path.join(PROJECT_DIR, target["script"])
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", target["name"],
        "--distpath", DIST_DIR,
        "--workpath", WORK_DIR,
        "--specpath", WORK_DIR,
        "--onefile" if onefile else "--onedir",
        "--console" if target["console"] else "--windowed",
        # ماژول‌های داخل پوشه‌های پلاگین با importlib لود می‌شن؛ PyInstaller
        # نمی‌تونه با آنالیز استاتیک پیداشون کنه.
        "--paths", PROJECT_DIR,
    ]
    # هشدارهای لودرِ خود PyInstaller قبل از اولین خط کد ما چاپ می‌شن، پس
    # فقط از این‌جا می‌شه خفه‌شون کرد. جزئیات توی خود فایل hook.
    rthook = os.path.join(BUILD_DIR, "rthook_quiet.py")
    if os.path.isfile(rthook):
        command += ["--runtime-hook", rthook]

    for module in target["hidden"]:
        command += ["--hidden-import", module]
    for module in target.get("excludes", []):
        command += ["--exclude-module", module]

    upx_dir = _find_upx() if use_upx else None
    if upx_dir:
        command += ["--upx-dir", upx_dir]
        for pattern in UPX_EXCLUDE:
            command += ["--upx-exclude", pattern]
        print("  (upx: " + upx_dir + ")")
    elif use_upx:
        print("  (upx پیدا نشد — بیلد بزرگ‌تر می‌شه. build/upx/upx.exe بذار یا UPX_DIR رو ست کن)")
    else:
        command += ["--noupx"]
    command += _add_data_args(target.get("native", []))
    command.append(script)
    return command


def build_target(key, onefile=False, use_upx=True):
    target = TARGETS[key]
    script = os.path.join(PROJECT_DIR, target["script"])
    if not os.path.isfile(script):
        print(f"!! {target['script']} پیدا نشد، رد شد.")
        return False

    print(f"\n=== بیلد {target['name']} ({target['script']}) ===")
    command = build_command(key, onefile=onefile, use_upx=use_upx)

    result = subprocess.run(command, cwd=PROJECT_DIR)
    if result.returncode != 0:
        print(f"!! بیلد {target['name']} شکست خورد (کد {result.returncode})")
        return False
    print(f"✓ {target['name']} -> {os.path.join(DIST_DIR, target['name'])}")
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="بیلد فایل اجرایی")
    parser.add_argument("targets", nargs="*", default=None,
                        help="bot / launcher / license / manage (پیش‌فرض: همه)")
    parser.add_argument("--onefile", action="store_true",
                        help="یه فایل اجرایی تنها (کندتر بالا میاد، جابه‌جایی راحت‌تر)")
    parser.add_argument("--clean", action="store_true",
                        help="پاک‌کردن dist/ و پوشه‌ی کاری قبل از بیلد")
    parser.add_argument("--no-upx", action="store_true",
                        help="بدون فشرده‌سازی UPX (بیلد بزرگ‌تر، ولی بدون حساسیت آنتی‌ویروس)")
    args = parser.parse_args(argv)

    if not _check_pyinstaller():
        return 1

    print(f"سیستم بیلد: {platform.system()} {platform.machine()}")
    print("توجه: PyInstaller کراس‌کامپایل نمی‌کنه — این بیلد فقط روی همین")
    print("      سیستم‌عامل اجرا می‌شه. برای اون‌یکی، همین اسکریپت رو اونجا بزن.\n")

    if args.clean:
        for directory in (DIST_DIR, WORK_DIR):
            if os.path.isdir(directory):
                print(f"پاک کردن {directory}")
                shutil.rmtree(directory, ignore_errors=True)

    selected = args.targets or ["bot", "launcher", "license", "manage"]
    unknown = [t for t in selected if t not in TARGETS]
    if unknown:
        print(f"هدف ناشناس: {', '.join(unknown)}")
        print(f"هدف‌های موجود: {', '.join(TARGETS)}")
        return 2

    ok = True
    for key in selected:
        ok = build_target(key, onefile=args.onefile, use_upx=not args.no_upx) and ok

    print()
    if ok:
        print(f"✓ همه‌ی بیلدها انجام شد: {DIST_DIR}")
        print()
        print("یادت باشه کنار فایل اجرایی این‌ها لازمن:")
        print("  - پوشه‌ی data/  (خودش ساخته می‌شه؛ کانفیگ و دیتای هر نصب)")
        if not IS_WINDOWS:
            print("  - libTeamTalk5.so و libmpv (اگه توی بیلد نبودن، از پکیج سیستم)")
        return 0
    print("!! بعضی بیلدها شکست خوردن.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
