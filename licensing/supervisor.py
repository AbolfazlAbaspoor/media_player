"""
اجرا و نگه‌داشتن پروسه‌های ربات روی سرور.

هر نمونه یه پروسه‌ی جدای `python bot.py <group> <bot>` است -- دقیقاً همون
کاری که launcher.py می‌کرد، ولی این‌جا از روی دیتابیس لایسنس تصمیم گرفته
می‌شه که کی باید بالا باشه، نه از روی محتوای پوشه‌ی data/.

## تفاوت مهم با launcher.py

launcher هر چیزی که توی data/ باشه رو استارت می‌کنه. سوپروایزر فقط
`db.runnable_instances()` رو استارت می‌کنه -- یعنی لایسنسِ فعال. نتیجه:
لحظه‌ای که یه لایسنس منقضی/معلق می‌شه، ربات دیگه بالا نمی‌آد، حتی اگه
فایل‌هاش هنوز روی دیسک باشن.

## ری‌استارت با backoff

ربات ممکنه به دلایل موقتی بیفته (قطعی شبکه، ری‌استارت سرور تیم‌تاک). بدون
backoff، یه ربات با کانفیگ غلط می‌تونه هزار بار در دقیقه استارت بشه و
سرور رو بخوابونه. پس فاصله‌ی ری‌استارت با هر شکستِ پشت‌سرهم دوبرابر می‌شه،
تا سقف RESTART_BACKOFF_MAX.

نکته: خروج با کد ۳ یعنی «خود ربات گفت لایسنس اجازه نمی‌ده» (توی bot.py).
اون‌موقع ری‌استارت بی‌فایده‌ست و نمونه `blocked` علامت می‌خوره.
"""

import os
import subprocess
import sys
import threading
import time

from core import audio_lines
from core import logging_setup
from core.paths import get_base_dir
from licensing import provisioning

BASE_DIR = get_base_dir()
BOT_PY = os.path.join(BASE_DIR, "bot.py")

RESTART_BACKOFF_START = 5
RESTART_BACKOFF_MAX = 600
# کد خروجی‌ای که bot.py وقتی لایسنس اجازه نمی‌ده برمی‌گردونه.
EXIT_LICENSE_BLOCKED = 3
# چند ثانیه بین استارت ربات‌ها فاصله بذاریم تا هم‌زمان به سرور تیم‌تاک
# هجوم نبرن (سرورها معمولاً روی لاگین پشت‌سرهم rate-limit دارن).
STAGGER_SECONDS = 1.0


class _Managed:
    __slots__ = ("slug", "instance_id", "process", "failures", "next_start_at",
                 "blocked", "last_exit_code", "started_at")

    def __init__(self, slug, instance_id):
        self.slug = slug
        self.instance_id = instance_id
        self.process = None
        self.failures = 0
        self.next_start_at = 0.0
        self.blocked = False
        self.last_exit_code = None
        self.started_at = None

    def is_alive(self):
        return self.process is not None and self.process.poll() is None


class Supervisor:
    def __init__(self, db, poll_interval=10):
        self.db = db
        self.poll_interval = poll_interval
        self._managed = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None

    # ------------------------------------------------------------ چرخه

    def start(self):
        """حلقه‌ی نگهبانی رو توی یه ترد پس‌زمینه اجرا می‌کنه."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="supervisor", daemon=True)
        self._thread.start()

    def shutdown(self, timeout=20):
        """
        همه‌ی ربات‌ها رو مرتب می‌بنده -- ولی وضعیتِ دیتابیس رو 'stopped'
        نمی‌کنه (persist_stopped=False).

        باگ قبلی: این متد موقع بستنِ خودِ سرور (Ctrl+C / ری‌استارت) صدا زده
        می‌شه، نه فقط وقتی یه ادمین صریحاً یه ربات رو خاموش می‌کنه. قبلاً هر
        دو حالت یکی بودن، یعنی بستنِ سرور همه‌ی نمونه‌ها رو 'stopped' علامت
        می‌زد -- و runnable_instances() فقط 'created'/'running'/'crashed'
        رو برمی‌گردونه، پس دفعه‌ی بعد که سرور بالا می‌اومد سوپروایزر هیچ
        ربانی نمی‌دید که استارتش کنه؛ باید از تلگرام دستی استارت می‌شدن.
        الان وضعیت دست‌نخورده می‌مونه (همون 'running' قبلی)، پس دفعه‌ی بعد
        همون لیست runnable دوباره واقعاً runnable حساب می‌شه.
        """
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            slugs = list(self._managed)
        for slug in slugs:
            self.stop(slug, timeout=timeout, persist_stopped=False)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self.reconcile()
            except Exception:
                logging_setup.log_exception("supervisor reconcile")
            self._stop_event.wait(self.poll_interval)

    # ----------------------------------------------------------- منطق

    def reconcile(self):
        """
        وضعیت واقعی رو با وضعیت مطلوب (دیتابیس) هم‌تراز می‌کنه: چیزهایی که
        باید بالا باشن و نیستن استارت می‌شن، چیزهایی که نباید باشن خاموش.
        """
        wanted = {}
        for row in self.db.runnable_instances():
            wanted[row["slug"]] = row

        with self._lock:
            running = set(self._managed)

        # آنچه نباید باشه
        for slug in running - set(wanted):
            self.stop(slug)

        # آنچه باید باشه
        now = time.time()
        started_this_round = 0
        for slug, row in wanted.items():
            with self._lock:
                managed = self._managed.get(slug)

            if managed is not None and managed.is_alive():
                continue

            if managed is not None:
                self._collect_exit(managed)
                if managed.blocked:
                    continue
                if now < managed.next_start_at:
                    continue

            if started_this_round and STAGGER_SECONDS:
                time.sleep(STAGGER_SECONDS)
            self.start_instance(row)
            started_this_round += 1

    def _collect_exit(self, managed):
        """
        کد خروجیِ یه پروسه‌ی تموم‌شده رو ثبت می‌کنه و backoff بعدی رو حساب
        می‌کنه.
        """
        if managed.process is None:
            return
        code = managed.process.poll()
        if code is None:
            return
        if managed.last_exit_code == code and managed.process is None:
            return

        managed.last_exit_code = code
        managed.process = None

        if code == EXIT_LICENSE_BLOCKED:
            managed.blocked = True
            self.db.update_instance(managed.instance_id, status="blocked",
                                    pid=None, last_exit_code=code)
            self.db.log_event("instance_blocked", detail={"slug": managed.slug})
            logging_setup.log_warning(
                f"bot {managed.slug} refused to start because of its licence; giving up",
                context="supervisor")
            return

        if code == 0:
            managed.failures = 0
            managed.next_start_at = time.time() + RESTART_BACKOFF_START
        else:
            managed.failures += 1
            delay = min(RESTART_BACKOFF_MAX,
                        RESTART_BACKOFF_START * (2 ** (managed.failures - 1)))
            managed.next_start_at = time.time() + delay
            logging_setup.log_warning(
                f"bot {managed.slug} exited with code {code} "
                f"({managed.failures} consecutive failures); retrying in {int(delay)}s",
                context="supervisor")

        self.db.update_instance(managed.instance_id, status="crashed" if code else "stopped",
                                pid=None, last_exit_code=code)

    def start_instance(self, instance_row):
        """
        یه نمونه رو استارت می‌کنه. قبلش مطمئن می‌شه لاین صداش زنده‌ست --
        بعد از ریبوت سرور، null-sink ها از بین رفتن و بدون این کار ربات
        بالا می‌آمد ولی صداش هیچ‌جا نمی‌رفت.
        """
        slug = instance_row["slug"]
        group_dir, bot_dir = provisioning.instance_dirs(instance_row)
        group_name = os.path.basename(group_dir)
        bot_name = os.path.basename(bot_dir)

        if not os.path.isfile(os.path.join(bot_dir, "identity.json")):
            logging_setup.log_warning(
                f"bot {slug} did not start: {bot_dir} has no configuration", context="supervisor")
            self.db.update_instance(int(instance_row["id"]), status="missing")
            return None

        try:
            if instance_row["audio_line"]:
                audio_lines.ensure_line(instance_row["audio_line"])
        except Exception:
            logging_setup.log_exception(f"ensuring audio line for {slug}")

        with self._lock:
            managed = self._managed.get(slug)
            if managed is None:
                managed = _Managed(slug, int(instance_row["id"]))
                self._managed[slug] = managed
            if managed.is_alive():
                return managed.process

            try:
                # cwd=BASE_DIR لازمه: مسیرهای نسبی (پلاگین‌ها، کوکی‌ها) نسبت
                # به پوشه‌ی پروژه حساب می‌شن، نه جایی که سوپروایزر از اونجا
                # اجرا شده.
                managed.process = subprocess.Popen(
                    [sys.executable, BOT_PY, group_name, bot_name],
                    cwd=BASE_DIR,
                    stdin=subprocess.DEVNULL,
                )
            except OSError as e:
                logging_setup.log_exception(f"starting instance {slug}")
                managed.failures += 1
                managed.next_start_at = time.time() + min(
                    RESTART_BACKOFF_MAX, RESTART_BACKOFF_START * (2 ** (managed.failures - 1)))
                self.db.update_instance(int(instance_row["id"]), status="crashed")
                self.db.log_event("instance_start_failed",
                                  detail={"slug": slug, "error": str(e)})
                return None

            managed.started_at = time.time()
            managed.blocked = False

        self.db.update_instance(int(instance_row["id"]), status="running",
                                pid=managed.process.pid,
                                last_started_at=int(time.time()))
        self.db.log_event("instance_started", detail={"slug": slug, "pid": managed.process.pid})
        return managed.process

    def stop(self, slug, timeout=20, persist_stopped=True):
        """
        یه نمونه رو مرتب می‌بنده (اول terminate، بعد kill). True یعنی واقعاً
        یه پروسه‌ی در حال اجرا بسته شد.

        persist_stopped=False فقط توسط shutdown() استفاده می‌شه: پروسه
        واقعاً بسته می‌شه ولی وضعیتِ دیتابیس دست‌نخورده می‌مونه (توضیح
        کامل بالای shutdown()).
        """
        with self._lock:
            managed = self._managed.pop(slug, None)

        if managed is None:
            return False

        process = managed.process
        if process is None or process.poll() is not None:
            if persist_stopped:
                self.db.update_instance(managed.instance_id, status="stopped", pid=None)
            return False

        try:
            process.terminate()
        except Exception:
            pass

        deadline = time.time() + timeout
        while time.time() < deadline and process.poll() is None:
            time.sleep(0.2)

        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=5)
            except Exception:
                logging_setup.log_exception(f"force killing {slug}")

        if persist_stopped:
            self.db.update_instance(managed.instance_id, status="stopped", pid=None,
                                    last_exit_code=process.returncode)
            self.db.log_event("instance_stopped", detail={"slug": slug})
        return True

    def restart(self, slug):
        row = self.db.get_instance_by_slug(slug)
        if row is None:
            return False
        self.stop(slug)
        with self._lock:
            self._managed.pop(slug, None)
        return self.start_instance(row) is not None

    # ----------------------------------------------------------- وضعیت

    def status(self):
        """[{slug, alive, pid, failures, blocked, uptime_seconds}]"""
        with self._lock:
            managed_items = list(self._managed.values())

        now = time.time()
        result = []
        for managed in managed_items:
            alive = managed.is_alive()
            result.append({
                "slug": managed.slug,
                "alive": alive,
                "pid": managed.process.pid if alive else None,
                "failures": managed.failures,
                "blocked": managed.blocked,
                "last_exit_code": managed.last_exit_code,
                "uptime_seconds": int(now - managed.started_at) if alive and managed.started_at else 0,
            })
        return sorted(result, key=lambda item: item["slug"])

    def is_running(self, slug):
        with self._lock:
            managed = self._managed.get(slug)
        return managed is not None and managed.is_alive()
