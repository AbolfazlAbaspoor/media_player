"""
پایه‌ی مشترک سایت‌های دانلود موزیکِ ایرانیِ وردپرسی (upmusics، nex1music،
rozmusic و مشابه‌ها).

## چرا یه فایل مشترک

این سایت‌ها ظاهرشون فرق داره ولی سه چیز یکسانه:

  * صفحه‌ی جستجو (`?s=` یا `/search/<عبارت>`) هر نتیجه رو با یه تیتر
    `<h2><a href=...>` لیست می‌کنه (بقیه‌ی لینک‌ها تگ/دسته‌بندی‌ان).
  * لینک مستقیم mp3 نه توی نتایج جستجو، بلکه توی *صفحه‌ی خودِ پست* هست؛
    معمولاً چند نسخه‌ی یک آهنگ کنار هم (۳۲۰، ۱۲۸ و گاهی ۶۴ کیلوبیت).
  * هیچ‌کدوم API یا extractor yt-dlp ندارن.

پس پارسِ جستجو، پیدا کردنِ بهترین mp3 و resolve فقط یک‌بار این‌جا نوشته
می‌شه و هر سایت فقط `HOST` و آدرس جستجوش رو می‌گه (`upmusics.py` ...).
فایلِ با `_` لود نمی‌شه و خودش سرویس نیست.

## از کجا بفهمیم کدوم mp3 بهتره

بیت‌ریت توی اسم فایل میاد: `(320)`، `[128]`، `_128`، ` 128.mp3`. فایلِ
بدون عدد همون نسخه‌ی اصلی (بالاترین کیفیت)ـه، و فایل‌های demo/preview/
sample (تیزرِ کوتاه) فقط وقتی انتخاب می‌شن که چیز دیگه‌ای نباشه.
"""

import html
import posixpath
import re
import urllib.parse

from core import logging_setup
from core import net
from core import track_meta
from core.services._ytdlp_service import YtdlpService

#: هر لینک/سورسِ mp3 یا m4a توی صفحه. اسم فایل فاصله و حروف فارسی داره، پس
#: فقط جداکننده‌های HTML کنار گذاشته می‌شن.
_MEDIA_RE = re.compile(
    r"""(?:href|src|data-src|data-url|data-mp3|data-audio)\s*=\s*["']\s*"""
    r"""(?P<url>(?:https?:)?//[^"'<>]+?\.(?:mp3|m4a)(?:\?[^"'<>]*)?)\s*["']""",
    re.I)
#: تیتر هر نتیجه توی صفحه‌ی جستجو.
_RESULT_RE = re.compile(
    r"""<h2[^>]*>\s*<a\s[^>]*?href=["'](?P<url>[^"']+)["'][^>]*>(?P<title>.*?)</a>""",
    re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"\s+")
_OG_TITLE_RE = re.compile(
    r"""<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']*)["']""", re.I)

#: بخش‌هایی از مسیر که لیست‌اند، نه پستِ آهنگ (تگ، دسته، نویسنده، صفحه‌بندی).
_LISTING_SEGMENTS = frozenset({
    "tag", "tags", "category", "cat", "author", "page", "search", "feed", "artist",
    "artists", "wp-content", "wp-json", "wp-admin"})
#: فایل‌های تیزر/پیش‌نمایش که فقط به‌عنوان آخرین چاره انتخاب می‌شن.
_PREVIEW_RE = re.compile(r"(?:preview|sample|demo|snippet|teaser)", re.I)
#: بیت‌ریت‌های معمول؛ عددِ دیگه‌ی اسم فایل (سال، شناسه) بیت‌ریت حساب نمی‌شه.
_BITRATES = frozenset({32, 48, 64, 96, 112, 128, 160, 192, 224, 256, 320})
_BITRATE_RE = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")
#: فایلِ بدون بیت‌ریت = نسخه‌ی اصلی؛ بالاتر از هر عدد.
_UNTAGGED_RANK = 1000
_MEDIA_SUFFIXES = (".mp3", ".m4a", ".mp4", ".m3u8", ".zip", ".rar")


def clean_title(text):
    """
    تیتر پست -> عنوانِ کوتاه‌تر برای نمایش: «دانلود آهنگ X به نام Y + متن
    آهنگ» -> «X - Y». هرجا الگو نبود، متن دست‌نخورده می‌مونه.
    """
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    text = _SPACES_RE.sub(" ", text.replace("‌", " ").replace("​", "")).strip()
    text = re.sub(r"^دانلود\s+(?:(?:آهنگ|ریمیکس|موزیک|آلبوم|اجرای\s+زنده)\s+)?", "", text)
    text = re.sub(r"\s*\+\s*متن\s+آهنگ\s*$", "", text)
    text = re.sub(r"\s+به\s+نام\s+", " - ", text, count=1)
    return text.strip() or "Unknown"


def _host(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _result_links(body, card_marker):
    """
    (url، تیتر) هر نتیجه. با card_marker صفحه به کارت‌ها تقسیم می‌شه و از هر
    کارت فقط اولین تیتر برمی‌داره -- سایدبارِ «آخرین آهنگ‌ها» هم تیتر h2 داره و
    بدون این، نتایجِ نامربوط قاطی جستجو می‌شد.
    """
    if not card_marker:
        for match in _RESULT_RE.finditer(body or ""):
            yield match.group("url"), match.group("title")
        return
    starts = [m.start() for m in re.finditer(card_marker, body or "")]
    for begin, end in zip(starts, starts[1:] + [len(body or "")]):
        for match in _RESULT_RE.finditer(body, begin, end):
            # اولین تیترِ *قابل‌قبول* کارت (تگ/دسته ردّ می‌شه)، نه صرفاً اولین h2.
            if is_post_url(html.unescape(match.group("url"))):
                yield match.group("url"), match.group("title")
                break


def parse_search_html(body, host, card_marker=None):
    """
    تیترهای صفحه‌ی جستجو -> لیست stub (ترتیبِ صفحه، بدون تکراری).
    فقط لینک‌های خودِ همین سایت که لیست (تگ/دسته/...) نباشن پست حساب می‌شن.
    """
    stubs, seen = [], set()
    for raw_url, raw_title in _result_links(body, card_marker):
        url = html.unescape(raw_url).strip()
        if _host(url) != host or not is_post_url(url):
            continue
        slug = urllib.parse.unquote(urllib.parse.urlparse(url).path).strip("/")
        if slug in seen:
            continue
        seen.add(slug)
        stubs.append({
            "id": slug,
            "url": url,
            "webpage_url": url,
            "title": clean_title(raw_title),
        })
    return stubs


def is_post_url(url):
    """
    آدرسِ یه پستِ آهنگ است؟ (نه صفحه‌ی اصلی، تگ، دسته، جستجو یا خودِ فایل).
    هم برای فیلتر نتایج جستجو هم برای تشخیصِ لینکِ پیست‌شده.
    """
    parts = urllib.parse.urlparse(url or "")
    segments = [s for s in urllib.parse.unquote(parts.path).split("/") if s]
    if not segments or segments[0].lower() in _LISTING_SEGMENTS:
        return False
    if "s" in urllib.parse.parse_qs(parts.query):
        return False
    return not segments[-1].lower().endswith(_MEDIA_SUFFIXES)


def _normalize(url, base):
    """آدرسِ مطلق با فاصله/حروف غیرلاتین کدشده (mpv و yt-dlp فاصله توی آدرس رو نمی‌خورن)."""
    url = html.unescape(url).strip()
    url = urllib.parse.urljoin(base, url)
    return urllib.parse.quote(url, safe=":/?&=%#@+,;()[]!$'*~")


def _bitrate(url):
    """بیت‌ریتِ اسم فایل، یا _UNTAGGED_RANK برای نسخه‌ی اصلی."""
    name = posixpath.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path))
    stem = name.rsplit(".", 1)[0]
    found = [int(n) for n in _BITRATE_RE.findall(stem) if int(n) in _BITRATES]
    return found[-1] if found else _UNTAGGED_RANK


def is_preview(url):
    """این فایل تیزر/دمو است، نه آهنگِ کامل؟"""
    return bool(_PREVIEW_RE.search(posixpath.basename(urllib.parse.urlparse(url).path)))


def media_links(body, base):
    """
    لینک‌های mp3 صفحه، بهترین اول: کیفیت نزولی، بقیه به ترتیبِ صفحه. تکراری‌ها
    (http و https یا دو بار آوردنِ یک فایل) یکی می‌شن و https ترجیح داره.
    تیزر/پیش‌نمایش فقط وقتی میاد که چیز دیگه‌ای نباشه.
    """
    unique = {}
    for match in _MEDIA_RE.finditer(body or ""):
        url = _normalize(match.group("url"), base)
        key = re.sub(r"^https?:", "", url)
        if key not in unique or (url.startswith("https") and not unique[key].startswith("https")):
            unique[key] = url
    links = list(unique.values())
    full = [u for u in links if not is_preview(u)]
    # sorted پایداره: بین هم‌کیفیت‌ها ترتیبِ صفحه می‌مونه.
    return sorted(full or links, key=_bitrate, reverse=True)


class WpMusicService(YtdlpService):
    """
    زیرکلاس‌ها فقط `SERVICE_NAME`، `HOST`، `URL_MARKERS` و `SEARCH_URL` رو می‌دن.
    """

    SUPPORTS_SEARCH = True
    AUDIO_ONLY = True

    #: دامنه‌ی سایت بدون www (مثلاً "upmusics.com"). حتماً پرش کن.
    HOST = ""
    #: آدرسِ جستجو؛ {query} با عبارتِ urlencode‌شده جایگزین می‌شه.
    SEARCH_URL = ""
    #: regexِ شروعِ هر کارتِ نتیجه (اگه سایت توی سایدبار هم تیتر h2 داره).
    CARD_MARKER = None

    def _search_stubs(self, query, count, interactive=False):
        """
        نتایج جستجوی سایت به‌صورت stub؛ همون شکلی که yt-dlp برمی‌گردونه، پس
        resolve، صف و رشد پلی‌لیست هیچ فرقی با جستجوی معمولی نمی‌بینن.
        (ترتیبِ مرتبط‌بودنِ خودِ سایت حفظ می‌شه.)
        """
        try:
            _, body = net.fetch_text(
                self.SEARCH_URL.format(query=urllib.parse.quote(query)), label=self.SERVICE_NAME)
        except Exception as e:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] search page failed: {e}")
            return []
        return parse_search_html(body, self.HOST, self.CARD_MARKER)[:count]

    def search(self, query):
        """
        لینکِ یه پستِ آهنگ مستقیم از صفحه‌ی پست resolve می‌شه؛ لینکِ دیگه‌ی
        همین سایت (تگ، فایلِ mp3 مستقیم، ...) None می‌ده تا لوله‌ی عمومیِ لینک
        بهش برسه (لینکِ فایل بدون هیچ سرویسی هم پخش می‌شه).
        """
        query = (query or "").strip()
        if query.startswith(("http://", "https://")):
            if not self.owns_url(query):
                return None
            if not is_post_url(query):
                return None
            self._last_playlist_info = None
            return self._resolve_entry({"id": None, "webpage_url": query}, interactive=True)
        return super().search(query)

    def _resolve_entry(self, entry, interactive=False):
        """
        صفحه‌ی پست رو می‌گیره و بهترین mp3 رو برمی‌داره. اگه خودِ صفحه
        گرفته نشد، شانسِ آخر با اکسترکتورِ عمومیِ yt-dlp است.
        """
        if not entry:
            return None
        page = entry.get("webpage_url") or entry.get("url")
        if not page:
            return None
        try:
            _, body = net.fetch_text(page, label=self.SERVICE_NAME)
        except Exception as e:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] post page failed: {e}")
            return super()._resolve_entry(entry, interactive=interactive)

        links = media_links(body, page)
        if not links:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] no mp3 link on the post page")
            return None
        best = links[0]

        og = _OG_TITLE_RE.search(body)
        title = entry.get("title") or (clean_title(og.group(1)) if og else None)
        if is_preview(best):
            # آهنگِ تازه گاهی فقط دمو داره؛ شنونده باید بدونه کامل نیست.
            title = f"{title or 'Unknown'} (دمو)"
        bitrate = _bitrate(best)
        info = track_meta.from_info({
            "id": entry.get("id"),
            "title": title,
            "webpage_url": page,
            "ext": posixpath.splitext(urllib.parse.urlparse(best).path)[1].lstrip(".").lower() or None,
            "abr": bitrate if bitrate != _UNTAGGED_RANK else None,
        }, self.SERVICE_NAME)
        return {
            "id": entry.get("id") or page,
            "url": best,
            "title": title or "Unknown",
            "public_url": page,
            "channel_url": None,
            "info": info,
            "verified_media": True,
        }
