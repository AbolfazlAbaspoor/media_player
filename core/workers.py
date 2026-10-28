"""
یه استخر ترد (thread pool) مشترک برای همه‌ی کارهای I/O محورِ موازیِ ربات.

چرا لازمه: قبلاً هر جایی که کار موازی داشتیم (resolve کردن آیتم‌های یه
پلی‌لیست توی هر کدوم از ۶ سرویس، و رشد دادن صف سرچ توی bot.py) یه
ThreadPoolExecutor کاملاً جدید ساخته می‌شد. یعنی هر بار سرچ یه پلی‌لیست =
تا ۸ ترد جدید که ساخته می‌شن، چند ثانیه کار می‌کنن و دور ریخته می‌شن. با
چند ربات هم‌زمان روی یه سیستم ضعیف، این ساخت‌وساز مداوم هم CPU می‌خوره هم
RAM (هر ترد استک خودش رو داره).

حالا همه از یه استخر مشترک و محدود استفاده می‌کنن که یه بار ساخته می‌شه و
تردهاش بازیافت می‌شن.

نکته‌ی مهم برای استفاده: کارهایی که به این استخر می‌دی نباید خودشون منتظر
کار دیگه‌ای از همین استخر بمونن (nested submit + wait)، چون با تعداد
محدود ترد می‌تونه به بن‌بست برسه. همه‌ی استفاده‌های فعلی «برگ» هستن
(فقط یه درخواست شبکه می‌زنن و برمی‌گردن).
"""

import atexit
import os
import threading
from concurrent.futures import ThreadPoolExecutor

# سقف تردها: به تعداد هسته‌ها گره خورده ولی هیچ‌وقت خیلی بزرگ نمی‌شه.
# این کارها همه I/O محورن (منتظر شبکه)، پس بیشتر از هسته‌ها ترد داشتن
# منطقیه؛ ولی روی یه سیستم ضعیف که چند ربات هم روش اجرا می‌شه، سقف ۸
# جلوی انفجار تعداد تردها رو می‌گیره.
# سقف عمداً پایین نگه داشته شده: بیشترِ کارهای این استخر، درخواست به
# سرویس‌های بیرونی (یوتیوب و ...) هستن. ۸ درخواست هم‌زمان از یه IP دقیقاً
# همون الگوییه که سرویس‌ها به‌عنوان scraper علامت‌گذاری می‌کنن؛ ۴ تا هم
# موازی‌سازی مفید رو حفظ می‌کنه هم ردپا رو طبیعی‌تر نگه می‌داره.
MAX_WORKERS = max(2, min(4, (os.cpu_count() or 2) * 2))

_pool = None
_pool_lock = threading.Lock()


def pool():
    """استخر مشترک؛ اولین بار که لازم بشه ساخته می‌شه (نه موقع import)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(
                    max_workers=MAX_WORKERS,
                    thread_name_prefix="cp-io",
                )
                atexit.register(shutdown)
    return _pool


def map_unordered(fn, items, max_workers=None):
    """
    مثل executor.map: fn رو روی همه‌ی آیتم‌ها موازی اجرا می‌کنه و نتیجه‌ها
    رو *به همون ترتیب ورودی* برمی‌گردونه (لیست، نه iterator).

    max_workers اینجا فقط برای سازگاری با کد قبلیه؛ سقف واقعی همون
    MAX_WORKERS استخر مشترکه.
    """
    items = list(items)
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    return list(pool().map(fn, items))


def submit(fn, *args, **kwargs):
    """یه کار پس‌زمینه به استخر مشترک می‌ده و Future برمی‌گردونه."""
    return pool().submit(fn, *args, **kwargs)


def shutdown(wait=True):
    """Gracefully shutdown the worker pool. wait=True to wait for pending tasks."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.shutdown(wait=wait)
            except Exception:
                pass
            finally:
                _pool = None
