"""
سرویس Dailymotion: ویدیو و فیلم.

استفاده:
    w dailymotion  +  p <عبارت>
    p https://www.dailymotion.com/video/xxxxx

yt-dlp برای Dailymotion اکسترکتور جستجو داره، پس نتایج مستقیم و بدون
کلید API میان.
"""

from core.services._ytdlp_service import YtdlpService


class Dailymotion(YtdlpService):
    SERVICE_NAME = "dailymotion"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("dailymotion.com", "dai.ly")
    AUDIO_ONLY = False
    SEARCH_URL_TEMPLATE = "https://www.dailymotion.com/search/{query}/videos"
