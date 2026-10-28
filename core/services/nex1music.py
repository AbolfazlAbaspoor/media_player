"""
سرویس نکس‌وان‌میوزیک (nex1music.com): **جستجوی متنی** و پخش آهنگ ایرانی.

استفاده:
    w nex1music  +  p <نام خواننده یا آهنگ>    -> جستجو
    p https://nex1music.com/<نام-پست>/         -> یه آهنگ

دامنه‌ی nex1music.ir از این شبکه فیلتره؛ nex1music.com (همون سایت) باز
می‌شه. جستجو از `/?s=<عبارت>` میاد و mp3 (۳۲۰/۱۲۸/۶۴) از صفحه‌ی پست؛ منطقش
توی core/services/_wp_music.py مشترکه.
"""

from core.services._wp_music import WpMusicService


class Nex1Music(WpMusicService):
    SERVICE_NAME = "nex1music"
    HOST = "nex1music.com"
    URL_MARKERS = (HOST,)
    SEARCH_URL = "https://nex1music.com/?s={query}"
    # سایدبارِ سایت هم تیتر h2 داره؛ فقط کارت‌های نتیجه.
    CARD_MARKER = '<div class="post anm"'
