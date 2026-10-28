"""
نوشتن/خوندن لایسنس‌ها روی Cloudflare KV، مستقیم از داخل ربات فروش.

## چرا این فایل

بدون این، صدور هر لایسنس دو مرحله‌ی دستی داشت: ساختن کلید با
`manage.py rental`، و بعد کپی/پیست کردن یه دستور `wrangler kv put` توی
ترمینال. یعنی ربات فروش نمی‌تونست واقعاً «بفروشه» -- فقط پیشنهاد
می‌داد و بقیه‌اش دست آدم بود.

## چرا توکن API و نه توکن خود رنگلر

توکن OAuth رنگلر **یک‌ساعته**ست و با refresh_token تازه می‌شه. برای یه
ربات که هفته‌ها بالاست این یعنی خرابیِ نیمه‌شب. توکن API اختصاصی
عمر طولانی داره و دسترسیش رو هم می‌شه فقط به KV محدود کرد -- پس حتی
اگه لو بره، کسی به بقیه‌ی حساب کلادفلرت نمی‌رسه.

ساختنش: dash.cloudflare.com -> My Profile -> API Tokens -> Create Token
با دسترسی «Workers KV Storage: Edit» روی همون حساب.

بعد توی data/licensing/config.json:

    "cloudflare_account_id": "...",
    "cloudflare_kv_namespace": "...",
    "cloudflare_api_token": "..."

یا متغیرهای محیطی CF_ACCOUNT_ID / CF_KV_NAMESPACE / CF_API_TOKEN.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from core import logging_setup

API_BASE = "https://api.cloudflare.com/client/v4"
TIMEOUT = 20


class CloudflareError(Exception):
    pass


class NotConfigured(CloudflareError):
    """هنوز مشخصات کلادفلر تنظیم نشده -- خطای واقعی نیست، فقط خاموشه."""


class RentalResetRefused(CloudflareError):
    """لایسنس به یه دستگاه بایند شده و force داده نشده."""


def _setting(key, env_name):
    value = os.environ.get(env_name)
    if value and value.strip():
        return value.strip()
    from licensing import config
    return str(config.get(key) or "").strip()


def settings():
    """(account_id, namespace_id, api_token) — هر کدوم که نباشه، رشته‌ی خالی."""
    return (
        _setting("cloudflare_account_id", "CF_ACCOUNT_ID"),
        _setting("cloudflare_kv_namespace", "CF_KV_NAMESPACE"),
        _setting("cloudflare_api_token", "CF_API_TOKEN"),
    )


def available():
    """آیا می‌تونیم روی KV بنویسیم؟"""
    return all(settings())


def missing_settings():
    """چی کمه — برای پیام راهنما به ادمین."""
    account, namespace, token = settings()
    missing = []
    if not account:
        missing.append("cloudflare_account_id")
    if not namespace:
        missing.append("cloudflare_kv_namespace")
    if not token:
        missing.append("cloudflare_api_token")
    return missing


def _request(method, path, body=None, raw_response=False):
    account, namespace, token = settings()
    if not all((account, namespace, token)):
        raise NotConfigured("مشخصات کلادفلر تنظیم نشده: " + ", ".join(missing_settings()))

    url = f"{API_BASE}/accounts/{account}/storage/kv/namespaces/{namespace}{path}"
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _open(request) as response:
            payload = response.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))
            detail = "; ".join(x.get("message", "") for x in (detail.get("errors") or []))
        except Exception:
            pass
        raise CloudflareError(f"کلادفلر خطا داد ({e.code}) {detail}".strip()) from e
    except Exception as e:
        raise CloudflareError(f"به کلادفلر وصل نشد: {type(e).__name__}") from e

    if raw_response:
        return payload
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except ValueError:
        return {}


def _open(request):
    """
    مثل مسیر بررسی لایسنس: اول مستقیم، بعد با پروکسی.

    api.cloudflare.com هم از بعضی شبکه‌ها مستقیم در دسترس نیست، و بدون
    این مسیر ربات فروش روی سرور ایران اصلاً نمی‌تونست لایسنس صادر کنه.
    """
    try:
        from licensing import config
        proxy_url = config.proxy_url()
    except Exception:
        proxy_url = None
    from core import proxy_state
    return proxy_state.open_direct_then_proxy(request, TIMEOUT, proxy_url)


# ------------------------------------------------------------------ KV

def put(key, value):
    """یه مقدار روی KV می‌نویسه. value می‌تونه dict یا رشته باشه."""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    path = f"/values/{urllib.parse.quote(key, safe='')}"
    # این endpoint مقدار رو خام می‌خواد، نه JSON-wrapped.
    account, namespace, token = settings()
    url = f"{API_BASE}/accounts/{account}/storage/kv/namespaces/{namespace}{path}"
    request = urllib.request.Request(
        url, data=text.encode("utf-8"), method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"})
    try:
        with _open(request) as response:
            response.read()
        return True
    except urllib.error.HTTPError as e:
        raise CloudflareError(f"نوشتن روی KV نشد ({e.code})") from e
    except Exception as e:
        raise CloudflareError(f"نوشتن روی KV نشد: {type(e).__name__}") from e


def get(key):
    """مقدار یه کلید، یا None اگه نبود."""
    path = f"/values/{urllib.parse.quote(key, safe='')}"
    try:
        raw = _request("GET", path, raw_response=True)
    except CloudflareError as e:
        if "404" in str(e):
            return None
        raise
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return raw.decode("utf-8", "replace")


def delete(key):
    """یه کلید رو پاک می‌کنه. True یعنی پاک شد یا از اول نبود."""
    path = f"/values/{urllib.parse.quote(key, safe='')}"
    try:
        _request("DELETE", path)
        return True
    except CloudflareError as e:
        if "404" in str(e):
            return True
        raise


def check_connection():
    """
    (ok, detail) — واقعاً یه درخواست می‌زنه.

    برای --check و پنل ادمین: «تنظیم شده» با «کار می‌کنه» فرق داره، و
    فهمیدن این تفاوت موقع صدور لایسنس خیلی دیر است.
    """
    if not available():
        return False, "تنظیم نشده: " + ", ".join(missing_settings())
    try:
        account, namespace, _token = settings()
        _request("GET", "/keys?limit=1")
        return True, f"وصل شد (namespace {namespace[:8]}…)"
    except Exception as e:
        return False, str(e)


def licence_key_name(license_key):
    """اسم کلید روی KV برای یه لایسنس."""
    return f"license:{str(license_key or '').strip().upper()}"


def seen_key_name(license_key):
    return f"seen:{str(license_key or '').strip().upper()}"


def write_licence(license_key, expires_at, features=None, max_bots=1, note=""):
    """
    یه لایسنس رو روی KV می‌نویسه (یا به‌روز می‌کنه).

    fingerprint عمداً خالی می‌مونه: لایسنس به **اولین دستگاهی که فعالش
    کنه** بایند می‌شه، پس لازم نیست شناسه‌ی کامپیوتر مشتری رو از قبل
    بدونی.
    """
    record = {
        "fingerprint": None,
        "expires_at": int(expires_at),
        "features": list(features) if features is not None else None,
        "max_bots": int(max_bots),
        "revoked": False,
        "note": str(note or ""),
    }
    put(licence_key_name(license_key), record)
    return record


def revoke_licence(license_key, remove=False):
    """
    لایسنس رو می‌خوابونه.

    remove=False (پیش‌فرض) فقط پرچم revoked رو می‌ذاره -- رکورد می‌مونه
    پس بعداً می‌شه فهمید چی بوده و به کی داده شده. remove=True کاملاً
    پاکش می‌کنه.
    """
    name = licence_key_name(license_key)
    if remove:
        delete(name)
        delete(seen_key_name(license_key))
        return True

    record = get(name)
    if not isinstance(record, dict):
        return False
    record["revoked"] = True
    put(name, record)
    return True


def read_licence(license_key):
    """رکوردِ خامِ یه لایسنسِ اجاره‌ای، یا None اگه روی KV نیست."""
    record = get(licence_key_name(license_key))
    return record if isinstance(record, dict) else None


def extend_licence(license_key, days, unrevoke=False):
    """
    اعتبارِ یه لایسنسِ اجاره‌ای رو `days` روز جلو می‌بره -- بدونِ دست‌زدن
    به fingerprint، تاریخچه‌ی دیده‌شده، امکانات، یا هر فیلدِ دیگه.

    برخلافِ write_licence (که fingerprint رو خالی می‌کنه، یعنی مشتری باید
    دوباره بایند بشه) و reset_rental (که علاوه بر اون تاریخچه رو هم پاک
    می‌کنه)، این فقط برای «عذرخواهی/جبران» یا تمدیدِ عادیه: دستگاهِ مشتری
    همون‌جوری که بود می‌مونه.

    مبنای جمع‌کردنِ روزها: اگه لایسنس هنوز منقضی نشده، از expires_at
    فعلیش؛ اگه منقضی/لغو شده، از همین الان -- وگرنه لایسنسِ منقضی‌شده با
    ۲ روز جبران هنوز منقضی به‌حساب می‌اومد.

    unrevoke=True هم پرچمِ revoked رو برمی‌داره (برای «اشتباهی لغو شده
    بود، جبران کن و برگردون»).
    """
    import time as _time

    name = licence_key_name(license_key)
    record = get(name)
    if not isinstance(record, dict):
        return None

    now = int(_time.time())
    base = record.get("expires_at") or 0
    if record.get("revoked") or base <= now:
        base = now
    record["expires_at"] = int(base) + int(days) * 86400
    if unrevoke:
        record["revoked"] = False
    put(name, record)
    return record


def machines_seen(license_key):
    """
    دستگاه‌هایی که این لایسنس رو چک کردن.

    بیشتر از یکی یعنی لایسنس داره بین چند نفر پخش می‌شه. عمداً خودکار
    مسدود نمی‌شه -- تصمیمش با آدمه.
    """
    data = get(seen_key_name(license_key))
    return data if isinstance(data, dict) else {}


def reset_rental(license_key, days=30, force=False):
    """
    یه لایسنس اجاره‌ای رو به حالت دست‌نخورده برمی‌گردونه: fingerprint خالی
    (منتظر اولین دستگاه)، اعتبار تازه، و تاریخچه‌ی دستگاه‌های دیده‌شده پاک.
    امکانات، max_bots و یادداشت دست‌نخورده می‌مونن.

    این تابع خودش چک «پروتکتد» رو نمی‌کنه -- عمداً: اون تصمیم به دیدنِ خودِ
    کلید نیاز نداره، `licensing.config.is_protected_licence` جواب می‌ده، و
    هم `manage.py` هم هندلر تلگرام قبل از صدازدنِ این تابع همونو صدا
    می‌زنن. تکرارش اینجا فقط دو نسخه از یه تصمیم می‌ساخت.

    خروجی: dict {"key", "was_bound", "expires_at"}.
    خطا:
      NotConfigured        کلادفلر تنظیم نشده
      CloudflareError      کلید روی KV نیست (پیام == "not_found")
      RentalResetRefused   بایند شده و force=False
    """
    key = str(license_key or "").strip().upper()
    record = get(licence_key_name(key))
    if not isinstance(record, dict):
        raise CloudflareError("not_found")

    was_bound = bool(record.get("fingerprint"))
    if was_bound and not force:
        raise RentalResetRefused("bound")

    import time as time_module

    expires_at = int(time_module.time()) + int(days) * 86400
    write_licence(key, expires_at, features=record.get("features"),
                 max_bots=record.get("max_bots") or 1, note=record.get("note") or "")
    # تاریخچه‌ی دستگاه‌ها هم باید بره، وگرنه دفعه‌ی بعد که ماشینِ مشتری وصل
    # می‌شه، کنار fingerprint های تستِ ادمین می‌شینه و مثل لایسنسِ
    # پخش‌شده به نظر می‌رسه.
    try:
        delete(seen_key_name(key))
    except Exception:
        pass
    return {"key": key, "was_bound": was_bound, "expires_at": expires_at}
