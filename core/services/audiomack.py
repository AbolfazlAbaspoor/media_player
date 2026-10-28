"""
سرویس Audiomack: آهنگ و آلبوم، با تمرکز روی هیپ‌هاپ، R&B و آفروبیتس.

استفاده:
    w audiomack  +  p <عبارت>
    p https://audiomack.com/artist/song
    p https://audiomack.com/artist/album/name
"""

from core.services._ytdlp_service import YtdlpService


class Audiomack(YtdlpService):
    SERVICE_NAME = "audiomack"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("audiomack.com",)
    AUDIO_ONLY = True
    SEARCH_URL_TEMPLATE = "https://audiomack.com/search?q={query}"
