"""
ابزارهای کمکی برای تشخیص و باز کردن لینک‌های پلی‌لیستی: m3u8/m3u، pls
(شوت‌کست/آیس‌کست)، xspf و asx.

نکته: خیلی از لینک‌های m3u8 در واقع یک استریم HLS واقعی هستن (چند سگمنت .ts یا
چند کیفیت متفاوت). این‌ها رو نباید دستی پارس کرد، چون mpv خودش به شکل بومی
ازشون پشتیبانی می‌کنه. اما بعضی لینک‌های m3u8/m3u صرفاً یک لیست ساده از
لینک‌های پخش جداگانه (آهنگ/فایل) هستن که باید به‌صورت آیتم‌های جدا به
پلی‌لیست ربات اضافه بشن. این ماژول این دو حالت رو از هم تشخیص می‌ده.
"""

import html as _html
import re
import urllib.parse

from . import net

PLAYLIST_EXTENSIONS = (".m3u8", ".m3u", ".pls", ".xspf", ".asx")

# سقفِ حجمِ خودِ فایلِ پلی‌لیست و تعدادِ آیتم‌ها: لینکِ کاربر ممکنه هر چیزی باشه.
_MAX_BYTES = 1_000_000
MAX_ENTRIES = 100

# فقط آدرس‌های شبکه‌ای: یه پلی‌لیستِ راه‌دور نباید بتونه فایل‌های محلیِ سرور
# (file:///...) رو به پخش‌کننده بده.
_NETWORK_SCHEMES = ("http", "https", "rtmp", "rtmps", "rtsp", "mms", "mmsh")

_PLS_FILE = re.compile(r"^\s*File(\d+)\s*=\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_XSPF_LOCATION = re.compile(r"<location>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</location>",
                            re.IGNORECASE | re.DOTALL)
_ASX_REF = re.compile(r"<ref\s[^>]*?href\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)


def looks_like_playlist(url: str) -> bool:
    if not url:
        return False
    return urllib.parse.urlparse(url).path.lower().endswith(PLAYLIST_EXTENSIONS)


# سازگاری با فراخوان‌های قدیمی.
looks_like_m3u = looks_like_playlist


def sniff_playlist(head: bytes) -> bool:
    """از روی چند بایتِ اول: آیا این یه فایلِ پلی‌لیست (m3u/pls/xspf/asx) به‌نظر می‌رسه؟"""
    start = head.lstrip()[:200].lower()
    return start.startswith((b"#extm3u", b"[playlist]", b"<asx")) or (
        start.startswith((b"<?xml", b"<playlist")) and b"<playlist" in head[:400].lower())


def _absolute(entries, base):
    """آدرس‌ها رو نسبت به base مطلق می‌کنه، فقط شبکه‌ای‌ها، بدون تکرار، با سقف."""
    result = []
    for entry in entries:
        entry = _html.unescape(entry.strip())
        if not entry:
            continue
        absolute = urllib.parse.urljoin(base, entry)
        if urllib.parse.urlparse(absolute).scheme.lower() not in _NETWORK_SCHEMES:
            continue
        if absolute not in result:
            result.append(absolute)
        if len(result) >= MAX_ENTRIES:
            break
    return result


def parse_entries(text: str, base: str):
    """
    آدرس‌های یه پلی‌لیستِ ساده (m3u/pls/xspf/asx) یا None وقتی پلی‌لیستِ ساده
    نیست (HLS واقعی، یا اصلاً فرمتِ ناشناخته). خالص و بدون شبکه.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    first = lines[0].lower()
    if first.startswith("#extm3u") or first.startswith(("http://", "https://")):
        joined = "\n".join(lines)
        if "#EXT-X-STREAM-INF" in joined or "#EXT-X-TARGETDURATION" in joined:
            return None  # HLS واقعی: mpv خودش مدیریتش می‌کنه.
        return _absolute([l for l in lines if not l.startswith("#")], base) or None
    if first.startswith("[playlist]") or _PLS_FILE.search(text):
        found = sorted(_PLS_FILE.findall(text), key=lambda pair: int(pair[0]))
        return _absolute([value for _n, value in found], base) or None
    lowered = text[:2000].lower()
    if "<asx" in lowered:
        return _absolute(_ASX_REF.findall(text), base) or None
    if "<playlist" in lowered:
        return _absolute(_XSPF_LOCATION.findall(text), base) or None
    return None


def _fetch_text(url: str, timeout: int = 10) -> str:
    # net.fetch_text: اول پروکسیِ ربات، بعد مستقیم (socks5 هم کار می‌کنه).
    _final, text = net.fetch_text(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout,
                                  label="playlist", max_bytes=_MAX_BYTES)
    return text


def resolve_playlist(url: str, timeout: int = 10, force: bool = False):
    """
    اگر url یک m3u8/m3u واقعی HLS باشه (سگمنت یا استریم چندکیفیتی)، همون url
    رو برمی‌گردونه تا mpv خودش مدیریتش کنه: [url]

    اگر url یک "لیست ساده از لینک‌ها" (m3u/pls/xspf/asx) باشه، تک‌تک لینک‌های
    داخلش (resolve شده نسبت به url اصلی) رو به‌صورت لیست برمی‌گردونه.

    force=True: پسوند رو چک نکن (لینکِ بی‌پسوندی که از محتواش فهمیدیم پلی‌لیسته).

    در صورت هر مشکلی (خطای شبکه، فرمت نامعتبر و ...) فقط [url] برمی‌گردونه
    تا mpv خودش سعی کنه پخشش کنه.
    """
    if not force and not looks_like_playlist(url):
        return [url]

    try:
        content = _fetch_text(url, timeout=timeout)
    except Exception:
        return [url]

    return parse_entries(content, url) or [url]
