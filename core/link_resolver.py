"""
برای لینک‌های مستقیمی که کاربر می‌فرسته (نه از طریق دستور جستجو)، این ماژول
از سریع‌ترین روش به کندترین روش امتحان می‌کنه تا لینک قابل‌پخش پیدا کنه:

  0) بازنویسیِ لینک‌های اشتراک (Dropbox dl=1، Google Drive دانلود مستقیم).
  1) اگه خودِ لینک مستقیم به یه فایل رسانه‌ای شناخته‌شده اشاره کنه، همون
     استفاده می‌شه (سریع‌ترین حالت، بدون هیچ پردازش اضافه‌ای). پلی‌لیست‌ها
     (m3u/pls/xspf/asx) به آیتم‌هاشون باز می‌شن.
  2) یه درخواست ارزون (probe): ریدایرکت‌ها (لینک‌کوتاه‌کن) دنبال می‌شن و از
     Content-Type/چند بایتِ اول می‌فهمیم لینکِ بی‌پسوند (http://host:port/name)
     مدیا/پلی‌لیست/صفحه‌ست.
  3) yt-dlp عمومی: خیلی از سایت‌ها (۱۸۰۰+ extractor) رو بدون نیاز به
     مرورگر واقعی پشتیبانی می‌کنه (فقط چند درخواست HTTP).
  4) اسکن سبک HTML: یه GET ساده به صفحه، دنبال <video>/<audio>/OpenGraph/
     JSON-LD/کلیدهای JSON یا لینک خام رسانه می‌گرده؛ meta-refresh/ریدایرکتِ
     جاوااسکریپت و iframeها رو (با سقفِ عمق و تعدادِ صفحه) دنبال می‌کنه.
  5) yt-dlp با extractorِ عمومیِ اجباری (وقتی extractorِ اختصاصیِ سایت خراب
     بوده).
  6) مرورگر headless (Playwright): کندترین ولی جامع‌ترین روش؛ فقط وقتی به
     سراغش می‌ریم که روش‌های بالا جواب ندن (سایت‌هایی که استریم رو کاملاً
     با جاوااسکریپت لود می‌کنن).

هر مرحله برای *هر* لینکی امتحان می‌شه (نه فقط سایت‌های شناخته‌شده)، ولی کلِ
کار یه سقفِ زمانی و تعدادِ صفحه داره (_Budget): لینکِ کاربر ممکنه هر چیزی
باشه و نباید ربات رو برای همیشه درگیر کنه.

وقتی رسانه‌ای که توی یه صفحه پیدا شد برای پخش هدرِ Referer/User-Agent
می‌خواد، نتیجه کلیدِ "headers" ({"referrer","user_agent"}) داره -- همون
هدرهایی که مکانیزمِ IPTV (core/iptv.py) روی mpv می‌ذاره؛ bot.py::load_and_play
اون‌ها رو با همون تابع اعمال می‌کنه.
"""

import functools
import re
import time
import urllib.parse

from . import proxy_state
from . import logging_setup
from . import proxy_retry
from . import ytdlp_opts
from . import playlist_utils

_DIRECT_MEDIA_EXTENSIONS = (
    ".mp3", ".mp4", ".m3u8", ".m3u", ".wav", ".ogg", ".flac", ".aac", ".webm", ".ts", ".mkv", ".opus", ".m4a", ".mpd"
) + tuple(e for e in playlist_utils.PLAYLIST_EXTENSIONS if e not in (".m3u8", ".m3u"))

#: سقفِ کلِ زمانِ resolve یه لینک (ثانیه) -- بین مرحله‌ها چک می‌شه.
TOTAL_BUDGET_SECONDS = 75
#: حداکثر دنبال‌کردنِ ریدایرکتِ meta/جاوااسکریپت/پلی‌لیستِ تودرتو.
MAX_REDIRECT_HOPS = 4
#: حداکثر عمقِ iframe توی iframe.
MAX_FRAME_DEPTH = 3
#: حداکثر تعدادِ صفحه‌ای که برای یه لینک دانلود می‌شه.
MAX_PAGES = 8
#: از یه پلی‌لیست حداکثر این‌قدر از آیتم‌ها هم resolve می‌شن (بقیه خام).
MAX_RESOLVED_PLAYLIST_ENTRIES = 5
# مرورگر headless حداقل این‌قدر زمان می‌خواد (بالا اومدن + لود + انتظار).
_BROWSER_MIN_SECONDS = 20

_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def looks_like_direct_media(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(_DIRECT_MEDIA_EXTENSIONS)


_MEDIA_MAGIC = (
    (b"ID3", 0), (b"OggS", 0), (b"fLaC", 0), (b"RIFF", 0), (b"\x1a\x45\xdf\xa3", 0),
    (b"ftyp", 4), (b"FLV", 0), (b"MThd", 0),
)
_PLAYLIST_CONTENT_TYPES = ("audio/x-scpls", "audio/scpls", "application/pls+xml", "application/xspf+xml")


def classify_probe(content_type: str, head: bytes) -> str:
    """
    'media' | 'playlist' | 'html' | 'unknown' از روی Content-Type و چند بایتِ
    اول. خالص و بدون شبکه (تستش راحته). MPEG sync (0xFFEx) و ADTS هم مدیا
    حساب می‌شن. 'playlist' = m3u/pls/xspf/asx (که باید باز بشه).
    """
    ctype = (content_type or "").lower()
    if ctype in _PLAYLIST_CONTENT_TYPES or playlist_utils.sniff_playlist(head):
        return "playlist"
    if ctype.startswith(("audio/", "video/")) or ctype in (
            "application/ogg", "application/vnd.apple.mpegurl", "application/x-mpegurl",
            "application/dash+xml"):
        return "media"
    stripped = head.lstrip()[:15].lower()
    if ctype in ("text/html", "application/xhtml+xml") or stripped.startswith((b"<!doctype", b"<html")):
        return "html"
    for magic, offset in _MEDIA_MAGIC:
        if head[offset:offset + len(magic)] == magic:
            return "media"
    if len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:
        return "media"
    return "unknown"


def probe_details(url: str, headers=None):
    """
    (kind، آدرسِ نهاییِ بعد از ریدایرکت، Content-Type، چند بایتِ اول) با یه
    درخواستِ ارزون (Range کوچک) -- بدون raise؛ خطا = ("unknown", url, "", b"").
    """
    from core import net
    try:
        final, ctype, head = net.probe(url, label="link", headers=headers)
    except Exception:
        logging_setup.log_debug("[link] probe failed")
        # شوت‌کستِ قدیمی («ICY 200 OK») رو HTTP-client نمی‌فهمه، ولی mpv پخش می‌کنه.
        if net.is_icy_stream(url):
            return "media", url, "audio/mpeg", b""
        return "unknown", url, "", b""
    return classify_probe(ctype, head), final or url, ctype, head


def probe_kind(url: str) -> str:
    return probe_details(url)[0]


def _is_media_ref(url: str) -> bool:
    return looks_like_direct_media(url) or ".m3u8" in url.lower() or ".mpd" in url.lower()


# ----------------------------------------------------------------- بودجه

class _Budget:
    """سقفِ زمان و تعدادِ صفحه‌ی یه resolve (یه نمونه برای کلِ درخت)."""

    def __init__(self, seconds=TOTAL_BUDGET_SECONDS, max_pages=MAX_PAGES):
        self.deadline = time.monotonic() + seconds
        self.max_pages = max_pages
        self.pages = 0

    def remaining(self):
        return self.deadline - time.monotonic()

    def expired(self):
        return self.remaining() <= 0

    def take_page(self):
        """یه صفحه‌ی دیگه اجازه داریم بگیریم؟ (و یکی از سهمیه کم می‌شه)"""
        if self.pages >= self.max_pages:
            return False
        self.pages += 1
        return True


# ------------------------------------------------------- لینک‌های اشتراک

_DRIVE_FILE_PATH = re.compile(r"^/(?:a/[^/]+/)?file/d/([\w-]+)")


def rewrite_share_link(url: str) -> str:
    """
    لینکِ «صفحه‌ی اشتراک» رو به لینکِ دانلودِ مستقیمِ همون فایل تبدیل می‌کنه
    (وگرنه یه صفحه‌ی HTML می‌گیریم نه فایل): Dropbox (dl=1) و Google Drive.
    هر لینکِ دیگه‌ای دست‌نخورده برمی‌گرده. خالص و بدون شبکه.
    """
    parts = urllib.parse.urlparse(url)
    host = parts.netloc.lower().split(":")[0]
    if host == "dropbox.com" or host.endswith(".dropbox.com"):
        query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                 if k not in ("dl", "raw")]
        query.append(("dl", "1"))
        return urllib.parse.urlunparse(parts._replace(query=urllib.parse.urlencode(query)))
    if host == "drive.google.com":
        match = _DRIVE_FILE_PATH.match(parts.path)
        file_id = match.group(1) if match else dict(urllib.parse.parse_qsl(parts.query)).get("id")
        if file_id and (match or parts.path in ("/open", "/uc")):
            # confirm=t: فایل‌های بزرگ صفحه‌ی «ویروس‌یاب» نشون نمی‌دن.
            return ("https://drive.usercontent.google.com/download?id="
                    f"{urllib.parse.quote(file_id)}&export=download&confirm=t")
    return url


# ---------------------------------------------------------------- yt-dlp

def _direct_url(info):
    if info.get("url"):
        return info["url"]
    for fmt in info.get("requested_formats") or []:
        if fmt.get("url"):
            return fmt["url"]
    return None

_PROXY_REQUIRED_DOMAINS = ("youtube.com", "youtu.be", "googlevideo.com", "ytimg.com")

def _domain_needs_proxy(url: str) -> bool:
    """
    پروکسی رو فقط برای دامنه‌هایی که واقعاً بهش نیاز دارن (مثل یوتیوب که
    توی خیلی از شبکه‌ها بلاکه) روشن می‌کنیم؛ برای بقیه‌ی سایت‌ها (مخصوصاً
    سایت‌های داخلی مثل namasha.com که معمولاً مستقیم در دسترسن)، رفتن از
    پروکسی هم کندتره هم اگه پروکسی خراب/غیرقابل‌دسترس باشه، بی‌خودی کل
    درخواست رو fail می‌کنه.
    """
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in _PROXY_REQUIRED_DOMAINS)


@functools.lru_cache(maxsize=1)
def _extractor_classes():
    from yt_dlp.extractor import gen_extractor_classes
    return tuple(gen_extractor_classes())


def has_dedicated_extractor(url: str) -> bool:
    """
    آیا یه extractorِ اختصاصی (نه generic) yt-dlp این آدرس رو می‌شناسه؟
    اگه نه، yt-dlp عمومی همون‌جوری هم فقط از generic رد می‌شد.
    """
    try:
        return any(ie.IE_NAME != "generic" and ie.suitable(url) for ie in _extractor_classes())
    except Exception:
        return False

MAX_PLAYLIST_ITEMS = 10


def try_ytdlp(url: str, timeout: int = 15, force_generic: bool = False):
    """
    تلاش سریع با yt-dlp عمومی (خیلی از سایت‌ها از جمله بعضی سایت‌های ایرانی
    پشتیبانی می‌شن). به‌جای raise کردن، در هر مشکلی None برمی‌گردونه تا
    فراخوان بره سراغ روش بعدی. در موفقیت {"url","title"} برمی‌گردونه.

    پروکسی/fallback/اطلاع‌رسانی چت از core.proxy_retry میاد (همون منطق
    مشترکی که سرویس‌ها استفاده می‌کنن) -- فقط برای دامنه‌هایی که واقعاً
    بهش نیاز دارن (_domain_needs_proxy) پروکسی رو امتحان می‌کنه، وگرنه
    مستقیم بدون پروکسی می‌ره (سریع‌تر، و اگه پروکسی خراب باشه بی‌خودی
    fail نمی‌شه).

    force_generic=True: extractorِ اختصاصیِ سایت رو رد می‌کنه و مستقیم
    generic رو اجرا می‌کنه (وقتی اختصاصی خراب شده ولی صفحه پلیرِ قابل‌پیدا داره).
    """
    opts = {
        "quiet": True,
        "no_warnings": False,
        "format": "bestaudio/best",
        "skip_download": True,
        "socket_timeout": timeout,
        "logger": logging_setup.get_ytdlp_logger(),
        # پلی‌لیستِ غیرسرویسی هم کامل‌تر از یه آیتم: چند اولی (سقف MAX_PLAYLIST_ITEMS).
        "playlist_items": f"1-{MAX_PLAYLIST_ITEMS}",
        # کم‌کردن ردپای درخواست‌ها (مثل بقیه‌ی سرویس‌ها).
        "retries": 2,
        "extractor_retries": 1,
        "fragment_retries": 2,
    }
    ytdlp_opts.with_js_runtime(opts)

    try:
        if _domain_needs_proxy(url) and not force_generic:
            info = proxy_retry.extract_with_fallback(opts, url, label="link")
        else:
            from yt_dlp import YoutubeDL
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, **({"ie_key": "Generic"} if force_generic else {}))
    except ImportError:
        return None
    except Exception:
        logging_setup.log_exception(f"yt-dlp resolve failed for '{url}'")
        return None

    if not info:
        return None

    if "entries" in info:
        entries = [e for e in (info.get("entries") or []) if e]
        items = [_item_from_info(e, url) for e in entries]
        items = [i for i in items if i]
        if not items:
            return None
        if len(items) > 1:
            return dict(items[0], items=items)
        return items[0]

    return _item_from_info(info, url)


def _headers_from_info(info):
    """
    Referer/User-Agentی که yt-dlp برای این فرمت لازم می‌دونه (extractorهای
    generic/سایت‌های محافظت‌شده). بدون Referer چیزی برنمی‌گردونه: UA پیش‌فرضِ
    yt-dlp برای بقیه (مثل یوتیوب) رو عمداً به mpv نمی‌دیم.
    """
    headers = info.get("http_headers") or {}
    referer = headers.get("Referer") or headers.get("referer")
    if not referer:
        return None
    result = {"referrer": referer}
    agent = headers.get("User-Agent") or headers.get("user-agent")
    if agent:
        result["user_agent"] = agent
    return result


def _item_from_info(info, url):
    direct = _direct_url(info)
    if not direct:
        return None
    item = {
        "url": direct, "title": info.get("title"), "public_url": info.get("webpage_url") or url,
        # توضیح کامل: core/services/_ytdlp_service.py::_resolve_entry.
        "verified_media": True,
    }
    headers = _headers_from_info(info)
    if headers:
        item["headers"] = headers
    if info.get("extractor_key") == "Generic":
        # generic حدسی‌ه (مثلاً «.wav» وسطِ query رو لینکِ رسانه می‌گیره)؛
        # _resolve قبل از قبول با یه probe چکش می‌کنه.
        item["generic"] = True
    return item


def _is_reachable(item):
    """
    آیا لینکِ نتیجه‌ی generic واقعاً جواب می‌ده؟ (probe، با هدرهای خودش).
    خطا/۴۰۴ = نه. رسانه/پلی‌لیست/ناشناخته = بله؛ فقط صفحه‌ی HTML نه.
    """
    try:
        from core import net
        headers = {"Referer": item["headers"]["referrer"]} if item.get("headers") else None
        _final, ctype, head = net.probe(item["url"], label="link", timeout=6, headers=headers)
    except Exception:
        return False
    return classify_probe(ctype, head) != "html"


# ------------------------------------------------------------- اسکن صفحه

def _media_item(url, public_url, headers=None):
    item = {"url": url, "title": None, "public_url": public_url}
    if headers:
        item["headers"] = headers
    return item


def _stream_headers(media_url, page_url):
    """
    هدرهایی که mpv برای پخشِ رسانه‌ای که روی صفحه‌ی page_url پیدا شد لازم داره
    (یا None). استریم‌های HLS/DASH همیشه Referer می‌گیرن (سگمنت‌ها هم
    چک می‌شن و نمی‌شه پیشاپیش فهمید)؛ برای فایل‌ها یه probe بدون Referer
    می‌زنیم و فقط اگه رد شد Referer می‌دیم.
    """
    if not page_url or page_url == media_url:
        return None
    headers = {"referrer": page_url, "user_agent": _BROWSER_UA}
    lowered = media_url.lower()
    if ".m3u8" in lowered or ".mpd" in lowered:
        return headers
    try:
        from core import net
        net.probe(media_url, label="link", timeout=5)
        return None
    except Exception:
        logging_setup.log_debug("[link] media needs a referer; attaching page headers")
        return headers


def _playlist_result(url, public_url, budget, hops):
    """
    پلی‌لیستِ ساده (m3u/pls/xspf/asx) رو باز می‌کنه. چند آیتمِ اول (سقفِ
    MAX_RESOLVED_PLAYLIST_ENTRIES) خودشون resolve می‌شن (مثلاً ورودیِ
    یوتیوب/ریدایرکت)، بقیه خام می‌مونن و mpv پخششون می‌کنه.
    HLS واقعی/غیرقابل‌پارس: همون لینک.
    """
    entries = playlist_utils.resolve_playlist(url, force=True)
    if entries == [url] or hops >= MAX_REDIRECT_HOPS:
        return _media_item(url, public_url)
    items = []
    for index, entry in enumerate(entries):
        resolved = None
        if index < MAX_RESOLVED_PLAYLIST_ENTRIES and entry != url:
            resolved = _resolve(entry, budget, hops + 1, public=public_url)
        if resolved:
            items.extend(resolved.get("items") or [resolved])
        else:
            items.append(_media_item(entry, public_url))
    return dict(items[0], items=items) if len(items) > 1 else items[0]


def try_html_scan(url: str, depth: int = MAX_FRAME_DEPTH, budget=None, hops: int = 0):
    """
    لایه‌ی میانی: GET سبک به صفحه، دنبال تگ رسانه/OpenGraph/JSON-LD/لینک خام
    می‌گرده؛ لینک‌های «صریح ولی بی‌پسوند» رو با probe چک می‌کنه؛ ریدایرکتِ
    meta/جاوااسکریپت و iframe/embedهای صفحه رو (تا depth سطح، با سقفِ
    تعدادِ صفحه و زمانِ _Budget) با yt-dlp و بعد اسکن HTML امتحان می‌کنه
    (مثلاً پلیر یوتیوب/آپاراتِ توی یه پست).
    بدون raise -- در هر مشکلی None برمی‌گردونه.
    """
    budget = budget or _Budget()
    if budget.expired() or not budget.take_page():
        return None
    try:
        from core import html_media_scan
        scan = html_media_scan.scan_detailed(url)
    except Exception:
        logging_setup.log_exception(f"html-scanning '{url}' failed")
        return None
    page = scan.final or url
    if scan.found:
        return _media_item(scan.found, url, _stream_headers(scan.found, page))

    frames = []
    for candidate in scan.candidates:
        if _is_media_ref(candidate):
            return _media_item(candidate, url, _stream_headers(candidate, page))
        kind, final, _ctype, _head = probe_details(candidate)
        if kind == "media":
            return _media_item(final, url, _stream_headers(final, page))
        if kind == "playlist":
            return _playlist_result(final, url, budget, hops)
        if kind == "html" or final != candidate:
            frames.append(final)

    if scan.redirect and hops < MAX_REDIRECT_HOPS:
        result = _resolve(scan.redirect, budget, hops + 1, public=url)
        if result:
            return result

    if depth <= 0:
        return None
    seen = {url, page}
    for frame in frames + scan.iframes:
        if frame in seen or budget.expired():
            continue
        seen.add(frame)
        if _is_media_ref(frame):
            result = _media_item(frame, url, _stream_headers(frame, page))
        else:
            # yt-dlp فقط برای سایتی که extractorِ اختصاصی داره (یوتیوب/آپارات...)؛
            # برای بقیه‌ی iframeها generic همون اسکنِ خودمونه و وقتِ بودجه رو می‌خوره.
            result = (has_dedicated_extractor(frame) and try_ytdlp(frame)) or \
                try_html_scan(frame, depth - 1, budget, hops)
        if result:
            result["public_url"] = url
            return result
    return None


# ------------------------------------------------------------------ اصلی

def _ytdlp_checked(url, force_generic=False):
    """try_ytdlp؛ نتیجه‌ی generic که جواب نمی‌ده (حدسِ غلط) دور ریخته می‌شه."""
    result = try_ytdlp(url, **({"force_generic": True} if force_generic else {}))
    if not result:
        return None
    for item in result.get("items") or ():
        item.pop("generic", None)
    if result.pop("generic", False) and not _is_reachable(result):
        logging_setup.log_debug("[link] yt-dlp generic result is not reachable; trying the next method")
        return None
    return result


def _browser_item(url, budget):
    # مرورگر گرون‌ترین تلاشه و توی بیلد مشتری اصلاً نیست. بدون این
    # چک، هر لینکی که مرحله‌های قبل حلش نکردن یه traceback کامل
    # می‌نوشت -- برای چیزی که اصلاً خطا نیست، و تازه لاگ هم رمزه
    # پس مشتری نمی‌تونه ببینه بی‌ضرره.
    extracted = None
    try:
        from core import browser_extract
        if browser_extract.is_available() and budget.remaining() >= _BROWSER_MIN_SECONDS:
            extracted = browser_extract.extract_stream(
                url, timeout_ms=int(min(20, budget.remaining() - 8) * 1000))
    except RuntimeError as e:
        # «نصب نیست» / «مرورگر نیست»: وضعیت معلومه، نه خرابی.
        logging_setup.log_debug(f"[link] browser tier unavailable: {e}")
    except Exception:
        logging_setup.log_exception(f"browser-extracting stream from '{url}'")
    return _media_item(extracted, url, _stream_headers(extracted, url)) if extracted else None


def _resolve(url: str, budget, hops: int = 0, public=None):
    public = public or url
    url = rewrite_share_link(url)
    if budget.expired():
        return None

    if looks_like_direct_media(url):
        if playlist_utils.looks_like_playlist(url) and not url.lower().split("?")[0].endswith(".m3u8"):
            return _playlist_result(url, public, budget, hops)
        return _media_item(url, public)

    # لینکِ بی‌پسوند/با پورت (http://host:port/name) یا کوتاه‌شده: probe هم
    # ریدایرکت‌ها رو دنبال می‌کنه هم می‌گه مدیا/پلی‌لیست/صفحه‌ست. اگه probe
    # جواب نداد ('unknown') هم ادامه می‌دیم و آخرش فراخوان خامش رو به پلیر می‌ده.
    kind, final, _ctype, _head = probe_details(url)
    if final != url:
        logging_setup.log_debug("[link] url redirected")
        url = rewrite_share_link(final)
        if looks_like_direct_media(url) and kind != "playlist":
            return _resolve(url, budget, hops + 1, public)
    if kind == "media":
        return _media_item(url, public, None)
    if kind == "playlist":
        return _playlist_result(url, public, budget, hops)

    result = _ytdlp_checked(url)
    if result:
        return result

    # صفحه‌ی یوتیوب و هم‌خانواده‌ها بدونِ yt-dlp چیزی برای پیدا‌کردن ندارن؛
    # اسکن/مرورگر فقط چند دقیقه وقت می‌سوزوند (مثلاً وقتی یوتیوب بات‌چک می‌ده).
    if _domain_needs_proxy(url):
        return None

    result = try_html_scan(url, budget=budget, hops=hops)
    if result:
        return result

    # extractorِ اختصاصیِ سایت خراب بوده؟ generic هنوز شاید پلیرِ صفحه رو پیدا کنه.
    if has_dedicated_extractor(url) and not budget.expired():
        result = _ytdlp_checked(url, force_generic=True)
        if result:
            return result

    return _browser_item(url, budget)


def resolve(url: str):
    """
    از سریع‌ترین به کندترین روش امتحان می‌کنه و اولین نتیجه‌ی قابل‌پخش رو
    به‌صورت {"url","title","public_url"} برمی‌گردونه (title ممکنه None
    باشه؛ public_url همیشه هست -- برای دستورات i/di لازمه، صرف‌نظر از
    این‌که load_and_play این آیتم رو private صدا بزنه یا نه). پلی‌لیست‌ها
    کلیدِ "items" دارن؛ اگه پخش هدر بخواد کلیدِ "headers". اگه هیچ‌کدوم
    جواب نداد، None برمی‌گردونه.

    ترتیب: مدیای مستقیم (پسوند یا probe، با دنبال‌کردنِ ریدایرکت) -> yt-dlp
    -> اسکن HTML سبک (+ریدایرکت/iframe) -> yt-dlp generic -> مرورگر
    headless. اگه هیچ‌کدوم چیزی نداد، *فراخوان* (command_helpers) آخرین
    تلاش رو می‌کنه: لینک خام رو به mpv می‌ده. هیچ‌وقت raise نمی‌کنه و از
    TOTAL_BUDGET_SECONDS بیشتر (به‌جز یه درخواستِ در-جریان) طول نمی‌کشه.
    """
    try:
        return _resolve(url, _Budget())
    except Exception:
        logging_setup.log_exception(f"resolving link '{url}' failed")
        return None
