"""
سرویس آپ‌میوزیک (upmusics.com): **جستجوی متنی** و پخش آهنگ ایرانی.

استفاده:
    w upmusics  +  p <نام خواننده یا آهنگ>     -> جستجو
    p https://upmusics.com/<نام-پست>/          -> یه آهنگ

جستجو از `/search/<عبارت>` (HTML) میاد و mp3 مستقیم از صفحه‌ی پست برداشته
می‌شه؛ همه‌ی منطقش توی core/services/_wp_music.py مشترکه. فایل‌ها (۳۲۰ کیلوبیت)
از irsv.upmusics.com میان و یه-دو ریدایرکت می‌خورن که mpv دنبال می‌کنه.
"""

from core.services._wp_music import WpMusicService


class UpMusics(WpMusicService):
    SERVICE_NAME = "upmusics"
    HOST = "upmusics.com"
    URL_MARKERS = (HOST,)
    SEARCH_URL = "https://upmusics.com/search/{query}"
    # سایدبارِ سایت هم تیتر h2 داره؛ فقط کارت‌های نتیجه.
    CARD_MARKER = '<article class="upsng"'
