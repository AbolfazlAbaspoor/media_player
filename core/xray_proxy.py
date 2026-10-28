"""
پشتیبانی V2Ray/Xray به‌عنوان جایگزینِ پروکسیِ ساده (E17).

کاربر دقیقاً همون دستور `proxy <link>` رو می‌زنه، فقط به‌جای http://...
یه لینک vless:// ، vmess:// ، trojan:// یا ss:// می‌ده. زیر کاپوت برای
هر ربات *یک* پروسه‌ی xray-core بالا میاد که روی 127.0.0.1 و یه پورت آزاد
گوش می‌ده (یه inbound socks و یه inbound http -- چون mpv/urllib/stt فقط
http می‌فهمن و yt-dlp هر دو رو)، و بقیه‌ی ربات مثل هر پروکسی دیگه‌ای از
همون آدرس محلی رد می‌شه: proxy_state.get_proxy_url() آدرس رو می‌ده.

* تنبل (lazy): تا وقتی کسی آدرس رو نخواسته هیچ پروسه‌ای بالا نمیاد؛ رباتِ
  بدون لینک V2Ray صفر CPU/RAM اضافه مصرف می‌کنه.
* کانفیگ از stdin به xray داده می‌شه، نه فایل -- UUID/کلید هیچ‌جای دیسک
  نمی‌مونه.
* اگه پروسه مرد، دفعه‌ی بعدی که آدرس خواسته بشه دوباره بالا میاد (با یه
  وقفه‌ی کوتاه بعد از شکست تا حلقه‌ی restart نسازه).
* خروج: atexit پروسه رو نرم terminate می‌کنه؛ یه pidfile هم می‌مونه تا
  اگه ربات سخت کشته شد، استارتِ بعدی xrayِ یتیم رو جمع کنه.
"""

import atexit
import base64
import json
import os
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from core import logging_setup, platform_paths

SHARE_SCHEMES = ("vless", "vmess", "trojan", "ss")

_START_TIMEOUT = 8.0
_RETRY_COOLDOWN = 15.0


class LinkError(ValueError):
    """لینک قابل‌فهم نیست. پیامش عمداً بدون هیچ بخشی از لینک است."""


def is_share_link(text):
    """آیا این رشته شکلِ یه لینک اشتراکِ V2Ray دارد (بدون اعتبارسنجی کامل)؟"""
    if not text:
        return False
    head = str(text).strip().split("://", 1)
    return len(head) == 2 and head[0].lower() in SHARE_SCHEMES


# ------------------------------------------------------------- پارس لینک

def _b64decode(data):
    data = data.strip().replace("-", "+").replace("_", "/")
    data += "=" * (-len(data) % 4)
    return base64.b64decode(data).decode("utf-8")


def _first(params, key, default=""):
    values = params.get(key)
    return values[0] if values else default


def _stream_settings(network, security, p):
    """
    بخش streamSettings مشترک بین هر چهار پروتکل. p دیکشنری تخت از
    پارامترهای لینک است (کلیدها همون اسم‌های استانداردِ share-link).
    """
    network = (network or "tcp").lower()
    if network == "h2":
        network = "http"
    stream = {"network": network, "security": security or "none"}

    host = p.get("host", "")
    path = p.get("path", "")
    if network == "ws":
        ws = {"path": path or "/"}
        if host:
            ws["headers"] = {"Host": host}
        stream["wsSettings"] = ws
    elif network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": p.get("serviceName") or path,
            "multiMode": p.get("mode") == "multi",
        }
    elif network == "http":
        http = {"path": path or "/"}
        if host:
            http["host"] = [h for h in host.split(",") if h]
        stream["httpSettings"] = http
    elif network == "httpupgrade":
        hu = {"path": path or "/"}
        if host:
            hu["host"] = host
        stream["httpupgradeSettings"] = hu
    elif network in ("xhttp", "splithttp"):
        xh = {"path": path or "/"}
        if host:
            xh["host"] = host
        if p.get("mode"):
            xh["mode"] = p["mode"]
        stream["network"] = "xhttp"
        stream["xhttpSettings"] = xh
    elif network == "tcp" and p.get("headerType") == "http":
        stream["tcpSettings"] = {"header": {"type": "http", "request": {
            "path": [path or "/"],
            "headers": {"Host": [h for h in host.split(",") if h]},
        }}}

    sni = p.get("sni") or p.get("peer") or host
    alpn = [a for a in p.get("alpn", "").split(",") if a]
    if security == "tls":
        tls = {"allowInsecure": p.get("allowInsecure") in ("1", "true")}
        if sni:
            tls["serverName"] = sni
        if alpn:
            tls["alpn"] = alpn
        if p.get("fp"):
            tls["fingerprint"] = p["fp"]
        stream["tlsSettings"] = tls
    elif security == "reality":
        stream["realitySettings"] = {
            "serverName": sni,
            "fingerprint": p.get("fp") or "chrome",
            "publicKey": p.get("pbk", ""),
            "shortId": p.get("sid", ""),
            "spiderX": p.get("spx", ""),
        }
    return stream


def _url_parts(link):
    """(scheme, user, host, port, params, fragment) از یه لینک استاندارد."""
    parts = urlsplit(link.strip())
    if not parts.hostname or not parts.port:
        raise LinkError("missing host or port")
    params = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
    return parts.scheme.lower(), unquote(parts.username or ""), parts.hostname, parts.port, params


def _parse_vless(link):
    _, user, host, port, p = _url_parts(link)
    if not user:
        raise LinkError("missing id")
    security = p.get("security", "none")
    user_cfg = {"id": user, "encryption": p.get("encryption") or "none"}
    if p.get("flow"):
        user_cfg["flow"] = p["flow"]
    return {
        "protocol": "vless",
        "settings": {"vnext": [{"address": host, "port": port, "users": [user_cfg]}]},
        "streamSettings": _stream_settings(p.get("type"), security, p),
    }


def _parse_trojan(link):
    _, user, host, port, p = _url_parts(link)
    if not user:
        raise LinkError("missing password")
    security = p.get("security", "tls")
    return {
        "protocol": "trojan",
        "settings": {"servers": [{"address": host, "port": port, "password": user}]},
        "streamSettings": _stream_settings(p.get("type"), security, p),
    }


def _parse_vmess(link):
    try:
        data = json.loads(_b64decode(link.strip()[len("vmess://"):]))
    except Exception:
        raise LinkError("bad vmess payload") from None
    if not (data.get("add") and data.get("port") and data.get("id")):
        raise LinkError("incomplete vmess payload")
    security = "tls" if str(data.get("tls", "")).lower() == "tls" else "none"
    p = {"host": data.get("host", ""), "path": data.get("path", ""),
         "sni": data.get("sni", ""), "alpn": data.get("alpn", ""),
         "fp": data.get("fp", ""), "headerType": data.get("type", "")}
    return {
        "protocol": "vmess",
        "settings": {"vnext": [{
            "address": data["add"], "port": int(data["port"]),
            "users": [{"id": data["id"], "alterId": int(data.get("aid") or 0),
                       "security": data.get("scy") or "auto"}],
        }]},
        "streamSettings": _stream_settings(data.get("net"), security, p),
    }


def _parse_ss(link):
    body = link.strip()[len("ss://"):].split("#", 1)[0]
    body, _, query = body.partition("?")
    try:
        if "@" in body:
            userinfo, _, hostport = body.rpartition("@")
            userinfo = unquote(userinfo)
            if ":" not in userinfo:  # SIP002: base64(method:password)
                userinfo = _b64decode(userinfo)
        else:  # فرمت قدیمی: base64(method:password@host:port)
            userinfo, _, hostport = _b64decode(body).rpartition("@")
        method, _, password = userinfo.partition(":")
        host, _, port = hostport.strip("/").rpartition(":")
        host = host.strip("[]")
        port = int(port)
    except Exception:
        raise LinkError("bad ss link") from None
    if not (method and password and host):
        raise LinkError("incomplete ss link")
    return {
        "protocol": "shadowsocks",
        "settings": {"servers": [{"address": host, "port": port,
                                  "method": method, "password": password}]},
        "streamSettings": {"network": "tcp", "security": "none"},
    }


_PARSERS = {"vless": _parse_vless, "vmess": _parse_vmess,
            "trojan": _parse_trojan, "ss": _parse_ss}


def parse_link(link):
    """خروجیِ outbound برای xray؛ اگه لینک خراب بود LinkError (بدون متنِ لینک)."""
    if not is_share_link(link):
        raise LinkError("unsupported scheme")
    scheme = link.strip().split("://", 1)[0].lower()
    try:
        outbound = _PARSERS[scheme](link)
    except LinkError:
        raise
    except Exception:
        raise LinkError("unparsable link") from None
    outbound["tag"] = "proxy"
    return outbound


def build_config(link, socks_port, http_port):
    """کانفیگ کاملِ xray: دو inbound فقط روی 127.0.0.1 و یه outbound."""
    def inbound(tag, protocol, port, settings):
        return {"tag": tag, "listen": "127.0.0.1", "port": port,
                "protocol": protocol, "settings": settings}
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            inbound("socks-in", "socks", socks_port, {"auth": "noauth", "udp": False}),
            inbound("http-in", "http", http_port, {}),
        ],
        "outbounds": [parse_link(link), {"tag": "direct", "protocol": "freedom"}],
    }


def mask_link(link):
    """نسخه‌ی قابل‌نمایش: فقط پروتکل، سرور و پورت -- هرگز UUID/رمز/کلید."""
    try:
        outbound = parse_link(link)
        settings = outbound["settings"]
        server = (settings.get("vnext") or settings.get("servers"))[0]
        stream = outbound.get("streamSettings", {})
        extra = "/".join(x for x in (stream.get("network"), stream.get("security"))
                         if x and x != "none")
        text = f"{link.strip().split('://', 1)[0].lower()}://***@{server['address']}:{server['port']}"
        return f"{text} ({extra})" if extra else text
    except Exception:
        return link.strip().split("://", 1)[0].lower() + "://***"


# --------------------------------------------------------------- پروسه

_lock = threading.RLock()
_proc = None
_link = None
_ports = None          # (socks, http)
_failed_at = 0.0
_atexit_registered = False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pidfile():
    from core.paths import get_base_dir
    return os.path.join(get_base_dir(), "xray.pid")


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _reap_stale():
    """اگه ربات قبلی سخت کشته شده بود، xrayِ یتیمِ خودش رو جمع کن."""
    path = _pidfile()
    try:
        with open(path) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        import psutil
        p = psutil.Process(pid)
        if "xray" in p.name().lower():
            p.terminate()
            p.wait(3)
    except Exception:
        pass
    try:
        os.remove(path)
    except OSError:
        pass


def _terminate(proc):
    """فقط پروسه‌ی خودِ xray؛ اول نرم، بعد از ۳ ثانیه kill."""
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(3)
    except Exception:
        try:
            proc.kill()
            proc.wait(2)
        except Exception:
            pass


def stop():
    global _proc, _link, _ports
    with _lock:
        _terminate(_proc)
        _proc = _link = _ports = None
        try:
            os.remove(_pidfile())
        except OSError:
            pass


def _start(link):
    """پروسه رو بالا میاره؛ True اگه پورت‌ها واقعاً گوش می‌دن."""
    global _proc, _link, _ports, _failed_at, _atexit_registered
    binary = platform_paths.find_native_component("xray")
    if not binary:
        import shutil
        binary = shutil.which("xray")
    if not binary:
        logging_setup.log_debug("[xray] binary not found")
        _failed_at = time.monotonic()
        return False
    binary = platform_paths._ensure_executable(binary)
    _reap_stale()
    socks_port, http_port = _free_port(), _free_port()
    while http_port == socks_port:
        http_port = _free_port()
    try:
        config = json.dumps(build_config(link, socks_port, http_port))
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        proc = subprocess.Popen(
            [binary, "run", "-config", "stdin:"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags)
        proc.stdin.write(config.encode("utf-8"))
        proc.stdin.close()
    except Exception:
        logging_setup.log_exception("xray start")
        _failed_at = time.monotonic()
        return False

    deadline = time.monotonic() + _START_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        if _port_open(socks_port) and _port_open(http_port):
            _proc, _link, _ports = proc, link, (socks_port, http_port)
            try:
                with open(_pidfile(), "w") as f:
                    f.write(str(proc.pid))
            except OSError:
                pass
            if not _atexit_registered:
                atexit.register(stop)
                _atexit_registered = True
            return True
        time.sleep(0.1)
    _terminate(proc)
    logging_setup.log_debug("[xray] did not become ready")
    _failed_at = time.monotonic()
    return False


def ensure(link):
    """
    (socks_url, http_url) برای این لینک، یا None اگه xray بالا نیومد.
    اگه پروسه هنوز زنده و برای همین لینکه، همون آدرس؛ اگه مرده یا لینک
    عوض شده، دوباره (یا با کانفیگ جدید) بالا میاد.
    """
    global _failed_at
    with _lock:
        alive = _proc is not None and _proc.poll() is None
        if alive and _link == link:
            return _urls()
        if alive:
            stop()
        if time.monotonic() - _failed_at < _RETRY_COOLDOWN:
            return None
        if _start(link):
            return _urls()
        return None


def _urls():
    return f"socks5h://127.0.0.1:{_ports[0]}", f"http://127.0.0.1:{_ports[1]}"


def is_running():
    with _lock:
        return _proc is not None and _proc.poll() is None
