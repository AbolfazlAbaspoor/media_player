"""
سرویس تماشا (tamasha.com): **جستجوی متنی** و پخش لینک ویدیو.

استفاده:
    w tamasha  +  p <هر عبارت فارسی>          -> جستجو
    p https://tamasha.com/v/xxxxx             -> یه ویدیو

## جستجو از کجا میاد

تماشا (سرویس اشتراک ویدیوی فراکاو) هم‌خانواده‌ی نماشاست، ولی دامنه و قالبِ
صفحه‌ش فرق داره. yt-dlp براش جستجو نداره (صفحه‌ی ویدیو با اکسترکتور html5
resolve می‌شه و یه استریم HLS می‌ده -- تأییدشده). خودِ سایت صفحه‌ی جستجوی
HTML داره:

    https://tamasha.com/search?query=<عبارت>

(توجه: پارامتر `query` است نه `q`؛ با `q` سایت جستجو رو نادیده می‌گیره و
صفحه‌ی اصلی می‌ده.) هر نتیجه یه کارت با لینک `/v/<id>`، عنوان (attr `title`)،
مدت‌زمان و کانال است. resolve نهایی دست اکسترکتور yt-dlp می‌مونه.
"""

import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from core import logging_setup
from core import net
from core.services._farakav import parse_duration
from core.services._ytdlp_service import YtdlpService

SEARCH_URL = "https://tamasha.com/search?query={query}"
BASE_URL = "https://tamasha.com"

#: هر کارتِ نتیجه تا شروع کارت بعدی.
_CARD_RE = re.compile(
    r'<div class="video compact-video[^"]*">(?P<body>.*?)'
    r'(?=<div class="video compact-video|\Z)', re.S)
_LINK_RE = re.compile(
    r'<a href="(?P<url>https?://(?:www\.)?tamasha\.com/v/(?P<id>[\w-]+))"'
    r'[^>]*\btitle="(?P<title>[^"]*)"')
_TIME_RE = re.compile(r'<time class="vid-time">\s*([^<\s][^<]*?)\s*</time>')
_CHANNEL_RE = re.compile(
    r'<a class="compact channel-info" href="(?P<path>/[^"]+)">\s*<span>(?P<name>[^<]*)</span>')
#: سرورِ فایلِ هر ویدیو از آدرسِ پیش‌نمایشِ کارت معلومه (as-v1 / as-v2 / ...).
_HOST_RE = re.compile(r'data-video-hover="https://(?P<host>[\w.-]+\.tamasha\.com)/statics/videos_preview/')
STREAM_URL = "https://{host}/statics/stream/{id}/master.m3u8"
#: هم‌زمانیِ چکِ زنده‌بودنِ نتایج.
_ALIVE_CHECK_THREADS = 6
#: فقط چندتای اول چک می‌شن (همون‌ها که زود پخش می‌شن)؛ بقیه بی‌چک می‌مونن تا
#: جستجو کند نشه و صف هم اگه به یه مرده رسید ردش می‌کنه.
_ALIVE_CHECK_LIMIT = 10


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
        host = _HOST_RE.search(text)
        stubs.append({
            "id": link.group("id"),
            "url": link.group("url"),
            "webpage_url": link.group("url"),
            "title": html.unescape(link.group("title")).strip() or "Unknown",
            "duration": parse_duration(time_stamp.group(1) if time_stamp else None),
            "uploader": html.unescape(channel.group("name")).strip() if channel else None,
            "channel_url": BASE_URL + channel.group("path") if channel else None,
            # فقط برای drop_dead؛ resolve از خودِ صفحه انجام می‌شه.
            "stream_url": (STREAM_URL.format(host=host.group("host"), id=link.group("id"))
                           if host else None),
        })
    return stubs


def _is_alive(stub):
    """فایلِ ویدیو هنوز روی سرور هست؟ (بدون آدرسِ استریم: فرض می‌کنیم هست.)"""
    url = stub.get("stream_url")
    if not url:
        return True
    try:
        net.probe(url, max_bytes=64, timeout=8, label="tamasha")
        return True
    except Exception:
        return False


def drop_dead(stubs):
    """
    نتیجه‌هایی که فایلشون از سرور پاک شده کنار می‌رن.

    چرا: ایندکسِ جستجوی تماشا ویدیوهای قدیمی‌ای رو هم برمی‌گردونه که صفحه‌شون
    هست ولی فایل و استریمشون ۴۰۴ می‌ده (تجربه‌ی زنده: ۲۰ تا ۵۰٪ نتیجه‌ها برای
    جستجوهای موسیقی). بدون این، اولین نتیجه اغلب پخش نمی‌شد و جستجو «چیزی پیدا
    نشد» می‌داد. اگه *همه‌ی* چک‌ها شکست بخورن (احتمالاً قطعیِ شبکه، نه ویدیوی
    پاک‌شده) لیست دست‌نخورده می‌مونه.
    """
    head, tail = stubs[:_ALIVE_CHECK_LIMIT], stubs[_ALIVE_CHECK_LIMIT:]
    if not head:
        return stubs
    with ThreadPoolExecutor(max_workers=_ALIVE_CHECK_THREADS) as pool:
        alive = list(pool.map(_is_alive, head))
    return ([s for s, ok in zip(head, alive) if ok] or head) + tail


class Tamasha(YtdlpService):
    SERVICE_NAME = "tamasha"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("tamasha.com",)
    # سرویس تصویریه ولی ربات فقط صدا رو به کانال می‌فرسته.
    AUDIO_ONLY = True

    def _search_stubs(self, query, count, interactive=False):
        """
        نتایج جستجوی تماشا به‌صورت stub؛ همون شکلی که yt-dlp برمی‌گردونه،
        پس resolve، صف و رشد پلی‌لیست هیچ فرقی با جستجوی معمولی نمی‌بینن.
        (ترتیبِ مرتبط‌بودنِ خودِ سایت حفظ می‌شه.)
        """
        try:
            _, body = net.fetch_text(
                SEARCH_URL.format(query=urllib.parse.quote(query)), label="tamasha")
        except Exception as e:
            logging_setup.log_debug(f"[tamasha] search page failed: {e}")
            return []
        return drop_dead(parse_search_html(body)[:count])
