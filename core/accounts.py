"""
حساب شخصی کاربر (نه حساب TeamTalk؛ یه لایسنس username/password کاملاً
جدا و مستقل، فقط برای قفل‌کردن فروریت/تنظیمات شخصی هرکس) -- دستورات
sf/sfl/rf/af/aff/of از این ماژول استفاده می‌کنن.

## مدل ذخیره‌سازی (خصوصی/عمومی)

هر حساب پیش‌فرض «خصوصی» و مخصوص همون سروریه که توش ساخته شده:
    data/<host>_<port>/accounts/<username>.json

با دستور «of» می‌شه حساب رو «عمومی» کرد: اون‌موقع از فایل محلیِ سرور به یه
فایل *سراسری* (مستقل از هر سروری) منتقل می‌شه:
    data/_global_accounts/<username>.json

جستجوی لاگین (find_account) همیشه اول توی حساب‌های *عمومی* سراسری می‌گرده
(چون این‌ها از همه‌جا در دسترسن)، بعد توی حساب‌های *خصوصیِ همین سرور*. یعنی
یه حساب عمومی از هر سروری قابل لاگینه، ولی یه حساب خصوصی فقط روی همون
سروری که ساخته شده.

موقع عمومی‌کردن (of)، اگه یه حساب عمومیِ *دیگه‌ای* (متعلق به یه پسورد/فرد
دیگه) از قبل همین username رو داشته باشه، رد می‌شه و از کاربر خواسته
می‌شه یه اسم دیگه انتخاب کنه (تا حساب کس دیگه‌ای رو نگیره/خراب نکنه).

نکته‌ی مهم درباره‌ی این چک: فقط *لحظه‌ی* اجرای «of» بررسی می‌شه، نه به‌صورت
دائم. یعنی اگه یه نفر روی سرورِ دیگه‌ای از قبل (بدون اطلاع از این) یه
username یکسان رو *خصوصی* ساخته باشه، و بعداً یکی دیگه همون اسم رو جای
دیگه عمومی کنه، حساب خصوصیِ اون نفر اول *سایه‌زده* می‌شه (find_account
دیگه بهش نمی‌رسه، چون عمومی‌ها همیشه اولویت دارن) -- ولی هرگز باز نمی‌شه،
چون پسوردش با پسورد حساب عمومی فرق داره (login_or_register روی
wrong_password می‌ایسته، نه اینکه اشتباهی وارد حساب اون یکی بشه). این یه
محدودیت شناخته‌شده‌ی طراحیه (چک کردن *همه‌ی* سرورها موقع هر «of» هزینه‌بر و
برخلاف همون حریم‌خصوصیِ پیش‌فرضه)، نه یه حفره‌ی امنیتی -- کسی به حساب کس
دیگه دسترسی پیدا نمی‌کنه، فقط ممکنه لازم باشه اسم دیگه‌ای انتخاب کنه.

## امنیت پسورد

پسورد هیچ‌وقت متن خام ذخیره نمی‌شه؛ با PBKDF2-HMAC-SHA256 (نمک تصادفی،
۱۰۰هزار تکرار -- از کتابخونه‌ی استاندارد پایتون، بدون وابستگی اضافه) هش
می‌شه. این یه قفل ساده‌ی شخصیه، نه یه سیستم احراز هویت با امنیت بالا؛ توی
مستندات کاربر باید روشن باشه که این پسورد ربطی به پسورد اکانت TeamTalk
نداره و نباید همون رو دوباره استفاده کنه.

## نشست (session) لاگین

بعد از یه «sf username password» موفق، توی حافظه (نه دیسک) یادمون می‌مونه
که این nickname/uid توی این پروسه‌ی ربات لاگین کدوم حسابه (bot.sf_sessions).
با ری‌استارت ربات این نشست از بین می‌ره و کاربر باید دوباره لاگین کنه --
عمداً ساده نگه داشته شده چون خودِ sf command سبکه و دوباره زدنش هزینه‌ای
نداره.
"""

import hashlib
import hmac
import json
import os
import re
import time

from core import paths
from core import logging_setup
from core.paths import get_base_dir

GLOBAL_ACCOUNTS_DIR = os.path.join(get_base_dir(), "data", "_global_accounts")

_PBKDF2_ITERATIONS = 100_000
_VALID_USERNAME = re.compile(r"^[a-zA-Z0-9_\-.]{3,32}$")


def is_valid_username(name):
    return bool(_VALID_USERNAME.match(name or ""))


def _hash_password(password, salt=None):
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS).hex()
    return salt, digest


def _verify_password(password, salt, digest):
    _, candidate = _hash_password(password, salt)
    return hmac.compare_digest(candidate, digest)


def _private_dir(bot):
    return os.path.join(bot.server_dir, "accounts")


def _private_path(bot, username):
    return os.path.join(_private_dir(bot), f"{username}.json")


def _global_path(username):
    return os.path.join(GLOBAL_ACCOUNTS_DIR, f"{username}.json")


def _read(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logging_setup.log_debug(f"reading account file failed ({path})")
        return None


def _write(path, data):
    paths.write_json_atomic(path, data, makedirs=True, per_process_tmp=True)


def _new_account_data(username, password):
    salt, digest = _hash_password(password)
    return {
        "username": username,
        "salt": salt,
        "password_hash": digest,
        "public": False,
        "created_at": time.time(),
        "favorites": [],       # [{url, title, public_url, time}]
        "instagram": {},       # جای رزرو برای اتصال شخصی اینستاگرام
    }


def find_account(bot, username):
    """
    (path, data, is_public) یا (None, None, None) اگه پیدا نشد.
    اول عمومی (سراسری)، بعد خصوصی (همین سرور) -- طبق طراحی بالا.
    """
    gpath = _global_path(username)
    data = _read(gpath)
    if data is not None:
        return gpath, data, True
    ppath = _private_path(bot, username)
    data = _read(ppath)
    if data is not None:
        return ppath, data, False
    return None, None, None


def login_or_register(bot, username, password):
    """
    نتیجه یه dict با کلید status:
      "logged_in"        -> حساب پیدا شد و پسورد درست بود. data همراهشه.
      "wrong_password"   -> حساب پیدا شد ولی پسورد غلط بود.
      "created"          -> حسابی نبود، یکی تازه (خصوصیِ همین سرور) ساخته شد.
    """
    if not is_valid_username(username):
        return {"status": "invalid_username"}

    path, data, is_public = find_account(bot, username)
    if data is not None:
        if not _verify_password(password, data["salt"], data["password_hash"]):
            return {"status": "wrong_password"}
        return {"status": "logged_in", "data": data, "public": is_public}

    data = _new_account_data(username, password)
    _write(_private_path(bot, username), data)
    return {"status": "created", "data": data, "public": False}


def save(bot, username, data, public):
    path = _global_path(username) if public else _private_path(bot, username)
    _write(path, data)


def set_public(bot, username, data):
    """
    حساب رو از خصوصیِ همین سرور به عمومی (سراسری) منتقل می‌کنه.
    برمی‌گردونه: "already_public" / "name_taken" / "ok"
    """
    gpath = _global_path(username)
    existing = _read(gpath)
    if existing is not None:
        if hmac.compare_digest(existing.get("password_hash", ""), data["password_hash"]):
            return "already_public"
        return "name_taken"

    data["public"] = True
    _write(gpath, data)
    try:
        os.remove(_private_path(bot, username))
    except OSError:
        pass
    return "ok"


def set_private(bot, username, data):
    """حساب رو از عمومی به خصوصیِ همین سرور برمی‌گردونه."""
    data["public"] = False
    _write(_private_path(bot, username), data)
    try:
        os.remove(_global_path(username))
    except OSError:
        pass


def session_login(bot, teamtalk_username, account_username):
    bot.sf_sessions[teamtalk_username] = account_username


def session_logout(bot, teamtalk_username):
    bot.sf_sessions.pop(teamtalk_username, None)


def upsert_favorite(bot, teamtalk_username, public_url, title, resume_seconds):
    """
    آیتم رو به فروریتِ حسابِ لاگین‌شده‌ی این کاربر اضافه می‌کنه، یا اگه از
    قبل بود (همون public_url) فقط زمان (resume_seconds) رو به‌روز می‌کنه.
    برمی‌گردونه: "added" / "updated" / "not_logged_in"
    """
    account_username, path, data, is_public = get_session_account(bot, teamtalk_username)
    if data is None:
        return "not_logged_in"

    favorites = data.setdefault('favorites', [])
    for entry in favorites:
        if entry.get('public_url') == public_url:
            entry['time'] = resume_seconds
            entry['title'] = title or entry.get('title')
            save(bot, account_username, data, is_public)
            return "updated"

    favorites.append({"url": public_url, "public_url": public_url, "title": title, "time": resume_seconds})
    save(bot, account_username, data, is_public)
    return "added"


def remove_favorite_by_index(bot, teamtalk_username, index):
    """index صفر-پایه. برمی‌گردونه: "removed" / "invalid_index" / "not_logged_in"."""
    account_username, path, data, is_public = get_session_account(bot, teamtalk_username)
    if data is None:
        return "not_logged_in"
    favorites = data.get('favorites', [])
    if not (0 <= index < len(favorites)):
        return "invalid_index"
    favorites.pop(index)
    save(bot, account_username, data, is_public)
    return "removed"


def remove_favorite_by_url(bot, teamtalk_username, public_url):
    """برمی‌گردونه: "removed" / "not_found" / "not_logged_in"."""
    account_username, path, data, is_public = get_session_account(bot, teamtalk_username)
    if data is None:
        return "not_logged_in"
    favorites = data.get('favorites', [])
    for i, entry in enumerate(favorites):
        if entry.get('public_url') == public_url:
            favorites.pop(i)
            save(bot, account_username, data, is_public)
            return "removed"
    return "not_found"


def get_session_account(bot, teamtalk_username):
    """
    اکانتِ لاگین‌شده‌ی فعلیِ این کاربر تیم‌تاک رو برمی‌گردونه:
    (username, path, data, is_public) یا (None, None, None, None).
    """
    account_username = bot.sf_sessions.get(teamtalk_username)
    if not account_username:
        return None, None, None, None
    path, data, is_public = find_account(bot, account_username)
    if data is None:
        # حساب بین این‌بار و لاگین قبلی حذف/جابه‌جا شده؛ نشست رو هم پاک کن.
        session_logout(bot, teamtalk_username)
        return None, None, None, None
    return account_username, path, data, is_public
