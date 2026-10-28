"""
فایل‌های کوکی (cookies.txt) سرویس‌ها: کجا هستن، کدوم استفاده بشه، و چی قبول
می‌شه.

## چرا هر ربات کوکی خودش

قبلاً کوکی‌ها توی `data/<host>_<port>/cookies/` بودن، یعنی **بین همه‌ی
ربات‌های یه سرور تیم‌تاک مشترک**. روی پلتفرم میزبانی چند مشتری می‌تونن روی
یه سرور باشن، پس کوکیِ یوتیوبِ یه مشتری -- که عملاً نشستِ حساب گوگلشه --
توسط ربات مشتریِ دیگه استفاده می‌شد.

حالا ترتیب اینه:
  ۱. کوکیِ خودِ همین ربات: `<bot_dir>/cookies/<service>.txt`
  ۲. فقط برای نصب‌های **غیرمدیریت‌شده** (نصب شخصی خود مالک): کوکیِ مشترکِ
     سرور، تا چند ربات شخصی روی یه سرور مثل قبل یه فایل مشترک داشته باشن.
ربات میزبانی‌شده هیچ‌وقت سراغ (۲) نمی‌ره.

## اعتبارسنجی

فایل از مشتری میاد، پس:
  * اسم سرویس فقط `[a-z0-9_]` -- وگرنه `../../x` از پوشه بیرون می‌زد.
  * سقف حجم.
  * فرمت Netscape: خط کامنت/خالی، یا دقیقاً ۷ فیلد جداشده با tab، و دست‌کم
    یه کوکی واقعی. فایل عوضی (HTML، JSON، یه عکس) رد می‌شه.
"""

import os
import re

SERVICE_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_BYTES = 512 * 1024
COOKIE_DIR_NAME = "cookies"


class CookieError(ValueError):
    pass


def check_service_name(service):
    service = str(service or "").strip().lower()
    if not SERVICE_NAME_RE.match(service):
        raise CookieError("invalid service name")
    return service


def path_in(directory, service):
    return os.path.join(directory, COOKIE_DIR_NAME, check_service_name(service) + ".txt")


def resolve(bot_dir, group_dir, service, managed):
    """
    فایل کوکی‌ای که این ربات برای این سرویس باید استفاده کنه، یا None.
    """
    try:
        own = path_in(bot_dir, service)
    except CookieError:
        return None
    if os.path.isfile(own):
        return own
    if not managed and group_dir:
        shared = path_in(group_dir, service)
        if os.path.isfile(shared):
            return shared
    return None


def validate(data):
    """
    bytes یا str -> متن تمیزِ فایل. CookieError با دلیل، اگه قبول نشد.
    """
    if isinstance(data, bytes):
        if len(data) > MAX_BYTES:
            raise CookieError("too large")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise CookieError("not a text file")
    else:
        text = str(data)
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise CookieError("too large")

    text = text.lstrip("﻿")
    cookies = 0
    for raw in text.splitlines():
        line = raw.strip("\r")
        if not line.strip():
            continue
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise CookieError("not a Netscape cookies.txt file")
        if not fields[4].strip().lstrip("-").isdigit():
            raise CookieError("not a Netscape cookies.txt file")
        cookies += 1
    if cookies == 0:
        raise CookieError("no cookies in the file")
    return text if text.endswith("\n") else text + "\n"


def write(directory, service, data):
    """اعتبارسنجی و ذخیره‌ی اتمی با دسترسی فقط-مالک. خروجی: مسیر فایل."""
    text = validate(data)
    path = path_in(directory, service)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def remove(directory, service):
    path = path_in(directory, service)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def present(directory):
    """اسم سرویس‌هایی که فایل کوکی دارن -- هیچ‌وقت محتوا."""
    folder = os.path.join(directory, COOKIE_DIR_NAME)
    if not os.path.isdir(folder):
        return []
    names = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".txt") and SERVICE_NAME_RE.match(name[:-4]):
            names.append(name[:-4])
    return names
