"""
سرویس Vimeo: فیلم کوتاه، مستند، و کارهای مستقل.

استفاده:
    w vimeo  +  p <عبارت>
    p https://vimeo.com/123456789
"""

from core.services._ytdlp_service import YtdlpService


class Vimeo(YtdlpService):
    SERVICE_NAME = "vimeo"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("vimeo.com",)
    AUDIO_ONLY = False
    SEARCH_URL_TEMPLATE = "https://vimeo.com/search?q={query}"
