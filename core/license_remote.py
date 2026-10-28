"""
بررسی *زنده‌ی* لایسنس مقابل سرویس ابری (Cloudflare Worker).

مدل اجاره‌ای/سخت‌گیر: **هر بار** از سرویس می‌پرسه و هیچی روی دیسک ذخیره
نمی‌کنه (به‌جز license.json نهایی که خروجی تأییدشده رو منعکس می‌کنه). نسخه‌ی
self-host قدیمی (توکنِ آفلاینِ چندروزه‌ی ذخیره‌شده روی دیسک، core/license_client.py)
بازنشسته شده.

## سه حمله‌ای که این فایل می‌بنده

**۱. تعویض کلید راستی‌آزما.** کلید عمومی از core/license_key.py میاد که
داخل کده، نه از فایل. توضیح کاملش همون‌جاست.

**۲. عقب‌بردن ساعت سیستم.** انقضا با ساعت *لوکال* سنجیده نمی‌شه؛ زمان از
هدر `Date` پاسخِ خود سرور خونده می‌شه. ساعت کامپیوتر کاربر هر چی باشه
بی‌اثره.

**۳. قطع‌کردن عمدیِ شبکه.** اگه بررسی انجام نشه، جواب «نه» است، نه «فعلاً
بذار رد شه». هیچ مسیر آفلاینی وجود نداره -- چون هر مهلت آفلاینی دقیقاً
همون چیزیه که با کشیدن کابل شبکه فعال می‌شه.

## چیزی که این *نمی‌تونه* بکنه

نرم‌افزاری که روی کامپیوتر یه نفر دیگه اجرا می‌شه، در نهایت مال اونه. یه
مهاجمِ مصمم با دیس‌اسمبلر همیشه برنده‌ست. هدف این لایه اینه که دور زدنش
از خریدن گرون‌تر باشه، و مهم‌تر: **لغو از راه دور** رو ممکن کنه.
"""

import base64
import email.utils
import hashlib
import json
import os
import platform
import socket
import time
import urllib.error
import urllib.request
import uuid

from core import paths
from core import license_key
from core import logging_setup
from core.paths import get_base_dir

REQUEST_TIMEOUT = 15

MACHINE_ID_FILE = os.path.join(get_base_dir(), "data", "_machine_id")

#: هر چند ثانیه یه بار حین اجرا دوباره چک بشه. بدون بررسی دوره‌ای، کافی
#: بود یه بار با اینترنت بالا بیاد و بعد تا ابد بدون چک کار کنه.
RECHECK_SECONDS = 3600


class LicenseDenied(Exception):
    """لایسنس معتبر نیست -- با دلیلِ قابل‌نمایش به کاربر."""


class LicenseUnreachable(Exception):
    """نشد از سرویس بپرسیم. در حالت سخت‌گیر این هم یعنی «اجازه نداری»."""


def _b64decode(text):
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _open(request):
    """
    درخواست رو می‌فرسته -- اول مستقیم، بعد با پروکسی.

    چرا لازمه: سرویس روی `*.workers.dev` است و از داخل ایران اتصال
    مستقیم بهش توی مرحله‌ی TLS شکست می‌خوره
    (`SSLV3_ALERT_HANDSHAKE_FAILURE`). بدون این مسیر، ربات روی سیستم
    مشتری *همیشه* «نشد وصل بشیم» می‌گرفت -- یعنی لایسنس کاملاً معتبر هم
    هیچ‌وقت تأیید نمی‌شد.

    امنیتش کم نمی‌شه: پروکسی فقط مسیرِ انتقاله. پاسخ با Ed25519 امضا شده،
    پس یه پروکسی خرابکار می‌تونه جلوی اتصال رو بگیره (که نتیجه‌ش «اجازه
    نداری» است) ولی نمی‌تونه لایسنس جعل کنه.
    """
    from core import proxy_state
    return proxy_state.open_direct_then_proxy(request, REQUEST_TIMEOUT, _proxy_url())


def _proxy_url():
    """پروکسی تنظیم‌شده‌ی خود پروژه، اگه هست."""
    try:
        from core import proxy_state
        return proxy_state.get_proxy_url()
    except Exception:
        return None


def _is_service_denial(error):
    """
    این 403/404 پاسخِ خودِ سرویس لایسنسه، یا بلاکِ لایه‌ی شبکه؟

    سرویس همیشه JSON می‌ده ({"ok": false, ...}). کلادفلر موقع
    بلاک‌کردن HTML/متن می‌ده. جداکردنشون یعنی مشتری به‌جای
    «لایسنست لغو شده» پیام درستِ «وصل نشدم» رو می‌بینه.

    در شک، جواب False است: متهم‌کردنِ لایسنسِ سالم بدتر از گفتنِ
    «فعلاً وصل نشدم» است.
    """
    try:
        raw = error.read()
    except Exception:
        return False
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return False
    return isinstance(data, dict) and "ok" in data


def _server_time(headers):
    """
    زمان از دید *سرور*، نه از دید ساعت کامپیوتر کاربر.

    این تنها دلیلیه که عقب‌بردن ساعت سیستم به جایی نمی‌رسه. اگه سرور هدر
    Date نداد، به ساعت لوکال برنمی‌گردیم -- بی‌زمان یعنی غیرقابل‌اعتماد.
    """
    raw = headers.get("Date")
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw).timestamp()
    except (TypeError, ValueError):
        return None


def machine_id():
    """
    یه شناسه‌ی پایدار برای این نصب.

    اول از فایل خونده می‌شه (تا با تغییر سخت‌افزار/شبکه عوض نشه)، و اگه
    نبود یه بار از مشخصات سیستم ساخته و ذخیره می‌شه. برای fingerprint
    (identity_fingerprint) استفاده می‌شه.
    """
    try:
        with open(MACHINE_ID_FILE, "r", encoding="ascii") as f:
            existing = f.read().strip()
        if len(existing) >= 16:
            return existing
    except (FileNotFoundError, OSError):
        pass

    raw = "|".join([
        platform.system(),
        platform.machine(),
        socket.gethostname(),
        str(uuid.getnode()),
    ])
    value = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    try:
        os.makedirs(os.path.dirname(MACHINE_ID_FILE), exist_ok=True)
        with open(MACHINE_ID_FILE, "w", encoding="ascii") as f:
            f.write(value)
    except OSError:
        logging_setup.log_debug("could not persist machine id; it will be regenerated each run")
    return value


def identity_fingerprint(machine, username="", password=""):
    """
    شناسه‌ی این نصب: ماشین + یوزر/پس.

    فقط machine_id کافی نیست -- یه ایمیج کلون‌شده‌ی ویندوز همون فایل
    شناسه رو با خودش می‌بره. با اضافه‌شدن یوزر/پسِ خود ربات، کلون‌کردن
    دیسک به‌تنهایی لایسنس رو منتقل نمی‌کنه.

    پسورد خام هیچ‌وقت فرستاده نمی‌شه؛ فقط هش.
    """
    raw = "|".join([str(machine or ""), str(username or ""), str(password or "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def check(license_key_text, machine, username="", password="", api_url=None):
    """
    یه بررسی زنده. یا dict لایسنس برمی‌گردونه یا استثنا می‌ده.

    خروجی موفق: dict امضاشده شامل expires_at، features، و fingerprint.
    """
    url = api_url or license_key.embedded_api_url()
    if not url:
        raise LicenseDenied("آدرس سرویس لایسنس توی این بیلد تنظیم نشده.")

    verify_key = license_key.embedded_public_key()
    if not verify_key:
        raise LicenseDenied("این بیلد کلید عمومی نداره، پس هیچ لایسنسی قابل تأیید نیست.")

    fingerprint = identity_fingerprint(machine, username, password)
    body = json.dumps({
        "key": str(license_key_text or "").strip(),
        "fingerprint": fingerprint,
        # برای پشتیبانی و تشخیص اشتراک‌گذاری؛ راز نیست.
        "machine": str(machine or "")[:64],
    }).encode("utf-8")

    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "tt-audio-bot/1",
    })

    try:
        with _open(request) as response:
            raw = response.read()
            now = _server_time(response.headers)
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            # 403 هم از خود سرویس میاد (لایسنس واقعاً رد شده) و هم از
            # کلادفلر وقتی خودش درخواست رو بلاک می‌کنه (bot-check/WAF،
            # مثل error 1010). دومی هیچ ربطی به لایسنس نداره، و اگه
            # «لغو شده» گزارش بشه، مشتریِ سالم فکر می‌کنه لایسنسش باطل
            # شده و می‌ره سراغ پشتیبانی.
            if _is_service_denial(e):
                raise LicenseDenied("این لایسنس فعال نیست یا لغو شده.") from e
            raise LicenseUnreachable(
                f"سرویس لایسنس در دسترس نیست (خطای {e.code} از شبکه، نه از لایسنس)."
            ) from e
        raise LicenseUnreachable(f"سرویس لایسنس خطا داد ({e.code}).") from e
    except Exception as e:
        raise LicenseUnreachable(f"به سرویس لایسنس وصل نشد: {type(e).__name__}") from e

    if now is None:
        raise LicenseDenied("سرویس لایسنس زمان معتبری برنگردوند.")

    try:
        envelope = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        raise LicenseUnreachable("پاسخ سرویس لایسنس خوانا نبود.") from e

    payload = _verify(envelope, verify_key)

    if payload.get("fingerprint") != fingerprint:
        raise LicenseDenied("این لایسنس برای این دستگاه صادر نشده.")

    expires_at = payload.get("expires_at")
    if expires_at is not None and float(expires_at) < now:
        raise LicenseDenied("اعتبار لایسنس تموم شده.")

    if payload.get("revoked"):
        raise LicenseDenied("این لایسنس لغو شده.")

    payload["_checked_at"] = time.monotonic()
    return payload


def _verify(envelope, verify_key_b64):
    """
    امضای Ed25519 روی *بایت‌های دقیقِ* payload.

    payload به‌صورت رشته‌ی base64 امضا و منتقل می‌شه، نه به‌صورت آبجکت
    JSON: اگه سمت ما دوباره از dict به JSON تبدیلش می‌کردیم، هر تفاوت
    کوچیکی توی ترتیب کلیدها یا فاصله‌ها امضا رو می‌شکست.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        payload_b64 = envelope["payload"]
        signature = _b64decode(envelope["signature"])
        payload_bytes = _b64decode(payload_b64)
    except (KeyError, TypeError, ValueError) as e:
        raise LicenseDenied("پاسخ سرویس لایسنس ساختار درستی نداشت.") from e

    try:
        public = ed25519.Ed25519PublicKey.from_public_bytes(_b64decode(verify_key_b64))
        public.verify(signature, payload_bytes)
    except InvalidSignature as e:
        # این یعنی یا پاسخ دستکاری شده یا از سرویس ما نیومده.
        raise LicenseDenied("امضای لایسنس معتبر نیست.") from e
    except Exception as e:
        raise LicenseDenied(f"بررسی امضا ممکن نشد: {type(e).__name__}") from e

    try:
        return json.loads(payload_bytes.decode("utf-8"))
    except ValueError as e:
        raise LicenseDenied("محتوای لایسنس خوانا نبود.") from e


def check_or_exit(license_key_text, machine, username="", password="", api_url=None,
                  on_message=print):
    """
    همون check، ولی برای نقطه‌ی شروع برنامه: یا dict می‌ده یا False.

    در حالت سخت‌گیر، «نشد وصل بشیم» هم مثل «اجازه نداری» رفتار می‌کنه --
    ولی پیامش فرق می‌کنه، چون برای کاربرِ درست‌کار این دوتا کاملاً دو
    چیزن و نباید فکر کنه لایسنسش باطل شده.
    """
    try:
        return check(license_key_text, machine, username, password, api_url)
    except LicenseDenied as e:
        on_message(f"[License] {e}")
        return False
    except LicenseUnreachable as e:
        on_message(f"[License] {e}")
        on_message("[License] بدون اتصال به اینترنت، ربات اجرا نمی‌شه.")
        return False


def write_license_files(payload, bot_dirs):
    """
    نتیجه‌ی بررسی ریموت رو به `license.json` هر ربات تبدیل می‌کنه.

    بدون این مرحله، محدودیت امکانات فقط حرف بود: بررسی ریموت می‌گفت «این
    لایسنس فقط مستند داره» ولی ربات همچنان license.json قدیمیِ روی دیسک
    رو می‌خوند و همه‌ی امکانات رو باز می‌کرد. اینجا منبع حقیقت از دیسک به
    پاسخِ امضاشده منتقل می‌شه.

    فایل هر بار بازنویسی می‌شه، پس دستکاریِ دستیِ کاربر با اولین اجرای
    بعدی پاک می‌شه.
    """
    import os

    written = []
    features = payload.get("features")

    # license_gate روی `services`/`commands` تصمیم می‌گیره، نه روی کدهای
    # امکانات. پس کدها همین‌جا باز می‌شن -- وگرنه لیست امکانات توی فایل
    # می‌نشست و گیت با ندیدن services/commands همه‌چیز رو باز می‌کرد.
    services = commands = None
    if features is not None:
        try:
            from licensing import catalog
            services = catalog.allowed_services(features)
            commands = catalog.allowed_commands(features)
        except Exception:
            logging_setup.log_debug("could not expand licence features; locking down")
            # نتونستیم باز کنیم یعنی نمی‌دونیم چی مجازه. امن‌ترین حالت
            # «هیچی» است، نه «همه‌چیز».
            services, commands = [], []

    document = {
        "key": payload.get("key"),
        "status": "active",
        "starts_at": int(payload.get("issued_at") or time.time()),
        "expires_at": int(payload.get("expires_at") or 0),
        "grace_until": None,
        "max_bots": int(payload.get("max_bots") or 1),
        "max_users": int(payload.get("max_users") or 1),
        # None یعنی «همه‌ی امکانات»؛ لیست یعنی دقیقاً همین‌ها.
        "features": list(features) if features is not None else None,
        "services": list(services) if services is not None else None,
        "commands": sorted(commands) if commands is not None else None,
        "managed": True,
        "source": "remote",
    }

    for bot_dir in bot_dirs:
        if not os.path.isdir(bot_dir):
            continue
        path = os.path.join(bot_dir, "license.json")
        try:
            paths.write_json_atomic(path, document, indent=2)
            written.append(path)
        except OSError:
            logging_setup.log_debug(f"could not write {path}")
    return written


def needs_recheck(payload, interval=RECHECK_SECONDS):
    """آیا وقتشه دوباره بپرسیم؟ (برای بررسی دوره‌ای حین اجرا)"""
    if not payload:
        return True
    last = payload.get("_checked_at")
    if last is None:
        return True
    return (time.monotonic() - last) >= interval
