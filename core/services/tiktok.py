"""
سرویس TikTok: فقط لینک مستقیم (یه ویدیو، لینک کوتاه، یا صفحه‌ی یه کاربر).

استفاده:
    tk https://www.tiktok.com/@username/video/XXXXXXXXX    -> یه ویدیو
    tk https://vm.tiktok.com/XXXXXXXXX                       -> لینک کوتاه

جستجوی متنی نداره (TikTok بدون API سرچ نمی‌ده)، پس توی چرخه‌ی w/p نیست و
فقط از دستور tk در دسترسه.

روی پایه‌ی مشترک (core/services/_ytdlp_service.py) است؛ از قبلِ اون فقط
این سه تا تفاوت مونده: User-Agent مرورگر (TikTok بدونش جواب نمی‌ده)،
پذیرفتن لینک بدون http، و اسم جایگزین وقتی ویدیو عنوان نداره.
"""

from core.services._ytdlp_service import YtdlpService


class TikTok(YtdlpService):
    SERVICE_NAME = "tiktok"
    SUPPORTS_SEARCH = False
    URL_MARKERS = ("tiktok.com",)
    EXTRA_OPTS = {
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
    }

    def search(self, query):
        if not isinstance(query, str) or "tiktok.com" not in query.lower():
            return None
        query = query.strip()
        if not query.startswith(("http://", "https://")):
            query = "https://" + query
        return super().search(query)

    def _resolve_entry(self, entry, interactive=False):
        resolved = super()._resolve_entry(entry, interactive)
        if resolved and resolved.get("title") in (None, "", "Unknown") and entry:
            uploader = entry.get("uploader") or entry.get("creator")
            if uploader:
                resolved["title"] = f"TikTok by {uploader}"
        return resolved
