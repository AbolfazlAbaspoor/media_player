"""
رمزنگاری لاگ خطاها روی سیستم مشتری.

## چرا

لاگ خطا برای پشتیبانی لازمه، ولی همون لاگ مسیرهای داخلی، اسم سرویس‌ها،
و جزئیات پیاده‌سازی رو لو می‌ده. روی سیستمی که در اختیار ما نیست،
این یعنی یه نقشه‌ی رایگان برای کسی که می‌خواد فضولی کنه.

راه‌حل: لاگ **رمز** می‌شه. مشتری فایل رو برای ما می‌فرسته، ما با کلید
خصوصی بازش می‌کنیم.

## sealed box، نه رمز مشترک

از `SealedBox` لیب‌سودیوم استفاده می‌شه: کلاینت فقط **کلید عمومی** داره
و فقط می‌تونه *رمز کنه*. هیچ کلیدی روی سیستم مشتری نیست که بشه باهاش
لاگ‌های خودش رو باز کرد -- حتی خودِ برنامه هم بعد از نوشتن نمی‌تونه
بخونتشون.

اگه به‌جاش یه رمز مشترک داخل برنامه می‌ذاشتیم، هرکسی که باینری رو باز
می‌کرد همون رمز رو درمی‌آورد و کل کار بی‌معنی می‌شد.

## فقط توی بیلد

روی اجرای عادی (توسعه) لاگ **خام** می‌مونه -- وگرنه خودت هم موقع
دیباگ نمی‌تونستی لاگت رو بخونی. رمزنگاری فقط وقتی فعاله که برنامه
compile شده باشه، یعنی دقیقاً همون نسخه‌ای که دست مشتریه.

## فرمت

هر خطِ فایل یه رکورد مستقلِ base64 است. یعنی:

  * فایل append-only می‌مونه و rotation مثل قبل کار می‌کنه
  * اگه وسط نوشتن قطع بشه، بقیه‌ی خط‌ها همچنان باز می‌شن
  * هر خط جدا باز می‌شه، پس فایل نصفه هم قابل استفاده‌ست

## خوندنشون

    python manage.py read-errors <فایل>
"""

import base64

from core.paths import is_frozen

#: کلید عمومی X25519 برای رمزکردن لاگ‌ها (base64).
#:
#: با `python manage.py error-keys` ساخته می‌شه. خالی یعنی رمزنگاری
#: خاموشه و لاگ خام نوشته می‌شه.
#:
#: این کلید *عمومی*ه و لو رفتنش مشکلی نداره -- فقط اجازه‌ی رمزکردن
#: می‌ده، نه بازکردن.
PUBLIC_KEY_B64 = "pQVrQsnKy1MUGpdNfllBbzd6NejU+ZDbferbjH0wpFY="

#: پیشوند خط‌های رمزشده، تا اسکریپت خواننده بفهمه با چی طرفه و فایل‌های
#: قدیمیِ خام رو هم بتونه بخونه.
PREFIX = "#e1:"

_box = None
_checked = False


def enabled():
    """
    آیا باید رمز کنیم؟

    سه شرط: بیلد compile شده باشه، کلید عمومی تنظیم شده باشه، و PyNaCl
    در دسترس باشه. هر کدوم نباشه، لاگ خام نوشته می‌شه -- چون لاگِ
    ناخوانا بدتر از لاگِ خوانده‌شدنیه.
    """
    return is_frozen() and _sealed_box() is not None


def _sealed_box():
    global _box, _checked
    if _checked:
        return _box
    _checked = True

    key = (PUBLIC_KEY_B64 or "").strip()
    if not key:
        return None
    try:
        from nacl.public import PublicKey, SealedBox
        _box = SealedBox(PublicKey(base64.b64decode(key)))
    except Exception:
        # نبودِ PyNaCl یا کلید خراب نباید لاگ‌گیری رو بخوابونه.
        _box = None
    return _box


def encrypt_line(line):
    """
    یه خط لاگ رو به یه رکورد رمزشده تبدیل می‌کنه.

    اگه رمزنگاری فعال نباشه یا شکست بخوره، همون خط خام برگردونده می‌شه:
    از دست دادن لاگ بدتر از خوانده‌شدنشه.
    """
    # enabled() نه _sealed_box(): شرط frozen هم باید چک بشه، وگرنه
    # به محض گذاشتن کلید، لاگ خودِ توسعه هم رمز می‌شه و دیگه
    # موقع دیباگ خونده نمی‌شه.
    if not enabled():
        return line
    box = _sealed_box()
    if box is None:
        return line
    try:
        payload = box.encrypt(line.rstrip("\n").encode("utf-8"))
        return PREFIX + base64.b64encode(payload).decode("ascii") + "\n"
    except Exception:
        return line


def decrypt_line(line, private_key_b64):
    """
    یه رکورد رو باز می‌کنه. خط‌های خام (بدون پیشوند) همون‌طور برمی‌گردن،
    تا یه فایل نیمه‌رمز هم کامل خونده بشه.
    """
    line = line.rstrip("\n")
    if not line.startswith(PREFIX):
        return line

    from nacl.public import PrivateKey, SealedBox

    box = SealedBox(PrivateKey(base64.b64decode(private_key_b64)))
    payload = base64.b64decode(line[len(PREFIX):])
    return box.decrypt(payload).decode("utf-8", "replace")


def decrypt_log_text(raw_text, private_key_b64):
    """
    یه فایل لاگِ رمزشده رو کامل باز می‌کنه (خط به خط).

    هم `manage.py read-errors` هم دکمه‌ی رمزگشاییِ ادمین توی تلگرام همینو
    صدا می‌زنن، تا حلقه‌ی «خط به خط رمزگشایی کن و بشمار» یه‌جا بمونه.

    خروجی: (متنِ باز‌شده، تعداد رمزگشایی‌شده، تعداد خط خام، تعداد خط خراب).
    یه رکورد خراب جلوی خوندن بقیه رو نمی‌گیره.
    """
    decrypted = plain = failed = 0
    out_lines = []
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        try:
            text = decrypt_line(line, private_key_b64)
        except Exception:
            failed += 1
            continue
        if line.startswith(PREFIX):
            decrypted += 1
        else:
            plain += 1
        out_lines.append(text)
    return "\n".join(out_lines), decrypted, plain, failed


def generate_keypair():
    """(private_b64, public_b64) — کلید خصوصی رو فقط پیش خودت نگه دار."""
    from nacl.public import PrivateKey

    private = PrivateKey.generate()
    return (base64.b64encode(bytes(private)).decode("ascii"),
            base64.b64encode(bytes(private.public_key)).decode("ascii"))


def describe():
    """وضعیت، برای build-check و گزارش‌ها."""
    if not (PUBLIC_KEY_B64 or "").strip():
        return "خاموش (کلید تنظیم نشده)"
    if _sealed_box() is None:
        return "کلید هست ولی PyNaCl در دسترس نیست"
    if not is_frozen():
        return "آماده — ولی توی بیلد توسعه خاموشه (لاگ خام)"
    return "فعال"
