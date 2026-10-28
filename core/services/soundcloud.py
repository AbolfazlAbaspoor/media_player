"""
سرویس ساندکلاد: ترک، پلی‌لیست، و **جستجوی متنی**.

استفاده:
    w soundcloud  +  p <هر عبارتی>            -> جستجوی متنی
    p https://soundcloud.com/artist/track       -> یه ترک
    p https://soundcloud.com/artist/sets/name   -> پلی‌لیست
    p https://soundcloud.com/artist             -> همه‌ی ترک‌های یه هنرمند
    sc <link>                                   -> دستور اختصاصی

## جستجو از کجا آمد

yt-dlp یه اکسترکتور به اسم `soundcloud:search` داره که با `scsearchN:` صدا
زده می‌شه -- دقیقاً مثل `ytsearchN:` برای یوتیوب. یعنی برای جستجو نه به API
ساندکلاد نیاز داریم نه به کلید.

## پایه‌ی مشترک

جستجو، resolve کردنِ stub، صف و رشد پلی‌لیست از core/services/_ytdlp_service.py
میان -- که اصلاً از روی همین سرویس ساخته شده بود. تنها چیزی که ساندکلاد رو
ساندکلاد می‌کنه پیشوند جستجو و دامنه‌ست.
"""

from core.services._ytdlp_service import YtdlpService


class SoundCloud(YtdlpService):
    SERVICE_NAME = "soundcloud"
    SUPPORTS_SEARCH = True
    SEARCH_PREFIX = "scsearch"
    URL_MARKERS = ("soundcloud.com",)
    # نتایج جستجو صفحه‌صفحه میان؛ فقط اولی برای شروع پخش، بقیه موقع رشد صف.
    SEARCH_FIRST_COUNT = 1
    # yt-dlp برای صفحه‌ی هنرمند فقط entryهای بی‌تاریخ می‌ده (و ترتیبِ API
    # وسطش آلبوم/ری‌پست قاطی می‌کنه)، پس تاریخِ چندتای اول کامل گرفته می‌شه.
    DATE_PROBE_LIMIT = 8

    def _is_feed(self, info):
        """صفحه‌ی هنرمند (نه set/آلبوم که ترتیبش مال خودشه) فیده."""
        return str((info or {}).get("extractor_key") or "") == "SoundcloudUser"
