"""
سرویس YouTube Music: جستجو و پخش آهنگ از کتابخانه‌ی موسیقیِ یوتیوب.

استفاده:
    w youtubemusic  +  p <اسم آهنگ یا خواننده>
    p https://music.youtube.com/watch?v=...

## فرقش با سرویس youtube چیه

هر دو از یه زیرساخت پخش می‌گیرن، ولی نتیجه‌ی *جستجو* فرق می‌کنه:
ytsearch ویدیوهای عمومی یوتیوب رو می‌ده (کلیپ، ریمیکس، ویدیوی کنسرت)،
درحالی‌که music.youtube.com روی نسخه‌ی رسمیِ آهنگ‌ها تمرکز داره -- برای
«آهنگ گوش دادن» نتیجه‌ی تمیزتری می‌ده.
"""

from core.services._ytdlp_service import YtdlpService


class YouTubeMusic(YtdlpService):
    SERVICE_NAME = "youtubemusic"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("music.youtube.com",)
    AUDIO_ONLY = True
    SEARCH_URL_TEMPLATE = "https://music.youtube.com/search?q={query}"
