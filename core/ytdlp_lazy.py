"""
دسترسیِ تنبلِ yt-dlp.

import کردنِ yt_dlp حدود ۱ ثانیه و ~۳۰ مگابایت رم می‌خوره (کلِ extractorها و
Cryptodome و websockets). ربات‌ی که بیکاره و هنوز هیچ لینکی resolve نکرده نباید
این هزینه رو بده؛ با هزاران پروسه‌ی ربات روی یه سرور این تفاوت جدیه. پس همه‌ی
جاهایی که قبلاً `from yt_dlp import ...` سطحِ ماژول داشتن از اینجا رد می‌شن و
import واقعی فقط اولین باری که واقعاً لازمه انجام می‌شه (بعدش کش sys.modules).
"""


def YoutubeDL(*args, **kwargs):
    """همون yt_dlp.YoutubeDL؛ با `with YoutubeDL(opts) as ydl:` هم کار می‌کنه."""
    from yt_dlp import YoutubeDL as _YoutubeDL
    return _YoutubeDL(*args, **kwargs)


def Request(*args, **kwargs):
    """همون yt_dlp.networking.Request."""
    from yt_dlp.networking import Request as _Request
    return _Request(*args, **kwargs)


def download_error():
    """کلاسِ DownloadError برای `except ytdlp_lazy.download_error():`؛ فقط
    وقتی استثنا واقعاً پرتاب شده ارزیابی می‌شه، پس import زودهنگام نداریم."""
    from yt_dlp.utils import DownloadError
    return DownloadError


def download_cancelled():
    """
    کلاسِ DownloadCancelled؛ برای متوقف‌کردنِ تمیزِ یه دانلودِ در جریان از
    داخلِ progress_hook (raise کردنِ همین کلاس) -- core/live_dvr.py وقتی
    سقفِ حجم/زمانِ بافر رد بشه یا کاربر صریحاً بخواد متوقفش کنه از همین
    استفاده می‌کنه، به‌جای یه استثنای عمومی که ممکن بود خودِ yt-dlp خطا
    حساب کنه و توی لاگ raise کنه.
    """
    from yt_dlp.utils import DownloadCancelled
    return DownloadCancelled
