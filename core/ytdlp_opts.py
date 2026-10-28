"""
نقطه‌ی واحد برای گزینه‌ی js_runtimes در هر جایی که یه دیکشنری گزینه‌ی
yt-dlp مستقیماً (نه از طریق core/services/_ytdlp_service.py::_opts) ساخته
می‌شه.

## چرا لازمه

yt-dlp ۲۰۲۶ بدون یه runtime جاوااسکریپت (deno یا node) برای استخراج
یوتیوب هشدار «No supported JavaScript runtime» می‌ده و ممکنه فرمت/نتیجه‌ی
کمتری برگردونه -- این احتمالاً فقط یوتیوب رو تحت‌تأثیر قرار نمی‌ده، چون
extractorهای زیادی (از جمله بعضی که سرویس‌های دیگه بهشون می‌رسن، مثل
مسیر یوتیوب برای اسپاتیفای) از همون زیرساخت استفاده می‌کنن.

core.platform_paths.js_runtime() مسیر deno/node رو *پیدا می‌کنه*؛ این
ماژول همون نتیجه رو *به گزینه‌های واقعی yt-dlp وصل می‌کنه* -- یه‌بار، نه
کپی‌شده توی هر فایلی که یه YoutubeDL(...) می‌سازه.

بیشتر سرویس‌ها (یوتیوب/ساندکلاد/اینستاگرام/تیک‌تاک/اسپاتیفای/آپارات/
تلوبیون/...) از core/services/_ytdlp_service.py::YtdlpService._opts()
استفاده می‌کنن که خودش این ماژول رو صدا می‌زنه -- برای اون‌ها نیازی به
صدازدن مستقیم این‌جا نیست. جاهایی که یه opts دیکشنری کاملاً مستقل می‌سازن
(مثل core/link_resolver.py::try_ytdlp) باید with_js_runtime رو صریح صدا
بزنن.
"""

from core import platform_paths

# js_runtime() فقط سیستم‌فایل رو چک می‌کنه (deno/node کجاست) -- طیّ عمر
# پروسه عوض نمی‌شه، پس یه‌بار کافیه. تست‌ها با _reset_cache() این کش رو
# پاک می‌کنن تا patch کردن platform_paths.js_runtime اثر کنه.
_cached = None


def _reset_cache():
    """فقط برای تست‌ها: کشِ ماژول رو پاک می‌کنه."""
    global _cached
    _cached = None


def js_runtimes_value():
    """دیکشنریِ js_runtimes (یا خالی اگه هیچ runtime‌ای پیدا نشد)."""
    global _cached
    if _cached is None:
        _cached = platform_paths.js_runtime()
    return dict(_cached)


def with_js_runtime(opts):
    """
    opts رو (in place) با کلید js_runtimes کامل می‌کنه، اگه runtime‌ای
    پیدا شده باشه؛ همون دیکشنری رو برمی‌گردونه تا chain کردن راحت باشه.
    """
    runtimes = js_runtimes_value()
    if runtimes:
        opts["js_runtimes"] = runtimes
    return opts
