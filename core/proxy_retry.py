"""
یه لایه‌ی مشترک برای همه‌ی سرویس‌ها: اگه پروکسی فعاله، اول با پروکسی
امتحان کن؛ اگه fail شد، توی چت خبر بده و بدون پروکسی دوباره امتحان کن؛
اگه اونم fail شد، یه پیام عمومی نهایی توی چت بده و exception اصلی رو
دوباره raise کن (تا caller بتونه پیام خطای خودش رو هم به کاربر بده).

این فقط برای درخواست‌های سطح‌بالا (مثل خودِ search()) استفاده می‌شه، نه
برای هر resolve تک‌آیتمی داخل یه پلی‌لیست -- وگرنه با یه پلی‌لیست بزرگ
ممکنه ده‌ها پیام "پروکسی fail شد" پشت‌سرهم بیاد.
"""

from core import proxy_state
from core import logging_setup
from core import i18n
from core import bot_context
from core import error_reasons


def _notify(key, **kwargs):
    try:
        bot_context.bot.channel_broadcast(i18n.t(key, **kwargs))
    except Exception:
        pass


# خطاهایی که ربطی به مسیر شبکه/پروکسی ندارن: تکرار درخواست بدون پروکسی
# نه‌تنها جواب نمی‌ده، بلکه یه درخواستِ مشکوکِ اضافه به سرویس می‌زنه
# (مخصوصاً وقتی طرف همین الان داره ما رو بات تشخیص می‌ده).
_NON_NETWORK_ERROR_MARKERS = (
    "sign in to confirm",
    "not a bot",
    "confirm you're not a bot",
    "private video",
    "members-only",
    "video unavailable",
    "removed by the uploader",
    "age-restricted",
    "requested format is not available",
    "unsupported url",
    "account has been terminated",
    "copyright",
)


def _is_worth_retrying_without_proxy(exc):
    text = str(exc).lower()
    return not any(marker in text for marker in _NON_NETWORK_ERROR_MARKERS)


def extract_with_fallback(base_opts, target, label="service"):
    """
    base_opts: dict گزینه‌های yt-dlp (بدون کلید 'proxy' -- اگه باشه هم
    نادیده گرفته می‌شه، چون خودمون بر اساس وضعیت زنده‌ی پروکسی تصمیم
    می‌گیریم اضافه‌ش کنیم یا نه).

    نمونه‌ی YoutubeDL از service_pool گرفته می‌شه (نه ساخت‌وسازِ تازه هر
    بار): ساختنِ یه YoutubeDL چیز ارزونی نیست (لودِ ~۱۷۰۰ extractor،
    باز‌کردنِ cookiejar، ساختِ session شبکه) و این تابع دقیقاً روی مسیرِ
    داغِ کاربره (هر `p`/لینکِ پیست‌شده یک‌بار اینجا می‌رسه). با pool، هم
    اون ساخت‌وساز حذف می‌شه هم اتصال HTTP گرم (keep-alive) به یوتیوب/
    سرویس بین درخواست‌های پشت‌سرهمِ همون ترد حفظ می‌مونه.
    """
    from core import service_pool

    opts = dict(base_opts)
    opts.pop("proxy", None)

    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        opts_with_proxy = dict(opts)
        opts_with_proxy["proxy"] = proxy_url
        try:
            ydl = service_pool.get_yt_instance(label, opts_with_proxy)
            return ydl.extract_info(target, download=False)
        except Exception as e:
            # نمونه‌ی همین کلید رو دور می‌ریزیم: اگه خرابی از خودِ حالتِ
            # نگه‌داشته‌شده‌ی نمونه بوده (نه از خودِ لینک)، دفعه‌ی بعد یه
            # نمونه‌ی تازه می‌سازه به‌جای تکرارِ همون خطا برای همه‌ی
            # درخواست‌های بعدی روی همین ترد.
            service_pool.evict(label, opts_with_proxy)
            error_reasons.remember(e)
            logging_setup.log_debug(f"[{label}] proxy attempt failed for '{target}': {e}")
            if not _is_worth_retrying_without_proxy(e):
                # خطا از جنس دسترسی/تشخیص‌بات بود، نه مسیر شبکه: تلاش دوم
                # فقط یه درخواست اضافه‌ی بی‌فایده‌ست.
                logging_setup.log_debug(f"[{label}] not a network error, skipping the no-proxy retry")
                raise
            _notify("proxy_attempt_failed", service=label)

    try:
        ydl = service_pool.get_yt_instance(label, opts)
        return ydl.extract_info(target, download=False)
    except Exception as e:
        service_pool.evict(label, opts)
        error_reasons.remember(e)
        logging_setup.log_debug(f"[{label}] no-proxy attempt failed for '{target}': {e}")
        if proxy_url:
            _notify("all_playback_methods_failed", service=label)
        raise


def extract_pooled(service_name, base_opts, target, label=None):
    """
    همون منطقِ «اول با پروکسی، بعد بدون پروکسی»، ولی روی نمونه‌های
    service_pool و **بی‌صدا** (بدون پیام توی چت).

    این برای resolve کردن تک‌آیتم‌هاست، جایی که extract_with_fallback
    مناسب نیست:

      * بی‌صدا، چون یه پلی‌لیست ۵۰تایی وگرنه ۵۰ تا پیام «پروکسی fail شد»
        پشت‌سرهم توی چت می‌ریخت (همون چیزی که بالای این فایل ازش
        پرهیز شده).
      * ولی *با* fallback، چون قبلاً این مسیر به پروکسی سنجاق شده بود و
        هیچ تلاش دومی نداشت. نتیجه‌ش یه خرابیِ گیج‌کننده بود: سرویس
        **جستجو می‌شد ولی پخش نمی‌شد** -- جستجو fallback داشت و
        resolve نداشت. برای سرویس‌هایی که اصلاً فیلتر نیستن (مثل
        ساندکلاد) عبور از پروکسی خودش خرابی می‌سازه.

    نمونه‌های pool روی اثرانگشتِ options کلید می‌خورن، پس نسخه‌ی
    «با پروکسی» و «بدون پروکسی» دو نمونه‌ی جدا و هر دو کش‌شده‌ان.
    """
    from core import service_pool

    label = label or service_name
    opts = dict(base_opts)
    opts.pop("proxy", None)

    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        opts_with_proxy = dict(opts)
        opts_with_proxy["proxy"] = proxy_url
        try:
            ydl = service_pool.get_yt_instance(service_name, opts_with_proxy)
            return ydl.extract_info(target, download=False)
        except Exception as e:
            service_pool.evict(service_name, opts_with_proxy)
            error_reasons.remember(e)
            logging_setup.log_debug(f"[{label}] pooled proxy attempt failed for '{target}': {e}")
            if not _is_worth_retrying_without_proxy(e):
                raise

    try:
        ydl = service_pool.get_yt_instance(service_name, opts)
        return ydl.extract_info(target, download=False)
    except Exception as e:
        service_pool.evict(service_name, opts)
        error_reasons.remember(e)
        raise
