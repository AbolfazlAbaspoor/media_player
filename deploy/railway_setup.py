#!/usr/bin/env python3
"""
Guided Railway setup / راهنمای قدم‌به‌قدم راه‌اندازی روی Railway.

    python deploy/railway_setup.py

هر قدم رو خودش انجام می‌ده؛ هر جا نیاز به کار تو باشه، همون‌جا می‌ایسته،
توی کنسول می‌گه چیکار کنی، و بعد از زدن Enter ادامه می‌ده.

قدم‌ها:
    1. چک پایتون و git
    2. گرفتن libTeamTalk5.so (SDK لینوکس) و گذاشتنش توی core/teamtalk/
    3. چک فایل‌های بالای ۱۰۰ مگ (گیت‌هاب قبول نمی‌کنه) و فایل‌های محرمانه
    4. commit و push به گیت‌هاب
    5. ساختن فایل متغیرها (برای paste توی Railway)
    6. راهنمای Railway (Volume، Variables، لاگ)

فقط کتابخانه‌ی استاندارد پایتون لازمه؛ برای باز کردن .7z اگه ابزار 7z
نبود، py7zr رو (با اجازه‌ی تو) نصب می‌کنه.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SO_DEST = os.path.join(PROJECT_DIR, "core", "teamtalk", "libTeamTalk5.so")
VARS_FILE = os.path.join(PROJECT_DIR, "railway-variables.env")

SDK_VERSION = "5.22a"
SDK_FILES = {
    "1": f"tt5sdk_v{SDK_VERSION}_ubuntu22_x86_64.7z",
    "2": f"tt5prosdk_v{SDK_VERSION}_ubuntu22_x86_64.7z",
}
SDK_URL = "https://bearware.dk/teamtalksdk/v{ver}/{name}"

# گیت‌هاب فایل بالای ۱۰۰ مگ رو رد می‌کنه؛ کمی پایین‌تر هشدار می‌دیم.
SIZE_LIMIT = 95 * 1024 * 1024

# چیزهایی که هیچ‌وقت نباید commit بشن.
SECRET_PATTERNS = (
    re.compile(r"(^|/)data/"),
    re.compile(r"(^|/)errors/"),
    re.compile(r"\.key$"),
    re.compile(r"\.sqlite3(-wal|-shm)?$"),
    re.compile(r"(^|/)config\.json$"),
    re.compile(r"(^|/)identity\.json$"),
    re.compile(r"(^|/)rental\.json$"),
    re.compile(r"(^|/)token\.txt$"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"railway-variables\.env$"),
)


# ------------------------------------------------------------- کنسول

def say(en, fa=None):
    print(en)
    if fa:
        print(fa)


def step(number, title_en, title_fa):
    print()
    print("=" * 64)
    print(f"[{number}] {title_en}")
    print(f"    {title_fa}")
    print("=" * 64)


def wait(en="Press Enter when done.", fa="وقتی انجام دادی Enter بزن."):
    print()
    try:
        input(f"{en} / {fa}\n> ")
    except EOFError:
        raise SystemExit("\nstdin closed.")


def ask(en, fa, default=None):
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{en} / {fa}{suffix}\n> ").strip()
    except EOFError:
        raise SystemExit("\nstdin closed.")
    return answer or (default or "")


def yes(en, fa, default=True):
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{en} ({hint})", fa).lower()
    if not answer:
        return default
    return answer in ("y", "yes", "ب", "بله")


def run(cmd, cwd=PROJECT_DIR, check=False):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{result.stdout}\n{result.stderr}".strip())
    return result


# ----------------------------------------------- توابع خالص (قابل‌تست)

def is_linux_x86_64_elf(path):
    """فایل واقعاً یه کتابخانه‌ی لینوکسِ x86-64 هست؟ (نه DLL ویندوز، نه ARM)."""
    try:
        with open(path, "rb") as f:
            header = f.read(20)
    except OSError:
        return False
    # 7f 'ELF'، کلاس ۶۴بیتی (2)، little-endian (1)، e_machine = 0x3E (x86-64)
    return (len(header) >= 20 and header[:4] == b"\x7fELF"
            and header[4] == 2 and header[5] == 1
            and int.from_bytes(header[18:20], "little") == 0x3E)


def find_file(root, filename):
    """اولین فایلی با این اسم زیر root (کمترین عمق، بعد ترتیب الفبایی)."""
    hits = []
    for folder, _dirs, files in os.walk(root):
        if filename in files:
            hits.append(os.path.join(folder, filename))
    hits.sort(key=lambda p: (p.count(os.sep), p))
    return hits[0] if hits else None


def is_secret_path(path):
    path = path.replace("\\", "/")
    return any(p.search(path) for p in SECRET_PATTERNS)


def find_big_files(root, paths, limit=SIZE_LIMIT):
    """[(مسیر نسبی، اندازه)] برای فایل‌های بزرگ‌تر از limit."""
    big = []
    for rel in paths:
        full = os.path.join(root, rel)
        try:
            size = os.path.getsize(full)
        except OSError:
            continue
        if size > limit:
            big.append((rel, size))
    return sorted(big, key=lambda item: -item[1])


def build_variables_text(values):
    """KEY=VALUE برای Raw Editor ریلوی؛ مقدارهای خالی نمی‌یان."""
    lines = [f"{k}={v}" for k, v in values.items() if v]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------- قدم ۱

def check_tools():
    step(1, "Checking Python and git", "چک پایتون و git")
    if sys.version_info < (3, 8):
        raise SystemExit("Python 3.8+ is required / پایتون ۳.۸ یا بالاتر لازمه.")
    if not shutil.which("git"):
        say("git is not installed.", "git نصب نیست.")
        say("Install it from https://git-scm.com/downloads then run this script again.",
            "از https://git-scm.com/downloads نصبش کن و دوباره اسکریپت رو اجرا کن.")
        raise SystemExit(1)
    say("OK.", "درسته.")


# ------------------------------------------------------------- قدم ۲

def _extract_7z(archive, dest):
    """.7z رو باز می‌کنه: اول ابزار 7z، بعد py7zr (با اجازه‌ی کاربر نصب می‌شه)."""
    tool = shutil.which("7z") or shutil.which("7za") or shutil.which("7zr")
    if not tool and os.name == "nt":
        for candidate in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
            if os.path.isfile(candidate):
                tool = candidate
                break
    if tool:
        result = run([tool, "x", "-y", f"-o{dest}", archive])
        if result.returncode == 0:
            return True
        say(f"7z failed: {result.stderr.strip() or result.stdout.strip()}",
            "باز کردن با 7z شکست خورد.")

    try:
        import py7zr  # noqa: F401
    except ImportError:
        if not yes("No 7z tool found. Install the Python package py7zr?",
                   "ابزار 7z پیدا نشد. پکیج پایتونی py7zr رو نصب کنم؟"):
            say("Install 7-Zip (https://www.7-zip.org) and run again.",
                "7-Zip رو نصب کن (https://www.7-zip.org) و دوباره اجرا کن.")
            return False
        result = run([sys.executable, "-m", "pip", "install", "--user", "py7zr"])
        if result.returncode != 0:
            say(f"pip failed:\n{result.stderr.strip()}", "نصب py7zr شکست خورد.")
            return False
        import importlib
        importlib.invalidate_caches()
        import py7zr  # noqa: F811
    try:
        with py7zr.SevenZipFile(archive, "r") as z:
            z.extractall(dest)
        return True
    except Exception as e:  # noqa: BLE001
        say(f"Could not extract: {e}", "باز کردن آرشیو شکست خورد.")
        return False


def _try_download(name, dest_path):
    url = SDK_URL.format(ver=SDK_VERSION, name=name)
    say(f"Trying to download {url}", f"تلاش برای دانلود {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ttbot-railway-setup"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as out:
            shutil.copyfileobj(resp, out)
        return os.path.getsize(dest_path) > 100_000
    except (urllib.error.URLError, OSError, ValueError) as e:
        say(f"Download failed ({e}).", "دانلود خودکار نشد.")
        return False


def _find_downloaded(name):
    """آرشیو دانلودشده‌ی دستی رو توی چند پوشه‌ی رایج می‌گرده."""
    home = os.path.expanduser("~")
    for folder in (PROJECT_DIR, os.getcwd(), os.path.join(home, "Downloads"),
                   os.path.join(home, "Desktop")):
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def get_teamtalk_so():
    step(2, "TeamTalk Linux library (libTeamTalk5.so)",
         "کتابخانه‌ی لینوکسی تیم‌تاک (libTeamTalk5.so)")

    if os.path.isfile(SO_DEST):
        if is_linux_x86_64_elf(SO_DEST):
            say(f"Already in place: {SO_DEST}", "از قبل سر جاشه.")
            return True
        say("A file exists there but it is not a Linux x86-64 library; replacing it.",
            "یه فایل اونجا هست ولی کتابخانه‌ی لینوکس x86-64 نیست؛ عوضش می‌کنم.")

    say("Which SDK edition does your TeamTalk server need?",
        "سرور تیم‌تاکت کدوم SDK رو می‌خواد؟")
    say("  1) standard (tt5sdk)  - normal servers",
        "     ۱) معمولی (tt5sdk) - سرور عادی")
    say("  2) professional (tt5prosdk) - if your server requires encrypted connections",
        "     ۲) حرفه‌ای (tt5prosdk) - اگه سرورت اتصال رمزنگاری‌شده می‌خواد")
    choice = ask("Choose 1 or 2", "۱ یا ۲ رو انتخاب کن", "1")
    name = SDK_FILES.get(choice if choice in SDK_FILES else "1")

    with tempfile.TemporaryDirectory(prefix="tt_sdk_") as tmp:
        archive = _find_downloaded(name)
        if archive:
            say(f"Found {archive}", "آرشیو پیدا شد.")
        else:
            archive = os.path.join(tmp, name)
            if not _try_download(name, archive):
                archive = None

        while not archive:
            say("Please download this file yourself:", "این فایل رو خودت دانلود کن:")
            say(f"    {name}", "")
            say("  from https://bearware.dk/teamtalksdk  (ubuntu22_x86_64 build)",
                "  از https://bearware.dk/teamtalksdk (نسخه‌ی ubuntu22_x86_64)")
            say("Save it in your Downloads folder or in the project folder.",
                "توی پوشه‌ی Downloads یا پوشه‌ی پروژه ذخیره‌ش کن.")
            wait()
            archive = _find_downloaded(name)
            if not archive:
                typed = ask("Not found. Type the full path of the file (or leave empty to retry)",
                            "پیدا نشد. مسیر کامل فایل رو بنویس (یا خالی بذار تا دوباره بگردم)")
                typed = typed.strip('"')
                archive = typed if typed and os.path.isfile(typed) else None

        extracted = os.path.join(tmp, "extracted")
        os.makedirs(extracted, exist_ok=True)
        if not _extract_7z(archive, extracted):
            return False

        found = find_file(extracted, "libTeamTalk5.so")
        if not found:
            say("libTeamTalk5.so was not found inside the archive.",
                "libTeamTalk5.so داخل آرشیو پیدا نشد.")
            return False
        if not is_linux_x86_64_elf(found):
            say("The file is not a Linux x86-64 library (wrong archive?).",
                "این فایل کتابخانه‌ی لینوکس x86-64 نیست (آرشیو اشتباهه؟).")
            return False

        os.makedirs(os.path.dirname(SO_DEST), exist_ok=True)
        shutil.copy2(found, SO_DEST)

    say(f"Installed: {SO_DEST}", "نصب شد.")
    return True


# ------------------------------------------------------------- قدم ۳ و ۴

def _git(*args, check=False):
    return run(["git", *args], check=check)


def _tracked_and_untracked():
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", check=True).stdout
    return [p for p in out.split("\0") if p]


def ensure_repo():
    if not os.path.isdir(os.path.join(PROJECT_DIR, ".git")):
        say("This folder is not a git repository yet; creating one.",
            "این پوشه هنوز ریپوی گیت نیست؛ می‌سازمش.")
        _git("init", check=True)
    _git("branch", "-M", "main")

    # commit به اسم و ایمیل نیاز داره
    if not _git("config", "user.name").stdout.strip():
        _git("config", "user.name", ask("Your name for git commits", "اسمت برای commit‌ها", "ttbot"))
    if not _git("config", "user.email").stdout.strip():
        _git("config", "user.email", ask("Your email for git commits", "ایمیلت برای commit‌ها"))

    remote = _git("remote", "get-url", "origin").stdout.strip()
    if not remote:
        say("Create a PRIVATE repository on GitHub (https://github.com/new), "
            "empty, without README, then paste its address here.",
            "توی گیت‌هاب یه ریپوی خصوصی (Private) و خالی بساز و آدرسش رو اینجا بنویس.")
        while not remote:
            remote = ask("Repository URL (https://github.com/<user>/<repo>.git)", "آدرس ریپو")
        _git("remote", "add", "origin", remote, check=True)
    else:
        say(f"Remote: {remote}", f"ریپوی مقصد: {remote}")
    return remote


def check_size_and_secrets():
    step(3, "Checking for files GitHub would reject, and for secrets",
         "چک فایل‌های بالای ۱۰۰ مگ (گیت‌هاب نمی‌پذیره) و فایل‌های محرمانه")

    while True:
        paths = _tracked_and_untracked()
        secrets = [p for p in paths if is_secret_path(p)]
        big = find_big_files(PROJECT_DIR, paths)
        if not secrets and not big:
            say("Clean: nothing too big, no secrets.", "همه‌چیز تمیزه.")
            return True
        if secrets:
            say("These files look secret and would be uploaded:",
                "این فایل‌ها محرمانه به‌نظر می‌رسن و آپلود می‌شدن:")
            for p in secrets:
                print(f"    {p}")
            say("Remove them from the project folder, or add them to .gitignore.",
                "از پوشه‌ی پروژه بردارشون یا توی .gitignore بنویسشون.")
        if big:
            say("These files are over GitHub's 100 MB limit:",
                "این فایل‌ها از سقف ۱۰۰ مگ گیت‌هاب بزرگ‌ترن:")
            for p, size in big:
                print(f"    {p}  ({size // (1024 * 1024)} MB)")
            say("They are not needed on Railway (Linux installs its own). "
                "Delete them or add them to .gitignore.",
                "روی Railway لازم نیستن (لینوکس خودش نصبشون می‌کنه). پاکشون کن یا به .gitignore اضافه کن.")
        if yes("Add them to .gitignore automatically (they stay on your disk)?",
               "خودکار به .gitignore اضافه‌شون کنم (روی دیسک خودت می‌مونن)؟"):
            ignore_paths(secrets + [p for p, _ in big])
            continue
        wait("Fix it, then press Enter to check again.", "درستش کن، بعد Enter بزن تا دوباره چک کنم.")


def ignore_paths(paths):
    """مسیرها رو به .gitignore اضافه می‌کنه و اگه tracked بودن از ایندکس درمی‌آره."""
    gitignore = os.path.join(PROJECT_DIR, ".gitignore")
    rules = []
    for p in paths:
        p = p.replace("\\", "/")
        rule = "/data/" if p.startswith("data/") else "/" + p
        if rule not in rules:
            rules.append(rule)
    with open(gitignore, "a", encoding="utf-8") as f:
        f.write("\n# added by deploy/railway_setup.py\n" + "\n".join(rules) + "\n")
    for p in paths:
        if _git("ls-files", "--error-unmatch", p).returncode == 0:
            _git("rm", "--cached", "-q", "--", p)


def history_has_big_blobs():
    """اگه تاریخچه‌ی گیت فایل بزرگی داشته باشه، push حتی با حذفش رد می‌شه."""
    if not _git("rev-parse", "--verify", "HEAD").returncode == 0:
        return []
    objects = _git("rev-list", "--objects", "--all").stdout
    names = {}
    for line in objects.splitlines():
        sha, _, path = line.partition(" ")
        names[sha] = path
    if not names:
        return []
    proc = subprocess.run(["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                          cwd=PROJECT_DIR, input="\n".join(names) + "\n",
                          capture_output=True, text=True)
    big = []
    for line in proc.stdout.splitlines():
        sha, kind, size = line.split()
        if kind == "blob" and int(size) > SIZE_LIMIT:
            big.append((names.get(sha, sha), int(size)))
    return big


def commit_and_push():
    ensure_repo()
    if not check_size_and_secrets():
        return False
    step(4, "Commit and push to GitHub", "commit و push به گیت‌هاب")

    _git("add", "-A", check=True)
    staged = _git("diff", "--cached", "--name-only", "-z").stdout.split("\0")
    leaked = [p for p in staged if p and is_secret_path(p)]
    if leaked:
        _git("reset", "-q")
        say("Aborted: secret files were staged: " + ", ".join(leaked),
            "متوقف شد: فایل‌های محرمانه stage شده بودن.")
        return False

    if _git("diff", "--cached", "--quiet").returncode != 0:
        _git("commit", "-m", "Prepare for Railway", check=True)
        say("Committed.", "commit شد.")
    else:
        say("Nothing new to commit.", "چیز جدیدی برای commit نبود.")

    big_history = history_has_big_blobs()
    if big_history:
        say("The git HISTORY contains files over 100 MB; GitHub will reject the push:",
            "تاریخچه‌ی گیت فایل بالای ۱۰۰ مگ داره و گیت‌هاب push رو رد می‌کنه:")
        for p, size in big_history:
            print(f"    {p}  ({size // (1024 * 1024)} MB)")
        say("Easiest fix: delete the .git folder and run this script again "
            "(it will create a fresh history).",
            "ساده‌ترین راه: پوشه‌ی .git رو پاک کن و اسکریپت رو دوباره اجرا کن (تاریخچه‌ی تازه می‌سازه).")
        wait("Press Enter after you did that, or Ctrl+C to quit.",
             "بعد از انجامش Enter بزن یا Ctrl+C.")
        return False

    while True:
        result = _git("push", "-u", "origin", "main")
        if result.returncode == 0:
            say("Pushed.", "push شد.")
            return True
        print(result.stderr.strip() or result.stdout.strip())
        say("Push failed. Common causes: wrong repository address, or GitHub login needed "
            "(a browser window / token prompt may appear; a Personal Access Token "
            "is used instead of a password).",
            "push شکست خورد. علت‌های رایج: آدرس ریپو اشتباهه، یا باید وارد گیت‌هاب بشی "
            "(به‌جای رمز از Personal Access Token استفاده کن).")
        if not yes("Try again?", "دوباره تلاش کنم؟"):
            return False


# ------------------------------------------------------------- قدم ۵ و ۶

def make_variables_file():
    step(5, "Railway variables file", "فایل متغیرهای Railway")
    say("Answer these; they are written to a local file that is NOT uploaded "
        "(ignored by git).",
        "این‌ها رو جواب بده؛ توی یه فایل محلی نوشته می‌شن که آپلود نمی‌شه (توی .gitignore هست).")
    say("Tip: use a NEW token (BotFather > /revoke), not the one from old backups.",
        "پیشنهاد: توکن جدید بگیر (BotFather > /revoke)، نه توکن بکاپ‌های قبلی.")

    values = {
        "LICENSING_BOT_TOKEN": ask("Bot token (from BotFather)", "توکن ربات (از BotFather)"),
        "LICENSING_ADMIN_IDS": ask("Admin numeric Telegram id(s), comma separated",
                                   "آیدی عددی ادمین (چندتا: با ویرگول)"),
        "LICENSING_CARD_NUMBER": ask("Card number (empty to skip)", "شماره کارت (خالی = رد)"),
        "LICENSING_CARD_HOLDER": ask("Card holder name (optional)", "نام صاحب کارت (اختیاری)"),
        "LICENSING_CARD_BANK": ask("Bank name (optional)", "نام بانک (اختیاری)"),
        "LICENSING_SUPPORT_USERNAME": ask("Support username (optional)", "یوزرنیم پشتیبانی (اختیاری)"),
    }
    with open(VARS_FILE, "w", encoding="utf-8") as f:
        f.write(build_variables_text(values))
    say(f"Written: {VARS_FILE}", f"نوشته شد: {VARS_FILE}")
    return VARS_FILE


def railway_guide(vars_file):
    step(6, "Railway dashboard", "داشبورد Railway")
    say("Do these in your browser, one by one. Press Enter after each.",
        "این‌ها رو توی مرورگر انجام بده، یکی‌یکی. بعد از هر کدوم Enter بزن.")

    say("\n(a) Open https://railway.com/new > 'Deploy from GitHub repo' > pick your repo.",
        "\n(الف) https://railway.com/new > Deploy from GitHub repo > ریپوت رو انتخاب کن.")
    say("    The first build starts; it may fail until variables exist - that is fine.",
        "    اولین ساخت شروع می‌شه؛ تا متغیرها نباشن ممکنه خطا بده، اشکال نداره.")
    wait()

    say("\n(b) Volume: open the service > Settings (or right-click the service > "
        "'Attach volume'). Mount path must be exactly:\n        /app/data",
        "\n(ب) Volume: سرویس رو باز کن > Settings (یا راست‌کلیک > Attach volume). "
        "Mount path دقیقاً این باشه:\n        /app/data")
    wait()

    say(f"\n(c) Variables: open the 'Variables' tab > 'Raw Editor' and paste the contents of:\n"
        f"        {vars_file}",
        f"\n(ج) Variables: تب Variables > Raw Editor و محتوای این فایل رو paste کن:\n        {vars_file}")
    say("    Then click 'Update Variables' / Deploy.",
        "    بعد Update Variables / Deploy رو بزن.")
    wait()

    say("\n(d) Open Deployments > View Logs. You should see:\n"
        "        ربات فروش در حال اجراست.   (the sales bot is running)\n"
        "    Then send /start to your bot from the admin account.",
        "\n(د) Deployments > View Logs رو باز کن. باید ببینی:\n"
        "        ربات فروش در حال اجراست.\n"
        "    بعد از حساب ادمین به ربات /start بزن.")
    say("\nIf something fails, copy the log text and send it to me.",
        "\nاگه خطا داد، متن لاگ رو کپی کن و برام بفرست.")


def main():
    os.chdir(PROJECT_DIR)
    print("Railway setup wizard / ویزارد راه‌اندازی Railway")
    check_tools()
    if not get_teamtalk_so():
        say("Cannot continue without libTeamTalk5.so.",
            "بدون libTeamTalk5.so نمی‌شه ادامه داد.")
        return 1
    if not commit_and_push():
        say("Stopped before the push finished. Fix the problem and run again; "
            "finished steps are skipped.",
            "قبل از تموم‌شدن push متوقف شد. مشکل رو درست کن و دوباره اجرا کن؛ قدم‌های انجام‌شده رد می‌شن.")
        return 1
    vars_file = make_variables_file()
    railway_guide(vars_file)
    print("\nDone / تمام.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled / لغو شد.")
        sys.exit(130)
