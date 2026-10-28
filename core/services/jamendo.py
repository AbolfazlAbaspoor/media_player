"""
سرویس Jamendo: موسیقی رایگان و با مجوز Creative Commons.

استفاده:
    w jamendo  +  p <عبارت>
    p https://www.jamendo.com/track/...

چرا مهمه: آهنگ‌های این‌جا مجوز پخش عمومی دارن، پس برای پخش توی یه
کانالِ عمومی از نظر کپی‌رایت امن‌ترین انتخابن.
"""

from core.services._ytdlp_service import YtdlpService


class Jamendo(YtdlpService):
    SERVICE_NAME = "jamendo"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("jamendo.com",)
    AUDIO_ONLY = True
    SEARCH_URL_TEMPLATE = "https://www.jamendo.com/search?q={query}"
