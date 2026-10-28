"""
یه زمان‌بند تک‌تردی و خیلی سبک برای کارهای تأخیردار.

چرا لازمه: قبلاً هر کاری که باید بعداً انجام می‌شد (مثلاً «این فایل رو ۲۴
ساعت دیگه پاک کن» توی دستور dl) با threading.Timer ساخته می‌شد. هر Timer
یه ترد واقعی سیستم‌عامله که تمام مدت فقط خوابیده -- برای یه ربات که قراره
روی ضعیف‌ترین سیستم‌ها و چندتایی اجرا بشه، ده‌ها ترد خوابیده بابت هیچی.

اینجا فقط *یک* ترد وجود داره که هر چند ثانیه بیدار می‌شه، کارهای سررسیده
رو انجام می‌ده و دوباره می‌خوابه. هزینه‌ش تقریباً صفره.
"""

import heapq
import itertools
import threading
import time

from core import logging_setup

# فاصله‌ی بیدار شدن. کارهای این ربات همه در مقیاس دقیقه/ساعتن، پس دقت
# چند ثانیه‌ای کاملاً کافیه و بیدار شدن نادر یعنی مصرف CPU نزدیک صفر.
TICK_SECONDS = 5.0

_heap = []
_counter = itertools.count()
_lock = threading.Lock()
_wakeup = threading.Event()
_thread = None


def schedule(delay_seconds, func, *args, **kwargs):
    """
    func رو بعد از delay_seconds ثانیه (تقریبی) اجرا می‌کنه.
    اگه delay_seconds صفر یا منفی باشه، همون تیک بعدی اجرا می‌شه.
    یه شناسه برمی‌گردونه که می‌شه باهاش cancel کرد.
    """
    run_at = time.monotonic() + max(0.0, delay_seconds)
    task_id = next(_counter)
    with _lock:
        heapq.heappush(_heap, (run_at, task_id, func, args, kwargs))
    _ensure_running()
    _wakeup.set()
    return task_id


def cancel(task_id):
    """اگه هنوز اجرا نشده، از صف حذفش می‌کنه. True یعنی پیدا و حذف شد."""
    with _lock:
        for i, item in enumerate(_heap):
            if item[1] == task_id:
                _heap[i] = _heap[-1]
                _heap.pop()
                heapq.heapify(_heap)
                return True
    return False


def pending_count():
    with _lock:
        return len(_heap)


def _ensure_running():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_run, name="cp-scheduler", daemon=True)
        _thread.start()


def _run():
    while True:
        now = time.monotonic()
        due = []
        with _lock:
            while _heap and _heap[0][0] <= now:
                due.append(heapq.heappop(_heap))
            next_at = _heap[0][0] if _heap else None

        for _, _, func, args, kwargs in due:
            try:
                func(*args, **kwargs)
            except Exception:
                logging_setup.log_exception("running a scheduled task")

        # تا کار بعدی می‌خوابیم (ولی حداکثر یه تیک، تا schedule جدید هم
        # زود دیده بشه). Event یعنی اگه کار جدیدی اضافه شد، فوراً بیدار
        # می‌شیم، نه بعد از تموم شدن خواب.
        if next_at is None:
            timeout = TICK_SECONDS
        else:
            timeout = max(0.0, min(TICK_SECONDS, next_at - time.monotonic()))
        _wakeup.wait(timeout)
        _wakeup.clear()
