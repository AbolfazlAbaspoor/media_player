"""
اسکن سبک HTML یه صفحه برای پیدا کردن لینک مستقیم رسانه، بدون باز کردن
مرورگر واقعی. یه لایه‌ی میانی بین yt-dlp (سریع ولی فقط سایت‌های شناخته‌شده)
و Playwright (کند ولی همه‌جا کار می‌کنه چون واقعاً صفحه رو اجرا می‌کنه).

خیلی از صفحات ساده (وبلاگ‌ها، سایت‌های خبری با پلیر HTML5 ساده) لینک
رسانه رو مستقیم توی HTML (تگ <video>/<audio>، متاتگ OpenGraph، JSON-LD یا
حتی رشته‌ی داخل یه اسکریپت) می‌ذارن، بدون اینکه جاوااسکریپت لازم باشه.
برای این‌ها فقط یه GET ساده کافیه. اگه پلیر توی یه iframe/embed باشه،
آدرسش هم برمی‌گرده تا فراخوان (link_resolver) عمیق‌تر بره (با سقفِ عمق).

علاوه بر تگ‌ها، این‌ها هم شناخته می‌شن: twitter:player:stream، JSON-LD
(contentUrl)، کلیدهای JSON/JS مثل "file"/"stream_url" (حتی بی‌پسوند)،
لینکِ نسبیِ href/data-src، آدرسِ URL-encodeشده‌ی داخل پارامتر
(?file=https%3A...) و ریدایرکتِ meta-refresh/جاوااسکریپتِ صفحه‌های خیلی کوچک.
"""

import collections
import html as _html
import re
import urllib.parse

from . import logging_setup
from . import net

_TIMEOUT = 8
_MAX_BYTES = 2_000_000  # صفحات خیلی بزرگ رو کامل پردازش نکن (فقط برای meta/tag کافیه)
# صفحه‌ی ریدایرکتِ جاوااسکریپتی معمولاً کوچیکه؛ توی یه اپِ بزرگ «location =»
# یعنی چیز دیگه‌ای (مثلاً بعد از لاگین)، پس فقط برای صفحه‌های کوچک دنبالش می‌ریم.
_JS_REDIRECT_MAX_HTML = 6000
_MAX_CANDIDATES = 6

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

_MEDIA_EXTENSIONS = (".mp3", ".mp4", ".m3u8", ".m3u", ".wav", ".ogg", ".flac", ".aac", ".webm",
                     ".ts", ".opus", ".m4a", ".mpd", ".mkv", ".pls", ".xspf", ".asx")
_EXT_ALT = r"(?:m3u8|m3u|pls|xspf|asx|mpd|mp4|mp3|m4a|webm|ogg|aac|flac|opus|mkv|wav)"

# تگ/متاهایی که *صریحاً* می‌گن «این رسانه‌ست»: حتی بی‌پسوند قبول می‌شن (ولی
# فراخوان باید با probe تأییدشون کنه). ترتیب اهمیت داره.
_META_STREAM = r'(?:og:(?:video|audio)(?::(?:url|secure_url))?|twitter:player:stream)'
_EXPLICIT_PATTERNS = [
    re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<audio[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<source[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+(?:property|name)=["\']' + _META_STREAM + r'["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']' + _META_STREAM + r'["\']', re.IGNORECASE),
    re.compile(r'["\']contentUrl["\']\s*:\s*["\']([^"\']+)["\']', re.IGNORECASE),
]

# کلیدِ JSON/JS که معمولاً آدرسِ استریم می‌گیره: با پسوندِ رسانه هر آدرسی (حتی
# نسبی) قبوله؛ بی‌پسوند فقط آدرسِ کامل (http/https) و به‌عنوان «ضعیف».
_KEY = (r'(?:file|src|source|url|href|stream|stream_?url|listen_?url|audio|audio_?url|video_?url|'
        r'media|media_?url|hls|hls_?url|mp3|play_?url|data-(?:src|file|url|audio|stream))')
_KEYED_WITH_EXT = re.compile(
    r'["\']?' + _KEY + r'["\']?\s*[:=]\s*["\']([^"\'<>\s]+?\.' + _EXT_ALT + r'(?:\?[^"\'<>\s]*)?)["\']',
    re.IGNORECASE)
_KEYED_ABSOLUTE = re.compile(
    r'["\']?(?:stream|stream_?url|listen_?url|audio_?url|video_?url|media_?url|hls_?url|play_?url|file|source)'
    r'["\']?\s*[:=]\s*["\'](https?:(?:\\?/){2}[^"\'<>\s]+)["\']',
    re.IGNORECASE)
_HREF_WITH_EXT = re.compile(
    r'<a[^>]+href=["\']([^"\'<>\s]+?\.' + _EXT_ALT + r'(?:\?[^"\'<>\s]*)?)["\']', re.IGNORECASE)

# m3u8/mpd (استریم تطبیقی) قبل از فایل‌های ساده میان.
_RAW_PATTERNS = [
    re.compile(r'(https?:(?:\\?/){2}[^\s"\'<>]+?\.(?:m3u8|mpd)(?:\?[^\s"\'<>\\]*)?)', re.IGNORECASE),
    re.compile(r'(https?:(?:\\?/){2}[^\s"\'<>]+?\.' + _EXT_ALT + r'(?:\?[^\s"\'<>\\]*)?)', re.IGNORECASE),
]

_IFRAME = re.compile(r'<(?:iframe|embed)[^>]+(?:data-)?src=["\']([^"\']+)["\']', re.IGNORECASE)
_PLAYER_META = re.compile(
    r'<meta[^>]+(?:property|name)=["\']twitter:player["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE)
_META_REFRESH = re.compile(
    r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?\s*\d*\s*;?\s*url\s*=\s*[\'"]?([^"\'>\s]+)',
    re.IGNORECASE)
_JS_REDIRECT = re.compile(
    r'(?:(?:window|document|top|self)\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']'
    r'|location\.(?:replace|assign)\(\s*["\']([^"\']+)["\']', re.IGNORECASE)

# found: اولین لینکِ قوی یا None؛ candidates: بقیه‌ی قوی‌ها و بعدش ضعیف‌ها؛
# iframes؛ redirect: هدفِ meta-refresh/JS یا None؛ final: آدرسِ نهاییِ صفحه.
PageScan = collections.namedtuple("PageScan", "found candidates iframes redirect final")


def _looks_like_media(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(_MEDIA_EXTENSIONS)


def _is_media_ref(url: str) -> bool:
    return _looks_like_media(url) or ".m3u8" in url.lower() or ".mpd" in url.lower()


def _clean(candidate: str, base: str) -> str:
    # داخل JSON اسلش‌ها escape شدن (https:\/\/...) و داخل HTML &amp; هست.
    candidate = _html.unescape(candidate.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&"))
    return urllib.parse.urljoin(base, candidate.strip())


def _http(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def find_candidates(html: str, base: str):
    """
    (قوی، ضعیف): «قوی» = لینکی که پسوندِ رسانه‌ای شناخته‌شده داره (همون‌طور
    قابل‌پخشه)؛ «ضعیف» = لینکی که صفحه صریحاً رسانه‌اش معرفی کرده ولی پسوند
    نداره (og:audio، JSON-LD، "stream_url": ...) و فراخوان باید با probe
    چکش کنه. هر دو بدون تکرار و با سقف؛ خالص و بدون شبکه.
    """
    strong, weak = [], []

    def add(candidate, is_strong):
        if not candidate:
            return
        resolved = _clean(candidate, base)
        if not _http(resolved):
            return
        is_ref = _is_media_ref(resolved)
        if is_strong and not is_ref:
            return  # پسوند فقط وسطِ query بود (?file=x.mp3): لینکِ رسانه نیست.
        bucket = strong if is_ref else weak
        if resolved not in strong and resolved not in weak and len(bucket) < _MAX_CANDIDATES:
            bucket.append(resolved)

    def scan(text):
        for pattern in _EXPLICIT_PATTERNS:
            for match in pattern.finditer(text):
                add(match.group(1), False)
        for pattern in (_KEYED_WITH_EXT, _HREF_WITH_EXT, *_RAW_PATTERNS):
            for match in pattern.finditer(text):
                add(match.group(1), True)
        for match in _KEYED_ABSOLUTE.finditer(text):
            add(match.group(1), False)

    scan(html)
    if not strong and "%2F" in html:
        # آدرس داخل پارامتر (player.php?file=https%3A%2F%2F...mp3).
        scan(urllib.parse.unquote(html))
    return strong, weak


def find_media(html: str, base: str):
    """اولین لینک رسانه‌ی (با پسوندِ شناخته‌شده) داخل متنِ HTML (یا None). خالص و بدون شبکه."""
    strong, _weak = find_candidates(html, base)
    return strong[0] if strong else None


def find_iframes(html: str, base: str, limit: int = 4):
    """آدرس iframe/embedها (و twitter:player) ی صفحه (مطلق، بدون تکرار، حداکثر limit تا)."""
    found = []
    for pattern in (_IFRAME, _PLAYER_META):
        for match in pattern.finditer(html):
            src = _clean(match.group(1), base)
            if _http(src) and src not in found:
                found.append(src)
            if len(found) >= limit:
                return found
    return found


def find_redirect(html: str, base: str):
    """
    هدفِ ریدایرکتِ meta-refresh یا جاوااسکریپت (فقط برای صفحه‌ی کوچک) یا None.
    خالص و بدون شبکه.
    """
    match = _META_REFRESH.search(html)
    target = match.group(1) if match else None
    if not target and len(html) <= _JS_REDIRECT_MAX_HTML:
        js = _JS_REDIRECT.search(html)
        target = (js.group(1) or js.group(2)) if js else None
    if not target:
        return None
    resolved = _clean(target, base)
    return resolved if _http(resolved) and resolved != base else None


def scan_detailed(url: str):
    """
    PageScan(found, candidates, iframes, redirect, final). بدون raise -- در هر
    مشکلی یه PageScan خالی برمی‌گردونه تا فراخوان بره سراغ روش بعدی.
    final = آدرسِ صفحه بعد از ریدایرکتِ HTTP (مبنای لینک‌های نسبی و Referer).
    """
    try:
        final, body = net.fetch(url, headers={"User-Agent": USER_AGENT}, timeout=_TIMEOUT,
                                label="html_scan", max_bytes=_MAX_BYTES)
    except Exception:
        logging_setup.log_debug("[html_media_scan] fetching page failed")
        return PageScan(None, [], [], None, url)
    final = final or url
    html = body.decode("utf-8", errors="replace")
    strong, weak = find_candidates(html, final)
    return PageScan(strong[0] if strong else None, strong[1:] + weak, find_iframes(html, final),
                    find_redirect(html, final), final)


def scan(url: str):
    """فقط لینک رسانه‌ی خودِ صفحه (رشته) یا None."""
    return scan_detailed(url).found
