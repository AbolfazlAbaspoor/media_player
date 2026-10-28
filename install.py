"""
نصب یک‌مرحله‌ای همه‌ی چیزهایی که ربات لازم داره (E9) -- از پوشه‌ی پروژه،
روی یه سیستم تازه، فقط با stdlib (بدون هیچ وابستگیِ خارجی برای خودِ
اسکریپت نصب):

    python install.py                 # همه‌چیزِ پیش‌فرض
    python install.py --dry-run       # فقط پلن؛ بدون دانلود/نصب واقعی
    python install.py --components ffmpeg,libmpv
    python install.py --with-licensing --venv .venv

## چی نصب می‌شه

  * وابستگی‌های پایتون از requirements.txt (و با --with-licensing از
    requirements-license.txt هم)، اختیاری توی یه venv.
  * ffmpeg، libmpv، SDK تیم‌تاک -- مقصدشون از core.platform_paths
    (NATIVE_COMPONENTS/E16) می‌آد، نه یه لیست مسیرِ جدا این‌جا.
  * pulseaudio-utils (pactl) روی لینوکس -- لاین‌های صدا (core/audio_lines.py)
    بهش نیاز دارن؛ روی ویندوز معادلی نداره (Virtual Audio Cable) و رد می‌شه.
  * یه جاوااسکریپت‌رانتایم برای استخراج یوتیوبِ yt-dlp (deno ترجیح داده
    می‌شه، node موجود هم قبوله) -- ببین core.platform_paths.js_runtime().
  * اختیاری: xray-core، برای یه فیچرِ V2Ray به‌ازای هر ربات که هنوز پیاده
    نشده؛ فقط با --components xray (یا اضافه‌کردنش به لیست) نصب می‌شه.
  * اختیاری: tesseract (موتور OCR بررسی خودکار رسید --
    licensing/receipts.py)؛ فقط با --components tesseract نصب می‌شه، چون
    فقط سرورِ ربات لایسنس بهش نیاز داره، نه نصب‌های عادیِ ربات تیم‌تاک.

## استراتژیِ هر سیستم‌عامل

روی لینوکس اول پکیج‌منیجر (apt یا dnf) امتحان می‌شه؛ اگه نبود یا نصب
شکست خورد، برای ffmpeg دانلود جایگزین هست (بیلدِ BtbN)، ولی برای libmpv
دانلودِ قابل‌اعتمادی برای لینوکس وجود نداره -- به‌جاش راهنمای دستی چاپ
می‌شه. روی ویندوز مستقیم از صفحه‌ی ریلیزهای رسمیِ هر پروژه دانلود می‌شه
(BtbN برای ffmpeg، shinchiro/mpv-winbuild-cmake برای libmpv، GitHub
ریلیزهای خودِ deno/xray). SDK تیم‌تاکِ ویندوز از قبل همراه ریپوعه؛ لینوکسش
لایسنس/ثبت‌نام بِیرور رو لازم داره، پس دانلود خودکار نداره.

## ایمنی

idempotent است: هر کامپوننتی که از قبل کار می‌کنه رد می‌شه (با
platform_paths، نه فقط «فایل هست یا نه»)، و بعد از نصب دوباره همون چک رو
می‌زنه تا مطمئن بشه واقعاً جواب داد. --dry-run هیچ تابع دانلود/فراخوانیِ
شبکه‌ای‌ای رو صدا نمی‌زنه -- فقط پلن چاپ می‌شه.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from core import platform_paths  # noqa: E402
from core.paths import force_utf8_console  # noqa: E402
from core.platform_paths import _ensure_executable as _ensure_native_executable  # noqa: E402

force_utf8_console()


class InstallError(Exception):
    """خطای پیش‌بینی‌شده‌ی یه قدمِ نصب (دانلود، استخراج، اجرای دستور)."""


class Status:
    OK = "ok"            # از قبل کار می‌کنه، کاری لازم نبود
    PLANNED = "planned"  # --dry-run: این کار انجام می‌شد
    DONE = "done"        # همین الان نصب/دانلود شد و تأیید شد
    MANUAL = "manual"    # خودکار نمی‌شه؛ راهنمای دستی چاپ شد
    FAILED = "failed"    # تلاش شد ولی شکست خورد


STATUS_LABELS = {
    Status.OK: "از قبل موجود بود",
    Status.PLANNED: "(dry-run) پلن آماده‌ست",
    Status.DONE: "نصب شد",
    Status.MANUAL: "نیاز به کار دستی (بالا رو ببین)",
    Status.FAILED: "شکست خورد",
}

COMPONENT_LABELS = {
    "python": "وابستگی‌های پایتون",
    "teamtalk": "TeamTalk SDK",
    "ffmpeg": "ffmpeg",
    "libmpv": "libmpv",
    "pulseaudio_utils": "ابزارهای pulseaudio (pactl -- لاین‌های صدای لینوکس)",
    "js_runtime": "جاوااسکریپت‌رانتایمِ yt-dlp (deno/node)",
    "xray": "xray-core (اختیاری -- هسته‌ی V2Ray برای دستور proxy)",
    "tesseract": "tesseract OCR (اختیاری -- بررسی خودکار رسید در ربات لایسنس)",
}

#: xray-core و tesseract عمداً بیرون از پیش‌فرضن: «اختیاری» طبق مشخصات
#: E9 (xray) و چون فقط سرورِ ربات لایسنس بهشون نیاز داره، نه نصب عادیِ
#: ربات تیم‌تاک.
DEFAULT_COMPONENTS = ["python", "teamtalk", "ffmpeg", "libmpv", "pulseaudio_utils", "js_runtime"]
ALL_COMPONENTS = DEFAULT_COMPONENTS + ["xray", "tesseract"]

USER_AGENT = "ttbot-install.py"
GITHUB_API = "https://api.github.com"

# دانلودهای مستقیم با اسمِ asset ثابت -- خود GitHub با /releases/latest/
# download/<name> همیشه به آخرین نسخه ریدایرکت می‌کنه، پس نیازی به صدا
# زدنِ API نیست. فقط بیلدِ libmpv ویندوز (shinchiro) اسمِ فایلش تاریخ و
# کامیت داره و از API لازم می‌شه (_resolve_libmpv_windows_url پایین‌تر).
FFMPEG_URLS = {
    "windows": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "linux": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl-shared.tar.xz",
}
DENO_URLS = {
    "windows": "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
    "linux": "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip",
}
XRAY_URLS = {
    "windows": "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip",
    "linux": "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip",
}
#: اسم asset با تاریخ/کامیت عوض می‌شه، پس با یه الگو پیدا می‌شه (نه اسمِ
#: ثابت). نسخه‌ی v3 (نیازمند AVX2) عمداً رد می‌شه تا روی هر CPU ای کار کنه.
LIBMPV_WINDOWS_ASSET_PATTERN = re.compile(r"^mpv-dev-x86_64-(?!.*-v3-)\d+-git-[0-9a-f]+\.7z$")

#: نصب‌کننده‌ی رسمیِ ویندوزِ tesseract (UB-Mannheim). اسمش با شماره‌ی
#: نسخه عوض می‌شه، پس با الگو پیدا می‌شه -- دقیقاً مثل libmpv بالا.
TESSERACT_WINDOWS_ASSET_PATTERN = re.compile(r"^tesseract-ocr-w64-setup-[\d.]+\.exe$")


# --------------------------------------------------------------- شبکه
#
# این دو تابع تنها جاهایی هستن که این اسکریپت واقعاً به شبکه وصل می‌شه.
# --dry-run هیچ‌کدومشون رو صدا نمی‌زنه (تست‌ها همینو با mock تضمین می‌کنن).

def _http_get_json(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url, dest_path):
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response, open(dest_path, "wb") as out_file:
        shutil.copyfileobj(response, out_file)
    return dest_path


def _verify_sha256(archive, url):
    """
    اگه ناشر کنار asset یه فایل digest (<url>.dgst، فرمت Xray-core) منتشر
    کرده باشه، SHA-256 آرشیو رو باهاش تطبیق می‌ده و در صورت مغایرت
    InstallError می‌ده. اگه digest منتشر نشده باشه (404) بی‌صدا رد می‌شه.
    """
    import hashlib
    try:
        request = urllib.request.Request(url + ".dgst", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise
    match = re.search(r"SHA2?-?256\s*=\s*([0-9a-fA-F]{64})", text)
    if not match:
        return False
    digest = hashlib.sha256()
    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != match.group(1).lower():
        raise InstallError("SHA-256 آرشیوِ دانلودشده با digest منتشرشده نمی‌خونه؛ نصب متوقف شد.")
    print("  SHA-256 تأیید شد.")
    return True


def _pick_asset(release, pattern):
    for asset in release.get("assets", []):
        if pattern.search(asset.get("name", "")):
            return asset
    return None


def _resolve_windows_release_asset(repo, pattern, asset_label):
    release = _http_get_json(f"{GITHUB_API}/repos/{repo}/releases/latest")
    asset = _pick_asset(release, pattern)
    if not asset:
        raise InstallError(
            f"asset مناسب ({asset_label}) توی آخرین ریلیزِ "
            f"{repo} پیدا نشد.")
    return asset["browser_download_url"], asset["name"]


def _resolve_libmpv_windows_url():
    return _resolve_windows_release_asset(
        "shinchiro/mpv-winbuild-cmake", LIBMPV_WINDOWS_ASSET_PATTERN, "mpv-dev-x86_64-*.7z")


def _resolve_tesseract_windows_url():
    return _resolve_windows_release_asset(
        "UB-Mannheim/tesseract", TESSERACT_WINDOWS_ASSET_PATTERN, "tesseract-ocr-w64-setup-*.exe")


# ------------------------------------------------------------ آرشیو‌ها

def _safe_member_path(dest_dir, member_name):
    """
    مسیرِ نهاییِ یه عضوِ آرشیو، فقط اگه واقعاً زیرِ dest_dir بمونه (نه یه
    ../../ که از پوشه‌ی مقصد بزنه بیرون). امن‌سازیِ استخراج در برابر آرشیو
    مخرب -- حتی وقتی منبع GitHub رسمیه، هزینه‌ش صفره.
    """
    target = os.path.abspath(os.path.join(dest_dir, member_name))
    dest_abs = os.path.abspath(dest_dir)
    if os.path.commonpath([dest_abs, target]) != dest_abs:
        return None
    return target


def _extract_zip(archive_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            target = _safe_member_path(dest_dir, info.filename)
            if not target:
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return dest_dir


def _extract_tar(archive_path, dest_dir, mode):
    os.makedirs(dest_dir, exist_ok=True)
    with tarfile.open(archive_path, mode=mode) as tf:
        safe_members = []
        for member in tf.getmembers():
            if _safe_member_path(dest_dir, member.name):
                safe_members.append(member)
        tf.extractall(dest_dir, members=safe_members)
    return dest_dir


def _extract_archive(archive_path, dest_dir):
    lower = archive_path.lower()
    if lower.endswith(".zip"):
        return _extract_zip(archive_path, dest_dir)
    if lower.endswith(".tar.xz") or lower.endswith(".txz"):
        return _extract_tar(archive_path, dest_dir, "r:xz")
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        return _extract_tar(archive_path, dest_dir, "r:gz")
    raise InstallError(f"فرمت آرشیو ناشناس: {archive_path}")


def _extract_7z(archive_path, dest_dir):
    """
    stdlib هیچ پشتیبانیِ 7z ای نداره (فقط zip/tar). اگه یه ابزار 7z روی
    PATH باشه ازش استفاده می‌کنیم؛ وگرنه None برمی‌گردونیم و صدازننده
    راهنمای دستی می‌ده.
    """
    tool = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
    if not tool:
        return None
    os.makedirs(dest_dir, exist_ok=True)
    result = subprocess.run([tool, "x", f"-o{dest_dir}", "-y", archive_path],
                             capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return dest_dir


def _find_in_tree(root, filename):
    for dirpath, _dirs, files in os.walk(root):
        if filename in files:
            return os.path.join(dirpath, filename)
    return None


# --------------------------------------------------------- خروجی/پرینت

def _ok(msg):
    print(f"  ✅ {msg}")


def _plan(msg):
    print(f"  \U0001f553 [dry-run] {msg}")


def _manual(msg):
    print(f"  ⚠️  {msg}")


def _fail(msg):
    print(f"  ✗ {msg}")
    return Status.FAILED


# --------------------------------------------------------- پکیج‌منیجر

_apt_updated = False


def _package_manager():
    if shutil.which("apt-get"):
        return "apt"
    if shutil.which("dnf"):
        return "dnf"
    return None


def _maybe_sudo(cmd):
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return ["sudo"] + cmd
    return cmd


def _package_install(pm, packages):
    global _apt_updated
    if pm == "apt" and not _apt_updated:
        _apt_updated = True
        subprocess.run(_maybe_sudo(["apt-get", "update"]), capture_output=True)
    base = ["apt-get", "install", "-y"] if pm == "apt" else ["dnf", "install", "-y"]
    cmd = _maybe_sudo(base + list(packages))
    print("    $ " + " ".join(cmd))
    result = subprocess.run(cmd)
    return result.returncode == 0


# --------------------------------------------------------- کامپوننت‌ها

def do_python(dry_run, with_licensing, venv):
    req_files = ["requirements.txt"] + (["requirements-license.txt"] if with_licensing else [])
    missing_req = [r for r in req_files if not os.path.isfile(os.path.join(PROJECT_DIR, r))]
    for r in missing_req:
        print(f"  ⚠️  {r} پیدا نشد، رد شد.")
    req_files = [r for r in req_files if r not in missing_req]
    if not req_files:
        return _fail("هیچ‌کدوم از فایل‌های requirements پیدا نشدن.")

    target_python = sys.executable
    venv_exists = bool(venv) and os.path.isdir(venv)

    if dry_run:
        if venv and not venv_exists:
            _plan(f"ساخت venv: {venv}")
        target_python = _venv_python(venv) if venv else target_python
        for r in req_files:
            _plan(f"{target_python} -m pip install -r {r}")
        return Status.PLANNED

    if venv:
        if not venv_exists:
            print(f"  ساخت venv: {venv}")
            _run_checked([sys.executable, "-m", "venv", venv])
        else:
            print(f"  venv از قبل هست: {venv}")
        target_python = _venv_python(venv)

    for r in req_files:
        print(f"  نصب وابستگی‌ها از {r} ...")
        _run_checked([target_python, "-m", "pip", "install", "-r", os.path.join(PROJECT_DIR, r)])

    _ok("وابستگی‌های پایتون نصب شدن.")
    return Status.DONE


def _venv_python(venv_dir):
    if platform_paths.IS_WINDOWS:
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _run_checked(cmd):
    print("    $ " + " ".join(str(c) for c in cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise InstallError(f"دستور با کد {result.returncode} شکست خورد.")
    return result


def do_teamtalk(dry_run):
    existing = platform_paths.find_native_component("teamtalk")
    if existing:
        _ok(f"TeamTalk SDK از قبل هست: {existing}")
        return Status.OK

    subdir = platform_paths.native_component_subdir("teamtalk")
    name = platform_paths.native_component_names("teamtalk")[0]
    if platform_paths.IS_WINDOWS:
        _manual(
            f"{name} توی پوشه‌ی {subdir}/ نیست. این فایل معمولاً همراه ریپو/بسته تحویل داده "
            "می‌شه و دانلود خودکار نداره -- از بسته‌ی رسمی که تحویل گرفتی کپیش کن، یا از "
            "bearware.dk (http://bearware.dk/teamtalksdk) نسخه‌ی ویندوزِ SDK رو بگیر."
        )
    else:
        _manual(
            f"{name} توی پوشه‌ی {subdir}/ نیست.\n"
            "      از bearware.dk (http://bearware.dk/teamtalksdk) نسخه‌ی لینوکسِ SDK رو "
            "دانلود کن (لایسنس/ثبت‌نامِ خودش رو می‌خواد، دانلود خودکار نداره) و از داخل آرشیو:\n"
            f"          cp /path/to/sdk/Library/TeamTalk_DLL/libTeamTalk5.so {subdir}/"
        )
    return Status.MANUAL


def _install_ffmpeg_from_archive(archive_path):
    with tempfile.TemporaryDirectory(prefix="ttbot_install_") as tmp:
        extracted = _extract_archive(archive_path, os.path.join(tmp, "extracted"))
        name = platform_paths.native_component_names("ffmpeg")[0]
        found = _find_in_tree(extracted, name)
        if not found:
            return None
        dest_dir = os.path.join(PROJECT_DIR, platform_paths.native_component_subdir("ffmpeg"))
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, name)
        shutil.copy2(found, dest_path)
        # ffprobe اختیاریه -- yt-dlp با فقط ffmpeg هم کار می‌کنه، ولی وقتی
        # همون آرشیو رایگان کنارش داره چرا نگیریمش.
        probe_name = "ffprobe.exe" if platform_paths.IS_WINDOWS else "ffprobe"
        probe_found = _find_in_tree(extracted, probe_name)
        if probe_found:
            shutil.copy2(probe_found, os.path.join(dest_dir, probe_name))
        return dest_path


def do_ffmpeg(dry_run):
    if platform_paths.has_ffmpeg():
        _ok(f"ffmpeg از قبل هست: {platform_paths.ffmpeg_binary()}")
        return Status.OK

    if platform_paths.IS_LINUX:
        pm = _package_manager()
        if pm:
            if dry_run:
                _plan(f"نصب ffmpeg با {pm} (fallback: دانلود از BtbN اگه نصب نشد)")
                return Status.PLANNED
            if _package_install(pm, ["ffmpeg"]) and platform_paths.has_ffmpeg():
                _ok("ffmpeg با پکیج‌منیجر نصب شد.")
                return Status.DONE
            print("    پکیج‌منیجر جواب نداد؛ فال‌بک به دانلودِ مستقیم...")
        elif dry_run:
            _plan(f"دانلود ffmpeg از {FFMPEG_URLS['linux']} (پکیج‌منیجری پیدا نشد)")
            return Status.PLANNED
        url = FFMPEG_URLS["linux"]
    else:
        if dry_run:
            _plan(f"دانلود ffmpeg از {FFMPEG_URLS['windows']} و استخراجِ "
                  f"{platform_paths.native_component_names('ffmpeg')[0]} به "
                  f"{platform_paths.native_component_subdir('ffmpeg')}/")
            return Status.PLANNED
        url = FFMPEG_URLS["windows"]

    with tempfile.TemporaryDirectory(prefix="ttbot_install_") as tmp:
        archive = os.path.join(tmp, os.path.basename(url))
        print(f"  دانلود {url} ...")
        _download(url, archive)
        placed = _install_ffmpeg_from_archive(archive)

    if placed and platform_paths.has_ffmpeg():
        _ok(f"ffmpeg نصب شد: {placed}")
        return Status.DONE
    return _fail("دانلود شد ولی ffmpeg هنوز پیدا نمی‌شه؛ مسیر استخراج رو دستی چک کن.")


def _mpv_present():
    if platform_paths.find_native_component("mpv"):
        return True
    import ctypes
    import ctypes.util
    if ctypes.util.find_library("mpv"):
        return True
    for name in platform_paths.mpv_library_names():
        try:
            ctypes.CDLL(name)
            return True
        except OSError:
            continue
    return False


def do_libmpv(dry_run):
    if _mpv_present():
        _ok("libmpv از قبل هست.")
        return Status.OK

    if platform_paths.IS_LINUX:
        pm = _package_manager()
        candidates = ["libmpv2", "libmpv1"] if pm == "apt" else ["mpv-libs"]
        if pm:
            if dry_run:
                _plan(f"نصب libmpv با {pm}: یکی از {', '.join(candidates)}")
                return Status.PLANNED
            for pkg in candidates:
                if _package_install(pm, [pkg]) and _mpv_present():
                    _ok(f"libmpv ({pkg}) نصب شد.")
                    return Status.DONE
        elif dry_run:
            _plan("پکیج‌منیجری (apt/dnf) پیدا نشد؛ نصب libmpv روی لینوکس دانلودِ رسمی و "
                  "قابل‌اعتمادی نداره -- راهنمای دستی چاپ می‌شد.")
            return Status.PLANNED
        _manual(
            "libmpv پیدا نشد. دستی نصب کن:\n"
            "      sudo apt install libmpv2   (یا libmpv1 روی توزیع‌های قدیمی‌تر)\n"
            "      sudo dnf install mpv-libs\n"
            "    یا فایلِ libmpv.so.2 رو از یه بیلدِ رسمیِ mpv بگیر و کنار core/mpv/ بذار."
        )
        return Status.MANUAL

    # ویندوز: دانلودِ بیلدِ dev شینچیرو -- فرمتش 7z است و stdlib نمی‌تونه
    # بازش کنه، پس یه ابزار 7z روی سیستم لازمه (پایین‌تر توضیح داده شده).
    if dry_run:
        _plan("دانلود آخرین mpv-dev-x86_64-*.7z از shinchiro/mpv-winbuild-cmake (GitHub API) و "
              f"استخراجِ {platform_paths.native_component_names('mpv', os_key='windows')[0]} به "
              f"{platform_paths.native_component_subdir('mpv')}/")
        return Status.PLANNED

    try:
        url, asset_name = _resolve_libmpv_windows_url()
    except (InstallError, urllib.error.URLError) as e:
        return _fail(f"پیدا کردنِ آخرین بیلدِ libmpv شکست خورد: {e}")

    name = platform_paths.native_component_names("mpv")[0]
    dest_dir = os.path.join(PROJECT_DIR, platform_paths.native_component_subdir("mpv"))
    with tempfile.TemporaryDirectory(prefix="ttbot_install_") as tmp:
        archive = os.path.join(tmp, asset_name)
        print(f"  دانلود {url} ...")
        _download(url, archive)
        extracted_dir = _extract_7z(archive, os.path.join(tmp, "extracted"))
        if not extracted_dir:
            _manual(
                f"فایل دانلود شد ({asset_name}) ولی هیچ ابزار 7z ای (7z/7za/7zr) روی سیستم "
                f"پیدا نشد که بازش کنه. یا 7-Zip نصب کن و دوباره اجرا کن، یا خودت از "
                f"{url} دانلودش کن، {name} رو از توش دربیار و بذار توی: {dest_dir}"
            )
            return Status.MANUAL
        found = _find_in_tree(extracted_dir, name)
        if not found:
            return _fail(f"{name} توی آرشیوِ استخراج‌شده پیدا نشد.")
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(found, os.path.join(dest_dir, name))

    if _mpv_present():
        _ok(f"libmpv نصب شد: {os.path.join(dest_dir, name)}")
        return Status.DONE
    return _fail("کپی شد ولی libmpv هنوز پیدا نمی‌شه؛ مسیر رو دستی چک کن.")


def do_pulseaudio_utils(dry_run):
    """
    pactl -- لاین‌های صدای لینوکس (core/audio_lines.py) ازش استفاده می‌کنن.
    معادل ویندوزی نداره (اونجا از Virtual Audio Cable استفاده می‌شه)، پس
    اینجا فقط یه no-op موفقه.
    """
    if platform_paths.IS_WINDOWS:
        _ok("لازم نیست (ویندوز به‌جاش از Virtual Audio Cable استفاده می‌کنه).")
        return Status.OK

    if shutil.which("pactl"):
        _ok("pactl از قبل هست.")
        return Status.OK

    pm = _package_manager()
    if pm:
        if dry_run:
            _plan(f"نصب pulseaudio-utils با {pm}")
            return Status.PLANNED
        if _package_install(pm, ["pulseaudio-utils"]) and shutil.which("pactl"):
            _ok("pulseaudio-utils نصب شد.")
            return Status.DONE
    elif dry_run:
        _plan("پکیج‌منیجری (apt/dnf) پیدا نشد؛ راهنمای دستی چاپ می‌شد.")
        return Status.PLANNED

    _manual(
        "pactl پیدا نشد. دستی نصب کن:\n"
        "      sudo apt install pulseaudio-utils\n"
        "      sudo dnf install pulseaudio-utils\n"
        "    بدونش لاین‌های صدا (core/audio_lines.py) کار نمی‌کنن."
    )
    return Status.MANUAL


def do_js_runtime(dry_run):
    current = platform_paths.js_runtime()
    if current:
        kind, cfg = next(iter(current.items()))
        _ok(f"جاوااسکریپت‌رانتایم از قبل هست: {kind} ({cfg['path']})")
        return Status.OK

    os_key = "windows" if platform_paths.IS_WINDOWS else "linux"
    url = DENO_URLS[os_key]
    if dry_run:
        _plan(f"دانلود deno از {url} و کپی به "
              f"{platform_paths.native_component_subdir('deno')}/")
        return Status.PLANNED

    status = _download_and_place("deno", url)
    if status != Status.DONE:
        return status
    if platform_paths.js_runtime():
        return Status.DONE
    return _fail("deno کپی شد ولی js_runtime() هنوز چیزی پیدا نمی‌کنه.")


def do_xray(dry_run):
    if platform_paths.find_native_component("xray") or shutil.which("xray"):
        _ok("xray-core از قبل هست.")
        return Status.OK

    os_key = "windows" if platform_paths.IS_WINDOWS else "linux"
    url = XRAY_URLS[os_key]
    if dry_run:
        _plan(f"دانلود xray-core از {url} و کپی به "
              f"{platform_paths.native_component_subdir('xray')}/")
        return Status.PLANNED
    return _download_and_place("xray", url)


def _download_and_place(component, url):
    name = platform_paths.native_component_names(component)[0]
    dest_dir = os.path.join(PROJECT_DIR, platform_paths.native_component_subdir(component))
    with tempfile.TemporaryDirectory(prefix="ttbot_install_") as tmp:
        archive = os.path.join(tmp, os.path.basename(url))
        print(f"  دانلود {url} ...")
        _download(url, archive)
        if component == "xray":
            try:
                _verify_sha256(archive, url)
            except InstallError as e:
                return _fail(str(e))
        extracted = _extract_archive(archive, os.path.join(tmp, "extracted"))
        found = _find_in_tree(extracted, name)
        if not found:
            return _fail(f"{name} توی آرشیوِ دانلودشده پیدا نشد.")
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, name)
        shutil.copy2(found, dest_path)
        _ensure_native_executable(dest_path)

    if platform_paths.find_native_component(component):
        _ok(f"{component} نصب شد: {dest_path}")
        return Status.DONE
    return _fail(f"{component} کپی شد ولی پیدا نمی‌شه؛ مسیر رو دستی چک کن.")


def do_tesseract(dry_run):
    """
    موتور OCR بررسی خودکار رسید (licensing/receipts.py). اختیاریه: اگه
    نباشه، receipts.extract_text یه پیام روشن برمی‌گردونه و سفارش مستقیم
    می‌ره برای بررسی دستی ادمین -- نصب این کامپوننت هیچ‌وقت شرط بالا اومدنِ
    ربات نیست.
    """
    if platform_paths.has_tesseract():
        _ok(f"tesseract از قبل هست: {platform_paths.tesseract_binary()}")
        return Status.OK

    if platform_paths.IS_LINUX:
        pm = _package_manager()
        # tesseract-ocr-fas: بسته‌ی زبان فارسی -- بدونش رسیدهای فارسی رو
        # عملاً نمی‌خونه (fas+eng توی extract_text لازمش داره).
        packages = (["tesseract-ocr", "tesseract-ocr-fas"] if pm == "apt"
                    else ["tesseract", "tesseract-langpack-fas"])
        if pm:
            if dry_run:
                _plan(f"نصب tesseract با {pm}: {', '.join(packages)}")
                return Status.PLANNED
            if _package_install(pm, packages) and platform_paths.has_tesseract():
                _ok("tesseract نصب شد.")
                return Status.DONE
            print("    پکیج‌منیجر جواب نداد.")
        elif dry_run:
            _plan("پکیج‌منیجری (apt/dnf) پیدا نشد؛ راهنمای دستی چاپ می‌شد.")
            return Status.PLANNED
        _manual(
            "tesseract پیدا نشد. دستی نصب کن:\n"
            "      sudo apt install tesseract-ocr tesseract-ocr-fas\n"
            "      sudo dnf install tesseract tesseract-langpack-fas\n"
            "    بدونش بررسی خودکار رسید (licensing/receipts.py) غیرفعال می‌مونه؛\n"
            "    ربات لایسنس بدون این بالا میاد، فقط این یه فیچرش کار نمی‌کنه."
        )
        return Status.MANUAL

    # ویندوز: نصب‌کننده‌ی رسمیِ UB-Mannheim (NSIS)، سایلنت با /S و مقصد با
    # /D=<مسیر مطلق، بدون اسلش انتهایی و بدون کوتیشن -- محدودیتِ خودِ NSIS>.
    if dry_run:
        _plan("دانلود آخرین tesseract-ocr-w64-setup-*.exe از UB-Mannheim/tesseract "
              f"(GitHub API) و نصبِ سایلنت (/S) به "
              f"{platform_paths.native_component_subdir('tesseract')}/")
        return Status.PLANNED

    try:
        url, asset_name = _resolve_tesseract_windows_url()
    except (InstallError, urllib.error.URLError) as e:
        return _fail(f"پیدا کردنِ آخرین نصب‌کننده‌ی tesseract شکست خورد: {e}")

    dest_dir = os.path.join(PROJECT_DIR, platform_paths.native_component_subdir("tesseract"))
    with tempfile.TemporaryDirectory(prefix="ttbot_install_") as tmp:
        installer = os.path.join(tmp, asset_name)
        print(f"  دانلود {url} ...")
        _download(url, installer)
        os.makedirs(dest_dir, exist_ok=True)
        print(f"  نصبِ سایلنتِ tesseract به {dest_dir} ...")
        result = subprocess.run([installer, "/S", f"/D={dest_dir}"])
        if result.returncode != 0:
            return _fail(f"نصب‌کننده با کد {result.returncode} شکست خورد.")

    if platform_paths.has_tesseract():
        _ok(f"tesseract نصب شد: {platform_paths.tesseract_binary()}")
        return Status.DONE
    return _fail("نصب‌کننده اجرا شد ولی tesseract هنوز پیدا نمی‌شه؛ مسیر رو دستی چک کن.")


COMPONENT_RUNNERS = {
    "teamtalk": lambda dry_run, **_: do_teamtalk(dry_run),
    "ffmpeg": lambda dry_run, **_: do_ffmpeg(dry_run),
    "libmpv": lambda dry_run, **_: do_libmpv(dry_run),
    "pulseaudio_utils": lambda dry_run, **_: do_pulseaudio_utils(dry_run),
    "js_runtime": lambda dry_run, **_: do_js_runtime(dry_run),
    "xray": lambda dry_run, **_: do_xray(dry_run),
    "tesseract": lambda dry_run, **_: do_tesseract(dry_run),
}


def run(components, dry_run, with_licensing, venv):
    results = {}
    for name in components:
        print(f"\n=== {COMPONENT_LABELS.get(name, name)} ===")
        try:
            if name == "python":
                status = do_python(dry_run, with_licensing, venv)
            else:
                status = COMPONENT_RUNNERS[name](dry_run)
        except InstallError as e:
            status = _fail(str(e))
        except Exception as e:  # یه کامپوننتِ خراب نباید کل نصب رو با traceback بترکونه
            status = _fail(f"خطای غیرمنتظره: {e}")
        results[name] = status
    return results


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="نصب یک‌مرحله‌ای همه‌ی نیازمندی‌های ربات (پایتون + باینری‌های نیتیو).")
    parser.add_argument(
        "--components", default=None,
        help=("لیست با کاما از: " + ", ".join(ALL_COMPONENTS) +
              " (پیش‌فرض: " + ", ".join(DEFAULT_COMPONENTS) +
              " -- xray اختیاریه، باید صریح انتخاب بشه)"))
    parser.add_argument("--dry-run", action="store_true",
                        help="فقط پلن رو چاپ کن؛ هیچ دانلود/نصب/تغییری انجام نده.")
    parser.add_argument("--with-licensing", action="store_true",
                        help="requirements-license.txt رو هم (علاوه بر requirements.txt) نصب کن.")
    parser.add_argument(
        "--venv", nargs="?", const=".venv", default=None, metavar="PATH",
        help="وابستگی‌های پایتون رو توی این venv نصب کن (بدون مقدار یعنی .venv کنار پروژه).")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.components:
        requested = [c.strip() for c in args.components.split(",") if c.strip()]
        unknown = [c for c in requested if c not in ALL_COMPONENTS]
        if unknown:
            print(f"کامپوننتِ ناشناس: {', '.join(unknown)}")
            print(f"کامپوننت‌های موجود: {', '.join(ALL_COMPONENTS)}")
            return 2
        components = requested
    else:
        components = list(DEFAULT_COMPONENTS)

    print(f"سیستم‌عامل: {platform_paths.system_name()}")
    print(f"پایتون: {sys.executable} ({sys.version.split()[0]})")
    print("حالت: " + ("--dry-run (فقط پلن، بدون دانلود/نصب واقعی)" if args.dry_run else "نصب واقعی"))

    results = run(components, args.dry_run, args.with_licensing, args.venv)

    print("\n=== خلاصه ===")
    for name, status in results.items():
        print(f"  {COMPONENT_LABELS.get(name, name)}: {STATUS_LABELS[status]}")

    if any(status == Status.FAILED for status in results.values()):
        print("\n⛔ حداقل یه قدم شکست خورد؛ بالا رو ببین.")
        return 1
    if any(status == Status.MANUAL for status in results.values()):
        print("\n⚠️  یکی‌دو قدم نیاز به کار دستی دارن؛ بالا رو ببین.")
    else:
        print("\n✅ تمام.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
