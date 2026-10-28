"""
سرویس رادیو جوان (radiojavan.com): **جستجوی متنی** و پخش آهنگ.

استفاده:
    w radiojavan  +  p <نام خواننده یا آهنگ، فارسی یا انگلیسی>   -> جستجو
    p https://play.radiojavan.com/song/<نام-آهنگ>                -> یه آهنگ
    p https://www.radiojavan.com/mp3s/mp3/<نام-آهنگ>             -> یه آهنگ
    p https://play.radiojavan.com/video/<نام-ویدیو>              -> یه موزیک‌ویدیو
    p https://rj.app/m/<کد>                                      -> لینک کوتاه

## چرا yt-dlp نه

اکسترکتور RadioJavan توی yt-dlp خرابه (CURRENTLY BROKEN) و صفحه‌ی
www.radiojavan.com پشت چالش ضدرباتِ Cloudflare است (403). ولی برنامه‌ی وبِ
خودِ رادیو جوان یه API عمومی و بدون کلید داره:

    https://play.radiojavan.com/api/p/search?query=<عبارت>
    https://play.radiojavan.com/api/p/mp3?id=<permlink>
    https://play.radiojavan.com/api/p/video?id=<permlink>

نتیجه‌ی جستجو (`mp3s`) هر آهنگ رو با لینک مستقیمِ mp3 (۲۵۶ کیلوبیت) می‌ده،
پس stub خودش قابل‌پخشه و هیچ درخواستِ resolveی لازم نیست. permlink همون
بخشِ آخرِ آدرس صفحه‌ست (حروف کوچک/بزرگش فرقی نمی‌کنه).
"""

import json
import posixpath
import urllib.parse
import urllib.request

from core import logging_setup
from core import net
from core import proxy_state
from core import track_meta
from core.services._ytdlp_service import YtdlpService

SEARCH_API = "https://play.radiojavan.com/api/p/search?query={query}"
MP3_API = "https://play.radiojavan.com/api/p/mp3?id={permlink}"
VIDEO_API = "https://play.radiojavan.com/api/p/video?id={permlink}"
SONG_PAGE = "https://play.radiojavan.com/song/{permlink}"
VIDEO_PAGE = "https://play.radiojavan.com/video/{permlink}"

#: مسیرهای صفحه‌ی آهنگ/ویدیو (پلی‌ر جدید و سایت کلاسیک) -> نوعش.
_SONG_PATHS = ("song", "mp3")
_VIDEO_PATHS = ("video",)
#: لینک‌کوتاه rj.app/m/... و rj.app/v/... (با ریدایرکت به صفحه‌ی بالا).
_SHORT_HOSTS = ("rj.app",)
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def _count(text):
    """"17,203,339" -> 17203339، یا None."""
    try:
        return int(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _title(item):
    """«خواننده - آهنگ»؛ اگه جدا نبود، خودِ title."""
    artist, song = item.get("artist"), item.get("song")
    if artist and song:
        return f"{artist} - {song}"
    return item.get("title") or "Unknown"


def stub_from_item(item, kind="song"):
    """
    آیتمِ API (آهنگ یا ویدیو) -> stub با لینک مستقیمِ پخش داخلش (`media_url`).
    None اگه permlink یا لینکِ پخش نداشت.
    """
    if not isinstance(item, dict):
        return None
    permlink = item.get("permlink")
    # `link` هم برای آهنگ (mp3 ۲۵۶) هم برای ویدیو (mp4 معمولی) فایلِ مستقیمه؛
    # hq_link ویدیو همون 4K است و برای رباتی که فقط صدا می‌فرسته زیادیه.
    media = item.get("link")
    if not permlink or not media:
        return None
    page = (SONG_PAGE if kind == "song" else VIDEO_PAGE).format(permlink=permlink)
    return {
        "id": permlink,
        "url": page,
        "webpage_url": page,
        "media_url": media,
        "title": _title(item),
        "duration": item.get("duration"),
        "uploader": item.get("artist"),
        "view_count": _count(item.get("plays") or item.get("views")),
        "like_count": _count(item.get("likes")),
        "timestamp": track_meta.parse_timestamp(item.get("created_at")),
    }


class RadioJavan(YtdlpService):
    SERVICE_NAME = "radiojavan"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("radiojavan.com", "//rj.app/")
    AUDIO_ONLY = True

    def _api_get(self, url):
        _, body = net.fetch_text(url, headers={"Accept": "application/json"}, label="radiojavan")
        return json.loads(body)

    def _search_stubs(self, query, count, interactive=False):
        """
        آهنگ‌های نتیجه‌ی جستجو به‌صورت stub (ترتیبِ مرتبط‌بودنِ خودِ رادیو جوان).
        stubها لینکِ mp3 رو همراه دارن، پس صف و رشد پلی‌لیست هیچ درخواستِ
        اضافه‌ای نمی‌زنن.
        """
        try:
            payload = self._api_get(SEARCH_API.format(query=urllib.parse.quote(query)))
        except Exception as e:
            logging_setup.log_debug(f"[radiojavan] search API failed: {e}")
            return []
        stubs = []
        for item in (payload.get("mp3s") or []):
            stub = stub_from_item(item)
            if stub:
                stubs.append(stub)
                if len(stubs) >= count:
                    break
        return stubs

    @staticmethod
    def _kind_and_permlink(url):
        """
        ("song"|"video"|"short"|None، permlink یا خودِ url) از آدرس.
        صفحه‌ی آهنگ: /song/<p> یا /mp3s/mp3/<p>؛ ویدیو: /video/<p> یا
        /videos/video/<p>؛ لینک‌کوتاه: rj.app/m|v/<کد>.
        """
        parts = urllib.parse.urlparse(url or "")
        host = (parts.hostname or "").lower()
        segments = [urllib.parse.unquote(s) for s in parts.path.split("/") if s]
        if host in _SHORT_HOSTS:
            return ("short", url) if len(segments) >= 2 else (None, None)
        if not segments:
            return None, None
        head = segments[-2].lower() if len(segments) >= 2 else ""
        if head in _SONG_PATHS:
            return "song", segments[-1]
        if head in _VIDEO_PATHS:
            return "video", segments[-1]
        return None, None

    @staticmethod
    def _follow_short_link(url):
        """
        آدرسِ نهاییِ یه لینک‌کوتاهِ rj.app (یا None). Cloudflareِ rj.app کلاینتِ
        yt-dlp (core.net) رو با ۴۰۳ رد می‌کنه ولی urllib با User-Agentِ مرورگر
        رو راه می‌ده؛ هدر فقط تا ریدایرکتِ آخر خونده می‌شه، نه بدنه.
        """
        request = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        try:
            with proxy_state.open_direct_then_proxy(request, 10, proxy_state.get_proxy_url()) as response:
                return response.geturl()
        except Exception as e:
            logging_setup.log_debug(f"[radiojavan] short link failed: {e}")
            return None

    def search(self, query):
        """
        لینکِ آهنگ/ویدیو/لینک‌کوتاهِ رادیو جوان از API خودش resolve می‌شه.
        بقیه‌ی لینک‌ها (هنرمند، پلی‌لیست، ...) None می‌دن تا لوله‌ی عمومیِ لینک
        تلاشش رو بکنه.
        """
        query = (query or "").strip()
        if not query.startswith(("http://", "https://")):
            return super().search(query)
        if not self.owns_url(query):
            return None

        kind, permlink = self._kind_and_permlink(query)
        if kind == "short":
            final = self._follow_short_link(permlink)
            kind, permlink = self._kind_and_permlink(final)
        if kind not in ("song", "video"):
            return None

        api = MP3_API if kind == "song" else VIDEO_API
        try:
            item = self._api_get(api.format(permlink=urllib.parse.quote(permlink)))
        except Exception as e:
            logging_setup.log_debug(f"[radiojavan] item API failed: {e}")
            return None
        stub = stub_from_item(item, kind)
        if not stub:
            return None
        self._last_playlist_info = None
        return self._resolve_entry(stub, interactive=True)

    def _resolve_entry(self, entry, interactive=False):
        """
        stubِ رادیو جوان لینکِ مستقیم داره (media_url)؛ چیزی که yt-dlp بتونه
        از صفحه‌ش دربیاره نیست (اکسترکتورش خرابه)، پس همین‌جا ساخته می‌شه.
        """
        if not entry:
            return None
        media = entry.get("media_url")
        if not media:
            return None
        return {
            "id": entry.get("id"),
            "url": media,
            "title": entry.get("title") or "Unknown",
            "public_url": entry.get("webpage_url") or entry.get("url"),
            "channel_url": None,
            "info": track_meta.from_info(
                dict(entry, ext=posixpath.splitext(urllib.parse.urlparse(media).path)[1].lstrip(".").lower() or None),
                self.SERVICE_NAME),
            "verified_media": True,
        }
