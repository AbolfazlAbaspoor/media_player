"""
سرویس اینستاگرام (پست/ریل/IGTV/پروفایل/هشتگ). طبق قانون کلی این پروژه فقط
صدا پخش می‌شه -- حتی ریلز هم فقط صداش.

محدودیت مهم: اینستاگرام سرچ متنی نداره -- نه از راه yt-dlp، نه بدون API
رسمی/لاگین. پس این سرویس فقط لینک مستقیم قبول می‌کنه:
    iru https://www.instagram.com/reel/XXXXXXXXXXX/      -> یه ریل
    iru https://www.instagram.com/p/XXXXXXXXXXX/          -> یه پست
    ir  https://www.instagram.com/username/               -> پست‌های یه پروفایل
    ird #هشتگ                                              -> پست‌های یه هشتگ

کوکی (برای محتوای خصوصی/محدود لازمه): cookies.txt اینستاگرام، مثل یوتیوب --
هر ربات کوکی خودش رو داره (core/cookie_files.py).

## پایه‌ی مشترک

استخراج، کش، صف و رشد تدریجی پروفایل از core/services/_ytdlp_service.py میان.
چیزهایی که مخصوص اینستاگرامه اینجا مونده:
  * search به‌جای None یه ValueError با دلیل می‌ده -- «سرچ متنی نداره» و
    «محتوای خصوصی کوکی لازم داره» راهنمایی‌اند که کاربر باید ببینه.
  * پست‌ها معمولاً عنوان ندارن؛ توضیحات (کوتاه‌شده) جاش می‌شینه.
  * لیست پست‌های یه پروفایل یا هشتگ برای دستورهای کانال و ird.
"""

from core import logging_setup
from core import proxy_retry
from core import track_meta
from core import workers
from core.services._ytdlp_service import YtdlpService

TITLE_MAX = 100


class Instagram(YtdlpService):
    SERVICE_NAME = "instagram"
    SUPPORTS_SEARCH = False
    URL_MARKERS = ("instagram.com",)

    # ------------------------------------------------------------ resolve

    def _resolve_entry(self, entry, interactive=False):
        resolved = super()._resolve_entry(entry, interactive)
        if not resolved or not entry:
            return resolved
        if resolved.get("title") in (None, "", "Unknown"):
            resolved["title"] = entry.get("description") or "Instagram"
        resolved["title"] = str(resolved["title"])[:TITLE_MAX]
        if not resolved.get("channel_url"):
            uploader = entry.get("uploader") or entry.get("uploader_id") or entry.get("channel")
            if uploader:
                resolved["channel_url"] = f"https://www.instagram.com/{uploader}/"
        return resolved

    # ------------------------------------------------------------- search

    def search(self, query):
        query = (query or "").strip()
        if not query:
            raise ValueError("No link given.")
        if not query.startswith(("http://", "https://")) or "instagram.com" not in query.lower():
            raise ValueError("Instagram has no text search -- paste a direct post/reel/profile link.")
        result = super().search(query)
        if not result:
            raise ValueError("Nothing found (private content needs cookies/instagram.txt).")
        return result

    # ------------------------------------------------------- لیست‌گیری

    def _list(self, url, limit, label):
        opts = dict(self._opts(interactive=True))
        opts["extract_flat"] = "in_playlist"
        opts["playlistend"] = limit
        try:
            info = proxy_retry.extract_with_fallback(opts, url, label="instagram")
        except Exception:
            logging_setup.log_exception(label)
            return []
        entries = [e for e in ((info or {}).get("entries") or [])[:limit] if e]
        if not entries:
            return []
        # پروفایل/هشتگ کوتاهه (limit)، پس موازی resolve می‌شه تا همه یک‌جا
        # آماده باشن -- از استخر مشترکِ پروژه، نه یه ThreadPool تازه.
        resolved = [r for r in workers.map_unordered(self._resolve_entry, entries) if r]
        # همه‌شون کامل resolve شدن، پس تاریخِ واقعی دستمونه: نو به کهنه.
        return track_meta.sort_newest_first(resolved)

    def get_channel_all(self, channel_url, limit=20):
        if not channel_url:
            return []
        return self._list(channel_url, limit, f"listing instagram profile '{channel_url}'")

    def get_hashtag_feed(self, hashtag, limit=20):
        hashtag = (hashtag or "").lstrip("#").strip()
        if not hashtag:
            return []
        url = f"https://www.instagram.com/explore/tags/{hashtag}/"
        return self._list(url, limit, f"listing instagram hashtag '#{hashtag}'")
