"""
وضعیت پروکسی به‌صورت سراسری/runtime نگه‌داری می‌شه تا هم اسکریپت اصلی و هم
ابزارهای کمکی (playlist_utils) و سرویس‌ها (مثل services/youtube.py) بدون نیاز
به پاس دادن پارامتر اضافه به همه‌جا، از وضعیت فعلی پروکسی مطلع باشن.
"""

import re
import urllib.error
import urllib.request

from core import xray_proxy

_state = {"enabled": False, "url": None}

_SUPPORTED_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")

# "127.0.0.1:2080" یا "user:pass@host:2080" -- بدون scheme
_BARE_HOSTPORT_RE = re.compile(r"^(?:[^\s:@/]+(?::[^\s@/]*)?@)?[A-Za-z0-9._\-\[\]]+:\d{1,5}$")


def normalize_url(url):
    """
    آدرس پروکسی رو به یه شکل استاندارد و قابل‌استفاده برای yt-dlp/mpv/requests
    تبدیل می‌کنه. سه غلط رایج رو خودش درست می‌کنه:

      "http:127.0.0.1:2080"   -> "http://127.0.0.1:2080"   (فراموشی //)
      "127.0.0.1:2080"        -> "http://127.0.0.1:2080"   (نبود scheme)
      " socks5://x:1080/ "    -> "socks5://x:1080"          (فاصله/اسلش اضافه)

    اگه هیچ‌جوره معتبر نشه None برمی‌گردونه (به‌جای این‌که یه رشته‌ی خراب
    ذخیره بشه و بعداً همه‌ی درخواست‌ها رو بی‌صدا fail کنه -- دقیقاً همون
    اتفاقی که با "http:127.0.0.1:2080" توی errors.log افتاده بود).
    """
    if not url:
        return None
    text = str(url).strip().strip('"').strip("'")
    if not text:
        return None

    # لینک V2Ray/Xray (vless/vmess/trojan/ss): همون‌طور که هست نگه داشته
    # می‌شه؛ آدرسِ محلیِ واقعی لحظه‌ی استفاده از xray می‌آد (get_proxy_url).
    if xray_proxy.is_share_link(text):
        try:
            xray_proxy.parse_link(text)
        except xray_proxy.LinkError:
            return None
        return text

    lowered = text.lower()
    for scheme in _SUPPORTED_SCHEMES:
        # حالت درست: scheme://...
        if lowered.startswith(scheme + "://"):
            rest = text[len(scheme) + 3:]
            break
        # حالت غلط ولی رایج: scheme:host:port (بدون //)
        if lowered.startswith(scheme + ":") and not lowered.startswith(scheme + "://"):
            rest = text[len(scheme) + 1:].lstrip("/")
            break
    else:
        scheme = "http"
        rest = text

    rest = rest.strip().rstrip("/")
    if not rest or not _BARE_HOSTPORT_RE.match(rest):
        return None
    return f"{scheme}://{rest}"


def validate(url):
    """(normalized_url, error_text). دقیقاً یکیشون None نیست."""
    normalized = normalize_url(url)
    if normalized:
        return normalized, None
    return None, (
        "invalid proxy address; expected something like "
        "http://127.0.0.1:2080, socks5://127.0.0.1:1080 or a vless/vmess/trojan/ss link"
    )


def mask(url):
    """
    نسخه‌ی امن برای نمایش به کاربر/لاگ: اعتبارنامه‌ی user:pass@ و کل
    محتوای لینک V2Ray (UUID/رمز/کلید) هیچ‌وقت نشون داده نمی‌شه.
    """
    if not url:
        return url
    if xray_proxy.is_share_link(url):
        return xray_proxy.mask_link(url)
    return re.sub(r"//[^/@]*@", "//***@", str(url))


def is_v2ray(url=None):
    return xray_proxy.is_share_link(url if url is not None else _state["url"])


def configure(enabled: bool, url: str | None = None):
    if url is not None:
        _state["url"] = normalize_url(url)
    _state["enabled"] = bool(enabled)
    # پروسه‌ی xray فقط تا وقتی می‌مونه که همین لینک فعاله (خاموش/حذف/عوض
    # شدنِ لینک => بسته می‌شه). بالا اومدنش تنبله، توی resolve.
    if not (_state["enabled"] and is_v2ray()):
        xray_proxy.stop()


def resolve(url, prefer="http"):
    """
    آدرسِ واقعیِ قابل‌استفاده برای یه پروکسی: خودش، یا برای لینک V2Ray
    آدرسِ محلیِ xray (تنبل بالا میاد). prefer: "http" برای mpv/urllib/
    yt-dlp، "socks" برای مصرف‌کننده‌ای که socks می‌خواد. None اگه xray
    بالا نیومد (مثل یه پروکسیِ خراب: فراخوان به مسیر مستقیم برمی‌گرده).
    """
    if not xray_proxy.is_share_link(url):
        return url
    urls = xray_proxy.ensure(url)
    if not urls:
        return None
    return urls[0] if prefer == "socks" else urls[1]
def get_proxy_url():
    """اگه پروکسی فعال و آدرسش تنظیم شده باشه لینکش رو برمی‌گردونه، وگرنه None."""
    if _state["enabled"] and _state["url"]:
        return resolve(_state["url"])
    return None

def status():
    return dict(_state)

def test_proxy(target_url: str, proxy_url: str, timeout: float = 8.0):
    """
    یک درخواست HTTP از طریق proxy_url به target_url می‌زنه و زمان پاسخ (میلی‌ثانیه)
    رو برمی‌گردونه. مستقل از فعال/غیرفعال بودن پروکسی توی تنظیمات کار می‌کنه، چون
    هدفش تست کردن خود آدرس پروکسیه، نه وضعیت فعلیش.
    برگشتی: {"ok": bool, "ms": float یا None, "error": str یا None}
    """
    import time
    import urllib.request

    proxy_url = normalize_url(proxy_url)
    proxy_url = resolve(proxy_url) if proxy_url else None
    if not proxy_url:
        return {"ok": False, "ms": None, "error": "invalid proxy address"}

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    req = urllib.request.Request(target_url, headers={"User-Agent": "Mozilla/5.0"})

    start = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as resp:
            resp.read(1)
        elapsed_ms = (time.monotonic() - start) * 1000
        return {"ok": True, "ms": elapsed_ms, "error": None}
    except Exception as e:
        # متن کامل فقط توی لاگ؛ به ادمین فقط نوع خطا نشون داده می‌شه (متن
        # خام می‌تونه آدرس/اعتبارنامه‌ی پروکسی رو داشته باشه).
        from core import logging_setup
        logging_setup.log_exception("proxy test")
        return {"ok": False, "ms": None, "error": type(e).__name__}


def open_direct_then_proxy(request, timeout, proxy_url):
    """
    urllib: اول مستقیم، بعد با پروکسی (proxy_url؛ اگه خالی بود پروکسیِ
    سیستم/محیط). مشترک بین core/license_remote.py و licensing/cloudflare.py.

    جوابِ HTTP (مثلاً ۴۰۳) «نرسیدن» نیست و همون لحظه raise می‌شه؛ فقط خطای
    شبکه به تلاش بعدی می‌رسه، و خطای آخر raise می‌شه.
    """
    attempts = [urllib.request.build_opener(urllib.request.ProxyHandler({}))]
    if proxy_url:
        attempts.append(urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})))
    else:
        attempts.append(urllib.request.build_opener())

    last_error = None
    for opener in attempts:
        try:
            return opener.open(request, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            last_error = e
    raise last_error
