"""
سرویس رزموزیک (rozmusic.com): **جستجوی متنی** و پخش آهنگ ایرانی.

استفاده:
    w rozmusic  +  p <نام خواننده یا آهنگ>     -> جستجو
    p https://rozmusic.com/<نام-پست>.html      -> یه آهنگ

جستجو از `/?s=<عبارت>` میاد و mp3 (اصلی و ۱۲۸) از صفحه‌ی پست؛ منطقش توی
core/services/_wp_music.py مشترکه.
"""

from core.services._wp_music import WpMusicService


class RozMusic(WpMusicService):
    SERVICE_NAME = "rozmusic"
    HOST = "rozmusic.com"
    URL_MARKERS = (HOST,)
    SEARCH_URL = "https://rozmusic.com/?s={query}"
    # سایدبارِ سایت هم تیتر h2 داره؛ فقط کارت‌های نتیجه.
    CARD_MARKER = '<article class="box_right post"'
