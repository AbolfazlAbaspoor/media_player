"""
سرویس نماشا (namasha.com): **جستجوی متنی** و پخش لینک ویدیو.

استفاده:
    w namasha  +  p <هر عبارت فارسی>          -> جستجو
    p https://www.namasha.com/v/xxxxxxxx      -> یه ویدیو

## جستجو از کجا میاد

yt-dlp برای نماشا جستجو نداره (صفحه‌های ویدیو با اکسترکتور generic
resolve می‌شن -- تأییدشده: `extractor=generic` با لینک mp4 مستقیم).
ولی خود سایت یه صفحه‌ی جستجوی HTML داره:

    https://www.namasha.com/search?q=<عبارت>

هر نتیجه یه کارت با لینک `/v/<id>`، عنوان (attr `title`)، کانال و
مدت‌زمانه. JSON API ای پیدا نشد، پس همون HTML پارس می‌شه (بدون هیچ
کتابخانه‌ی جدید؛ فقط core.net با همون مسیر پروکسیِ بقیه‌ی سرویس‌ها).
resolve نهایی هم دست اکسترکتور yt-dlp می‌مونه.
"""

import html
import re
import urllib.parse

from core import logging_setup
from core import net
from core.services._farakav import parse_duration
from core.services._ytdlp_service import YtdlpService

SEARCH_URL = "https://www.namasha.com/search?q={query}"

#: هر کارتِ نتیجه تا شروع کارت بعدی.
_CARD_RE = re.compile(
    r'<div class="thumbnail full-width[^"]*"[^>]*>(?P<body>.*?)'
    r'(?=<div class="thumbnail full-width|\Z)', re.S)
_LINK_RE = re.compile(
    r'<a href="(?P<url>https?://(?:www\.)?namasha\.com/v/(?P<id>[\w-]+))"'
    r'[^>]*\btitle="(?P<title>[^"]*)"')
_TIME_RE = re.compile(r'class="time-stamp[^"]*">\s*([^<\s][^<]*?)\s*</span>')
_CHANNEL_RE = re.compile(
    r'<a href="(?P<url>https?://(?:www\.)?namasha\.com/(?!v/)[^"]+)"[^>]*>\s*'
    r'<span class="thumbnail-channel-title">(?P<name>[^<]*)</span>')

# مشترک با تماشا (core/services/_farakav.py)؛ اسم قدیمی برای تست‌ها می‌مونه.
_parse_duration = parse_duration


def parse_search_html(body):
    """کارت‌های صفحه‌ی جستجو -> لیست stub (ترتیبِ صفحه، بدون تکراری)."""
    stubs, seen = [], set()
    for card in _CARD_RE.finditer(body or ""):
        text = card.group("body")
        link = _LINK_RE.search(text)
        if not link or link.group("id") in seen:
            continue
        seen.add(link.group("id"))
        channel = _CHANNEL_RE.search(text)
        time_stamp = _TIME_RE.search(text)
        stubs.append({
            "id": link.group("id"),
            "url": link.group("url"),
            "webpage_url": link.group("url"),
            "title": html.unescape(link.group("title")).strip() or "Unknown",
            "duration": _parse_duration(time_stamp.group(1) if time_stamp else None),
            "uploader": html.unescape(channel.group("name")).strip() if channel else None,
            "channel_url": channel.group("url") if channel else None,
        })
    return stubs


class Namasha(YtdlpService):
    SERVICE_NAME = "namasha"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("namasha.com",)
    # سرویس تصویریه ولی ربات فقط صدا رو به کانال می‌فرسته.
    AUDIO_ONLY = True

    def _search_stubs(self, query, count, interactive=False):
        """
        نتایج جستجوی نماشا به‌صورت stub؛ همون شکلی که yt-dlp برمی‌گردونه،
        پس resolve، صف و رشد پلی‌لیست هیچ فرقی با جستجوی معمولی نمی‌بینن.
        (ترتیبِ مرتبط‌بودنِ خودِ سایت حفظ می‌شه؛ مرتب‌سازی تاریخی نداریم
        چون کارت فقط «۵ سال پیش» داره و resolve تاریخ دقیق رو می‌گیره.)
        """
        try:
            _, body = net.fetch_text(
                SEARCH_URL.format(query=urllib.parse.quote(query)), label="namasha")
        except Exception as e:
            logging_setup.log_debug(f"[namasha] search page failed: {e}")
            return []
        return parse_search_html(body)[:count]
