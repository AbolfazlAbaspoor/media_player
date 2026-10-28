import json
import os
import signal
import subprocess
import sys
import threading
import time

# مثل bot.py: جلوگیری از UnicodeEncodeError وقتی خروجی به فایل/پایپ می‌ره.
import warnings

# PyInstaller موقع بالا آمدن یه هشدار deprecation از pkg_resources چاپ
# می‌کنه که ربطی به این برنامه نداره و برای کاربر نهایی فقط نویز و
# نگران‌کننده‌ست. خطاهای واقعی همچنان چاپ می‌شن.
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")


from core.paths import force_utf8_console, get_base_dir
from core import audio_lines
from core import config_defaults
from core import platform_paths

force_utf8_console()

BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
BOT_PY = os.path.join(BASE_DIR, "bot.py")

def _find_all_bots():
    pairs = []
    if not os.path.isdir(DATA_DIR):
        return pairs
    for group_name in sorted(os.listdir(DATA_DIR)):
        # data/licensing مال پلتفرم لایسنسه، نه یه سرور تیم‌تاک. بدون این
        # چک، یه فایل جامونده اون تو باعث می‌شد launcher یه ربات ارواح
        # (بدون آدرس سرور) استارت کنه.
        if not config_defaults.is_server_group_name(group_name):
            continue
        group_dir = os.path.join(DATA_DIR, group_name)
        if not os.path.isfile(os.path.join(group_dir, "shared_config.json")):
            continue
        for bot_name in sorted(os.listdir(group_dir)):
            bot_dir = os.path.join(group_dir, bot_name)
            if os.path.isfile(os.path.join(bot_dir, "identity.json")):
                pairs.append((group_name, bot_name))
    return pairs

def _bot_command(group_name, bot_name):
    """
    دستور اجرای یه ربات — هم در حالت اسکریپت، هم بعد از compile.

    توی بیلد، `sys.executable` خودِ *لانچر*ه و `bot.py` اصلاً وجود نداره
    (داخل باندل فشرده شده). پس نسخه‌ی قبلی عملاً لانچر رو با آرگومانِ یه
    فایلِ ناموجود صدا می‌زد و هیچ رباتی بالا نمی‌اومد -- بدون هیچ پیام
    روشنی. توی بیلد باید فایل اجرایی ربات کنار لانچر صدا زده بشه.
    """
    if getattr(sys, "frozen", False):
        name = "ttbot.exe" if os.name == "nt" else "ttbot"
        exe = os.path.join(BASE_DIR, name)
        if not os.path.isfile(exe):
            raise FileNotFoundError(
                f"فایل اجرایی ربات ({name}) کنار لانچر نیست. "
                "هر دو باید توی یه پوشه باشن.")
        return [exe, group_name, bot_name]
    return [sys.executable, BOT_PY, group_name, bot_name]


def _cleanup_processes(processes, timeout=10):
    """Gracefully terminate all processes with timeout."""
    if not processes:
        return

    # First, try SIGTERM (graceful shutdown)
    for group_name, bot_name, p in processes:
        if p.poll() is None:  # Process still running
            try:
                if hasattr(signal, 'SIGTERM'):
                    p.terminate()
                else:
                    # Windows fallback
                    p.terminate()
            except Exception as e:
                print(f"[Launcher] خطا در متوقف کردن {group_name}/{bot_name}: {e}")

    # Wait for processes to terminate gracefully
    start_time = time.time()
    while time.time() - start_time < timeout:
        still_running = [p for _, _, p in processes if p.poll() is None]
        if not still_running:
            break
        time.sleep(0.1)

    # Force kill any remaining processes (SIGKILL)
    for group_name, bot_name, p in processes:
        if p.poll() is None:
            try:
                p.kill()
                print(f"[Launcher] پروسه {group_name}/{bot_name} با force kill متوقف شد.")
            except Exception as e:
                print(f"[Launcher] خطا در force kill {group_name}/{bot_name}: {e}")

    # Wait for all processes to finish
    for group_name, bot_name, p in processes:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"[Launcher] خطا: {group_name}/{bot_name} هنوز بعد از kill در حال اجرا است.")
        except Exception as e:
            print(f"[Launcher] خطا در wait کردن {group_name}/{bot_name}: {e}")

def _prepare_environment():
    """
    قبل از بالا آوردن ربات‌ها: هم به کاربر بگو چی کم داره، هم لاین‌های صدا
    رو بازسازی کن.

    بازسازی لاین‌ها روی لینوکس حیاتیه: null-sink های پالس‌اودیو با ریبوت یا
    ری‌استارت سرویس صدا از بین می‌رن. بدون این، ربات‌ها بالا میان ولی صدا
    هیچ‌جا نمی‌ره -- یه خرابیِ ساکت که دیباگش سخته.
    """
    print(f"[Launcher] محیط اجرا: {platform_paths.describe_runtime()}")

    for problem in platform_paths.missing_runtime_requirements():
        print(f"[Launcher] هشدار: {problem}")

    try:
        restored = audio_lines.ensure_all_lines()
        if restored:
            print(f"[Launcher] {restored} لاین صدا بعد از ری‌استارت سیستم صدا بازسازی شد.")
    except Exception as e:
        print(f"[Launcher] بازسازی لاین‌های صدا نشد: {e}")


def _configure_proxy_for_license_check():
    """
    پروکسیِ تنظیم‌شدهی مشتری رو **قبل از** چک لایسنس فعال می‌کنه.

    بدون این، چک لایسنس همیشه مستقیم می‌رفت. روی شبکه‌ای که
    workers.dev بلاکه یعنی ربات اصلاً بالا نمی‌اومد -- درست همون
    جایی که README به مشتری قول می‌ده «پروکسی رو توی تنظیمات بذار
    تا چک لایسنس رد نشه».

    دستور proxy خودش پشت امکان cap_proxy قفله، پس مشتری فقط
    از طریق ویزارد/کانفیگ می‌تونه تنظیمش کنه -- و همون هم باید
    کار کنه.
    """
    import json

    if not os.path.isdir(DATA_DIR):
        return
    for group_name in sorted(os.listdir(DATA_DIR)):
        if not config_defaults.is_server_group_name(group_name):
            continue
        shared = os.path.join(DATA_DIR, group_name, "shared_config.json")
        try:
            with open(shared, "r", encoding="utf-8") as f:
                proxy = (json.load(f) or {}).get("proxy") or {}
        except (OSError, ValueError):
            continue
        url = proxy.get("url")
        if proxy.get("enabled") and url:
            from core import proxy_state
            proxy_state.configure(True, url)
            print(f"[License] چک لایسنس از پروکسی رد می‌شه ({group_name}).")
            return


def _license_gate():
    """
    بررسی لایسنس **قبل از هر کار دیگه‌ای**.

    چرا اینجا و نه فقط داخل خود ربات: لانچر نقطه‌ی ورود واقعیه. اگه چک
    فقط داخل ربات باشه، کسی که پروسه‌ی ربات رو مستقیم اجرا کنه یا لانچر
    رو دور بزنه، هیچ‌وقت از این مسیر رد نمی‌شه. چک دوباره داخل ربات هم
    سر جاشه -- این لایه‌ی اوله، نه تنها لایه.

    خروجی: True یعنی اجازه هست.
    """
    from core import license_key

    if not license_key.is_locked():
        # بیلد توسعه: کلید داخل کد نیست، پس چیزی برای راستی‌آزمایی نداریم.
        # این حالت هیچ‌وقت نباید به دست مشتری برسه.
        print("[License] بیلد توسعه (بدون کلید داخلی) — بررسی ریموت رد شد.")
        return True

    api_url = license_key.embedded_api_url()
    if not api_url:
        print("[License] آدرس سرویس لایسنس توی این بیلد تنظیم نشده.")
        return False

    from core import license_remote

    key, identity_username, identity_password = _license_identity()
    if not key:
        print("[License] هیچ کلید لایسنسی توی این نصب تنظیم نشده.")
        print("[License] کلید رو توی data/licensing/rental.json بذار.")
        return False

    # ترتیب مهمه: اول پروکسی، بعد چک.
    _configure_proxy_for_license_check()

    payload = license_remote.check_or_exit(
        key, license_remote.machine_id(), identity_username, identity_password)
    if not payload:
        return False

    # امکاناتِ تأییدشده رو روی دیسک بنویس. بدون این، ربات license.json
    # قدیمی رو می‌خوند و محدودیت اجاره اصلاً اعمال نمی‌شد.
    bot_dirs = [os.path.join(DATA_DIR, group, bot) for group, bot in _find_all_bots()]
    written = license_remote.write_license_files(payload, bot_dirs)
    if written:
        features = payload.get("features")
        scope = "همه‌ی امکانات" if features is None else ", ".join(features)
        print(f"[License] امکانات این لایسنس: {scope}")

    expires_at = payload.get("expires_at")
    if expires_at:
        remaining = max(0, int((float(expires_at) - time.time()) // 86400))
        print(f"[License] معتبر — حدود {remaining} روز باقی‌مانده.")
    else:
        print("[License] معتبر.")
    return True


def _license_identity():
    """(کلید، یوزر، پس) از data/licensing/rental.json."""
    path = os.path.join(DATA_DIR, "licensing", "rental.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None, "", ""
    if not isinstance(data, dict):
        return None, "", ""
    return (str(data.get("key") or "").strip().upper(),
            str(data.get("username") or ""),
            str(data.get("password") or ""))


def main():
    # لایسنس اول از همه: نه لاین صدایی ساخته می‌شه، نه پروسه‌ای بالا میاد.
    if not _license_gate():
        return

    pairs = _find_all_bots()
    if not pairs:
        # توی بیلد، «python bot.py» وجود نداره و این راهنمایی کاربر رو
        # گیج می‌کرد. اسم همون چیزی رو می‌گیم که واقعاً کنارشه.
        first_run = "ttbot.exe" if os.name == "nt" else "./ttbot"
        if not getattr(sys, "frozen", False):
            first_run = "python bot.py"
        print("هیچ رباتی توی data/ پیدا نشد.")
        print(f"اول یه بار «{first_run}» رو از داخل ترمینال اجرا کن تا "
              "اولین سرور/ربات ساخته بشه.")
        # روی سرور (مثلاً Railway) برگشتن از اینجا یعنی «سرویس تموم شد» و
        # دیگه بالا نمیاد. پس به‌جای خروج منتظر می‌مونیم تا یه ربات پیدا بشه.
        print("منتظر ربات می‌مونم (هر ۱۰ ثانیه data/ رو دوباره نگاه می‌کنم). "
              "برای خروج Ctrl+C.")
        try:
            while not pairs:
                time.sleep(10)
                pairs = _find_all_bots()
        except KeyboardInterrupt:
            print("\n[Launcher] بسته شد.")
            return
        print("[Launcher] ربات پیدا شد؛ شروع می‌کنم.")

    _prepare_environment()

    print(f"در حال راه‌اندازی {len(pairs)} ربات (هر کدوم توی پروسه‌ی جدای خودش، بدون قاطی‌شدن):")
    processes = []
    try:
        for group_name, bot_name in pairs:
            print(f"  - {group_name}/{bot_name}")
            # cwd=BASE_DIR لازمه: بعضی مسیرها (و هر پلاگین کاربر که مسیر نسبی
            # استفاده کنه) نسبت به پوشه‌ی کاری حساب می‌شن، پس هر پروسه‌ی ربات
            # باید دقیقاً از پوشه‌ی خودِ پروژه اجرا بشه، نه از جایی که کاربر
            # اتفاقی launcher رو صدا زده.
            p = subprocess.Popen(_bot_command(group_name, bot_name), cwd=BASE_DIR)
            processes.append((group_name, bot_name, p))
            time.sleep(1)

        print("\nهمه‌ی ربات‌ها استارت شدن. با Ctrl+C این launcher رو ببند تا همه‌ی ربات‌ها به‌طور درست بسته بشن.")
        while True:
            time.sleep(5)
            # Check for crashed processes and report them
            for group_name, bot_name, p in processes:
                if p.poll() is not None:
                    print(f"[Launcher] ربات {group_name}/{bot_name} متوقف شد (exit code {p.returncode}).")
    except KeyboardInterrupt:
        print("\n[Launcher] Shutdown سیگنال دریافت شد، در حال متوقف کردن تمام ربات‌ها...")
        _cleanup_processes(processes)
        print("[Launcher] تمام ربات‌ها متوقف شدند.")
    except Exception as e:
        print(f"[Launcher] خطای غیرمنتظره: {e}")
        _cleanup_processes(processes)
        raise

if __name__ == "__main__":
    main()
