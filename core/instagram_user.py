"""
Instagram sessions per-user (مثل accounts.py برای sf).

هر کاربر یک session خودش داره (کاکی + metadata). کاکی encrypt شده روی دیسک با AES-256.

فایل: data/<host>_<port>/<bot>/instagram_sessions/<username>.json
"""

import hashlib
import json
import os
import re
import threading
import time
from collections import defaultdict
from cryptography.fernet import Fernet, InvalidToken

from core import paths
from core import accounts
from core import logging_setup
from core import proxy_state

_PBKDF2_ITERATIONS = accounts._PBKDF2_ITERATIONS
_SESSIONS_DIR = None  # will be set per-bot
_login_attempts = defaultdict(list)  # {username: [timestamp, ...]}
_login_lock = threading.Lock()
_MAX_LOGIN_ATTEMPTS = 3
_LOGIN_ATTEMPT_WINDOW = 900  # 15 minutes
_SESSION_TIMEOUT = 2592000  # 30 days

def set_bot_dir(bot_dir):
    """هر ربات باید این رو صدا بزند (از bot.server_dir)."""
    global _SESSIONS_DIR
    _SESSIONS_DIR = os.path.join(bot_dir, "instagram_sessions")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

def valid_username(username):
    """یوزرنیم اینستاگرام (حروف/عدد/نقطه/آندرلاین) -- اسمِ فایل هم هست، پس
    چیزی مثل ../x نباید از اینجا رد بشه."""
    return bool(username) and bool(_USERNAME_RE.match(username))

def _sessions_path(username):
    if _SESSIONS_DIR is None:
        raise RuntimeError("set_bot_dir() not called yet")
    if not valid_username(username):
        raise ValueError("invalid instagram username")
    return os.path.join(_SESSIONS_DIR, f"{username}.json")

# هش پسورد همون تابعِ حساب‌های مشترکه (یه پیاده‌سازی، نه دو کپی).
_hash_password = accounts._hash_password
_verify_password = accounts._verify_password

def _get_encryption_key(password, salt):
    """Generate a Fernet-compatible encryption key from password + salt."""
    import base64
    key_material = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return base64.urlsafe_b64encode(key_material[:32])

def _encrypt_cookie(cookie_str, password, salt):
    """Encrypt cookie using AES-128-CBC (via Fernet)."""
    try:
        key = _get_encryption_key(password, salt)
        cipher = Fernet(key)
        encrypted = cipher.encrypt(cookie_str.encode())
        return encrypted.decode()
    except Exception as e:
        logging_setup.log_debug(f"encryption failed: {e}")
        raise

def _decrypt_cookie(encrypted, password, salt):
    """Decrypt cookie using AES-128-CBC (via Fernet)."""
    try:
        key = _get_encryption_key(password, salt)
        cipher = Fernet(key)
        decrypted = cipher.decrypt(encrypted.encode())
        return decrypted.decode()
    except (InvalidToken, Exception) as e:
        logging_setup.log_debug(f"decryption failed: {e}")
        return None

def _check_login_attempt(username):
    """Check if user exceeded login attempt limit. Returns (allowed, wait_seconds)."""
    with _login_lock:
        now = time.time()
        attempts = _login_attempts[username]
        # Remove old attempts outside the window
        attempts[:] = [t for t in attempts if now - t < _LOGIN_ATTEMPT_WINDOW]

        if len(attempts) >= _MAX_LOGIN_ATTEMPTS:
            oldest = min(attempts)
            wait_seconds = int(_LOGIN_ATTEMPT_WINDOW - (now - oldest)) + 1
            return False, wait_seconds

        attempts.append(now)
        return True, 0

def _clear_login_attempts(username):
    """Clear login attempts after successful login."""
    with _login_lock:
        _login_attempts.pop(username, None)

def login_or_create(username, password):
    """
    Username/password رو لاگین می‌کنه (دریافت کاکی از instagrapi).
    اگه session موجود بود و password درست بود، session رو برمی‌گرداند.
    اگه نه، نیاز به instagrapi داره.

    برمی‌گردونه: {
        "status": "logged_in" / "created" / "wrong_password" / "rate_limited" / "instagrapi_unavailable",
        "session": {...} یا None,
        "wait_seconds": N (فقط rate_limited وقت)
    }
    """
    # Check rate limiting
    allowed, wait_sec = _check_login_attempt(username)
    if not allowed:
        return {"status": "rate_limited", "wait_seconds": wait_sec}

    path = _sessions_path(username)

    # اگه session موجود باشه
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Check session timeout
            created_at = data.get("created_at", 0)
            if time.time() - created_at > _SESSION_TIMEOUT:
                logging_setup.log_debug(f"instagram session expired for {username}")
                delete_session(username)
                return {"status": "session_expired"}

            stored_salt = data.get("password_salt")
            stored_hash = data.get("password_hash")
            if stored_salt and stored_hash:
                if not _verify_password(password, stored_salt, stored_hash):
                    return {"status": "wrong_password"}
                _clear_login_attempts(username)
                if not data.get("cookie_bot"):
                    # سشنِ قدیمی (فقط با رمز رمزگذاری شده): یه نسخه‌ی قابل‌استفاده
                    # برای دستورهای بعدی هم بساز.
                    cookie_str = _decrypt_cookie(data.get("cookie_encrypted", ""), password, stored_salt)
                    if cookie_str:
                        data = _with_bot_copy(data, cookie_str)
                        _write_session(username, data)
                return {"status": "logged_in", "session": data}
            # سشنِ ساخته‌شده با sessionid رمزی برای تأیید نداره: لاگینِ تازه با رمز.
        except Exception as e:
            logging_setup.log_debug(f"reading instagram session failed: {e}")
            return {"status": "wrong_password"}

    # session نیست - باید از instagrapi login کنیم
    from core import instagram_api
    try:
        client = instagram_api.new_client()
        if client is None:
            return {"status": "instagrapi_unavailable"}
        client.login(username, password)
        # JSON (نه str()): instagram_api.load_client_from_session با json.loads
        # می‌خوندش و نسخه‌ی str() همیشه بی‌صدا شکست می‌خورد.
        cookie_str = json.dumps(client.get_settings())

        salt, password_hash = _hash_password(password)
        session_data = _with_bot_copy({
            "username": username,
            "password_salt": salt,
            "password_hash": password_hash,
            "cookie_encrypted": _encrypt_cookie(cookie_str, password, salt),
            "created_at": time.time(),
            "auth": "password",
        }, cookie_str)

        _write_session(username, session_data)
        _clear_login_attempts(username)
        return {"status": "created", "session": session_data}
    except Exception as e:
        logging_setup.log_debug(f"instagram login failed: {e}")
        return _failure_result(e)


def login_with_sessionid(sessionid, who="sessionid"):
    """
    لاگین با کوکیِ sessionid (جایگزینِ مطمئن‌تر از رمز).

    چرا: اینستاگرام لاگینِ با رمز رو از IPِ سرور/پروکسی اغلب می‌بنده
    (challenge، بلاک، پاسخِ خراب). sessionid رو کاربر از مرورگرِ خودش
    (که قبلاً اونجا لاگینه) برمی‌داره، پس هیچ ورودِ تازه‌ای از IPِ مشکوک
    اتفاق نمی‌افته. رمز هم هرگز به ربات نمی‌رسه.

    who: کلیدِ محدودیتِ تلاش (معمولاً یوزرنیمِ تیم‌تاک) تا یه نفر برای همه سقف پر نکنه.

    برمی‌گردونه: {"status": "created", "username": ...} یا
    {"status": <دلیل>, "error_class": ...}.
    """
    sessionid = _clean_sessionid(sessionid)
    if not sessionid:
        return {"status": "bad_sessionid"}
    allowed, wait_sec = _check_login_attempt(f"sid:{who}")
    if not allowed:
        return {"status": "rate_limited", "wait_seconds": wait_sec}
    from core import instagram_api
    try:
        client = instagram_api.new_client()
        if client is None:
            return {"status": "instagrapi_unavailable"}
        client.login_by_sessionid(sessionid)
        username = getattr(client, "username", None)
        if not valid_username(username):
            return {"status": "session_rejected"}
        session_data = _with_bot_copy({
            "username": username,
            "created_at": time.time(),
            "auth": "sessionid",
        }, json.dumps(client.get_settings()))
        _write_session(username, session_data)
        _clear_login_attempts(f"sid:{who}")
        return {"status": "created", "username": username, "session": session_data}
    except Exception as e:
        logging_setup.log_debug(f"instagram sessionid login failed: {e}")
        return _failure_result(e)


def _clean_sessionid(value):
    """sessionid رو از فاصله/کوتیشن تمیز می‌کنه. دو شکلِ کپی‌شده‌ی مرورگر
    (با %3A یا با :) هر دو به شکلِ کوکیِ خام (%3A) برمی‌گردن. نامعتبر -> None."""
    value = (value or "").strip().strip("\"'")
    value = value.replace(":", "%3A")
    if len(value) < 31 or not re.match(r"^\d+%3A[A-Za-z0-9%_\-]+$", value):
        return None
    return value


# ---------------------------------------------------------------------------
# کلیدِ ذخیره‌ی سشن بدونِ رمز
#
# سشنِ اینستاگرام باید برای دستورهای بعدی (rl/lr/iu/...) بدونِ پرسیدنِ دوباره‌ی
# رمز/PIN در دسترس باشه، پس کلیدش نمی‌تونه از چیزی باشه که فقط کاربر می‌دونه.
# کلید یه رازِ تصادفیِ مخصوصِ هر ربات (instagram_sessions/.key) به‌علاوه‌ی salt
# هر سشنه.
#
# معامله‌ی صادقانه: فایلِ سشن به‌تنهایی (مثلاً داخلِ یه بکاپ یا اسکرین‌شات)
# بی‌فایده‌ست، ولی کسی که هم پوشه‌ی instagram_sessions و هم .key رو داره
# (یعنی دسترسیِ کاملِ فایلیِ سرور) می‌تونه سشن رو باز کنه. این همون سطحِ
# اعتمادیه که به توکن ربات و خودِ سرور داریم. PIN کاربر امن‌تره ولی یعنی
# هر دستور باید PIN بخواد، که برای ربات صوتیِ چندنفره قابل‌استفاده نیست.
# ---------------------------------------------------------------------------

def _bot_secret():
    path = os.path.join(_SESSIONS_DIR, ".key")
    try:
        with open(path, "r", encoding="utf-8") as f:
            secret = f.read().strip()
        if secret:
            return secret
    except OSError:
        pass
    os.makedirs(_SESSIONS_DIR, exist_ok=True)
    secret = os.urandom(32).hex()
    with open(path, "w", encoding="utf-8") as f:
        f.write(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret

def _with_bot_copy(data, cookie_str):
    """data رو با نسخه‌ی رمزشده با کلیدِ ربات (cookie_bot) برمی‌گردونه."""
    salt = os.urandom(16).hex()
    return dict(data, bot_salt=salt, cookie_bot=_encrypt_cookie(cookie_str, _bot_secret(), salt))

def load_saved_session(username):
    """
    (session_data, cookie_str) با کلیدِ ربات، یا (None, None) اگه سشنی
    نیست/منقضی شده/خراب شده. برای هر دو نوعِ لاگین (رمز و sessionid).
    """
    if _SESSIONS_DIR is None or not valid_username(username):
        return None, None
    try:
        with open(_sessions_path(username), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None, None
    if time.time() - data.get("created_at", 0) > _SESSION_TIMEOUT:
        delete_session(username)
        return None, None
    if not data.get("cookie_bot") or not data.get("bot_salt"):
        return None, None
    cookie_str = _decrypt_cookie(data["cookie_bot"], _bot_secret(), data["bot_salt"])
    return (data, cookie_str) if cookie_str else (None, None)


# کلاسِ استثنای instagrapi -> دلیل. با نامِ کلاس (نه import) چون instagrapi
# تنبل لود می‌شه؛ و با MRO چون خیلی از استثناها زیرکلاسِ هم‌ان (مثلاً
# ChallengeRequired زیرِ ChallengeError) و اول دقیق‌ترین کلاس جواب می‌ده.
_FAILURE_BY_CLASS = {
    "BadPassword": "wrong_password",
    "BadCredentials": "wrong_password",
    "TwoFactorRequired": "two_factor_required",
    "ChallengeRequired": "challenge_required",
    "ChallengeError": "challenge_required",
    "CaptchaChallengeRequired": "challenge_required",
    "PleaseWaitFewMinutes": "instagram_rate_limited",
    "RateLimitError": "instagram_rate_limited",
    "ClientThrottledError": "instagram_rate_limited",
    "ReloginAttemptExceeded": "instagram_rate_limited",
    "ClientConnectionError": "network_error",
    "ClientRequestTimeout": "network_error",
    "ClientIncompleteReadError": "network_error",
    "ProxyAddressIsBlocked": "ip_blocked",
    "SentryBlock": "ip_blocked",
    "ClientForbiddenError": "ip_blocked",
    "ClientJSONDecodeError": "bad_response",
    "FeedbackRequired": "action_blocked",
    "LoginRequired": "session_rejected",
    "ClientLoginRequired": "session_rejected",
    "ClientUnauthorizedError": "session_rejected",
    "AgeEligibilityError": "age_restricted",
}

def login_failure_status(exc):
    """
    دلیلِ واقعیِ شکستِ لاگین. قبلاً هر شکستی (رمز غلط، دومرحله‌ای،
    challenge، محدودیت، قطعیِ شبکه) «instagrapi_unavailable» برمی‌گشت، یعنی
    کاربر پیامِ «کتابخونه نصب نیست» می‌دید درحالی‌که نصب بود.
    """
    for cls in type(exc).__mro__:
        status = _FAILURE_BY_CLASS.get(cls.__name__)
        if status:
            return status
    if isinstance(exc, (OSError, ConnectionError)):
        return "network_error"
    return "login_failed"

def safe_class_name(exc):
    """نامِ کلاسِ استثنا برای عیب‌یابی -- هرگز متنِ پیامش (ممکنه URL/توکن
    داشته باشه). فقط حروف/عدد/آندرلاین و کوتاه."""
    return re.sub(r"[^A-Za-z0-9_]", "", type(exc).__name__)[:40] or "Error"

def _failure_result(exc):
    return {"status": login_failure_status(exc), "error_class": safe_class_name(exc)}

def get_session(username, password):
    """
    Session رو load می‌کنه و اگه password درست بود، decrypt شده‌ی cookie رو برمی‌گردونه.
    """
    path = _sessions_path(username)
    if not os.path.isfile(path):
        return None, None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check session timeout
        created_at = data.get("created_at", 0)
        if time.time() - created_at > _SESSION_TIMEOUT:
            logging_setup.log_debug(f"instagram session expired for {username}")
            delete_session(username)
            return None, None

        if not _verify_password(password, data.get("password_salt", ""), data.get("password_hash", "")):
            return None, None

        encrypted_cookie = data.get("cookie_encrypted")
        if not encrypted_cookie:
            return None, None

        salt = data.get("password_salt")
        cookie_str = _decrypt_cookie(encrypted_cookie, password, salt)
        if not cookie_str:
            return None, None

        return data, cookie_str
    except Exception as e:
        logging_setup.log_debug(f"loading instagram session failed: {e}")
        return None, None

def _write_session(username, data):
    """Write session data with atomic write (temp file + rename)."""
    path = _sessions_path(username)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    try:
        paths.write_json_atomic(path, data)
    except Exception as e:
        logging_setup.log_debug(f"writing instagram session failed: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise

def delete_session(username):
    """session رو حذف می‌کنه."""
    path = _sessions_path(username)
    try:
        os.remove(path)
    except OSError:
        pass
