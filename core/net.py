"""
گرفتنِ یه صفحه یا فایل متنی از اینترنت، از همون مسیر پروکسیِ بقیه‌ی ربات.

چرا یه ماژول جدا: اسپاتیفای (صفحه‌ی embed) و IPTV (پلی‌لیست M3U) هر دو
«یه آدرس رو بگیر، اول با پروکسیِ ربات، بعد بدون اون» لازم داشتن و هرکدوم
نسخه‌ی خودش رو داشت -- نسخه‌ی IPTV با urllib بود که پروکسیِ socks5 رو
نمی‌شناسه. حالا یه جا، و هر اصلاحی به هر دو می‌رسه.

از شبکه‌ی خودِ yt-dlp استفاده می‌شه نه urllib: پروکسیِ ربات ممکنه socks5
باشه، و yt-dlp گواهی‌ها رو با certifi چک می‌کنه (urllib روی بعضی ویندوزها
با «unable to get local issuer certificate» رد می‌شد).
"""

from core import logging_setup
from core.ytdlp_lazy import YoutubeDL, Request
from core import proxy_state

DEFAULT_TIMEOUT = 15


def _urlopen_with_fallback(url, headers, timeout, label, what, read):
    """
    اول با پروکسیِ ربات (اگه روشنه)، بعد صراحتاً بدون پروکسی؛ read(response)
    نتیجه‌ی هر تلاش رو می‌سازه. خطای آخرین تلاش raise می‌شه.
    """
    attempts = []
    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        attempts.append(proxy_url)
    # "" یعنی صراحتاً بدون پروکسی؛ None پروکسیِ محیط/ویندوز رو برمی‌داشت.
    attempts.append("")
    last_error = None
    for proxy in attempts:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": timeout,
            "proxy": proxy,
            "logger": logging_setup.get_ytdlp_logger(),
        }
        try:
            with YoutubeDL(opts) as ydl:
                with ydl.urlopen(Request(url, headers=headers)) as response:
                    return read(response)
        except Exception as e:
            last_error = e
            route = "proxy" if proxy else "direct"
            logging_setup.log_debug(f"[{label}] {what} failed ({route}): {e}")
    raise last_error


def fetch(url, headers=None, timeout=DEFAULT_TIMEOUT, label="net", max_bytes=None):
    """
    (آدرسِ نهایی بعد از ریدایرکت، بایت‌های بدنه).

    max_bytes: سقفِ خوندن (None = همه‌ی بدنه). برای لینکِ کاربر همیشه یه
    سقف بده -- سرورِ بدجنس/استریمِ بی‌پایان نباید حافظه رو پر کنه.

    اول با پروکسیِ ربات (اگه روشنه)، بعد صراحتاً بدون پروکسی -- همون ترتیبِ
    core/proxy_retry.py. خطای آخرین تلاش raise می‌شه؛ پیامش ممکنه آدرس رو
    داشته باشه، پس فراخوان هیچ‌وقت مستقیم نشونش نمی‌ده.
    """
    return _urlopen_with_fallback(
        url, dict(headers or {}), timeout, label, "fetch",
        lambda response: (response.url, response.read(max_bytes) if max_bytes else response.read()))


def probe(url, max_bytes=2048, timeout=8, label="net", headers=None):
    """
    (آدرسِ نهایی، Content-Type کوچک‌حرف، چند بایتِ اول) -- برای تشخیصِ این‌که
    یه لینکِ بی‌پسوند رسانه‌ست یا صفحه. فقط `max_bytes` می‌خونه (Range هم
    می‌فرسته) و می‌بنده، پس روی استریمِ بی‌پایان (icecast) هم گیر نمی‌کنه.
    مثل fetch اول پروکسیِ ربات، بعد مستقیم؛ خطای آخر raise می‌شه.

    headers: هدرهای اضافه (مثلاً Referer برای سرورهایی که بدونش 403 می‌دن).
    """
    def read(response):
        ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        return response.url, ctype, response.read(max_bytes)

    return _urlopen_with_fallback(
        url, {"Range": f"bytes=0-{max_bytes - 1}", **(headers or {})}, timeout, label, "probe", read)


def fetch_text(url, headers=None, timeout=DEFAULT_TIMEOUT, label="net", encoding="utf-8", max_bytes=None):
    """مثل fetch، ولی بدنه به‌صورت متن (کاراکترِ خراب جایگزین می‌شه، نه خطا)."""
    final_url, body = fetch(url, headers=headers, timeout=timeout, label=label, max_bytes=max_bytes)
    return final_url, body.decode(encoding, errors="replace")


def is_icy_stream(url, timeout=5):
    """
    True اگه سرور با «ICY 200 OK» (شوت‌کستِ نسخه‌ی ۱) جواب بده. کتابخونه‌ی HTTP
    (و yt-dlp) این status-line رو نمی‌شناسه و probe() خطا می‌ده، در حالی که mpv
    ازش پخش می‌کنه. فقط http:// و مستقیم (بدون پروکسی)؛ فقط status-line
    خونده می‌شه و سوکت بسته می‌شه، پس روی استریمِ بی‌پایان هم گیر نمی‌کنه.
    """
    import socket
    import urllib.parse
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "http" or not parts.hostname:
        return False
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    try:
        with socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(f"GET {target} HTTP/1.0\r\nHost: {parts.netloc}\r\nIcy-MetaData: 0\r\n"
                         "User-Agent: Mozilla/5.0\r\n\r\n".encode("ascii", "ignore"))
            return sock.recv(16).upper().startswith(b"ICY")
    except Exception:
        return False
