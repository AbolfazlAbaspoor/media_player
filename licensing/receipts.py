"""
بررسی خودکار عکس رسید پرداخت — با OCR محلی و قواعد، بدون ارسال عکس به
هیچ سرویس بیرونی.

## این چیزی که هست و چیزی که نیست

این ماژول **تأییدکننده‌ی پرداخت نیست**. کاری که می‌کنه اینه که رسید رو
بخونه و بگه «چقدر شبیه یه رسید واقعیِ همین فاکتوره». تصمیم نهایی همیشه
دست ادمینه — دقیقاً همون‌طور که خواسته شده. خروجی این ماژول فقط باعث
می‌شه ادمین یه پیام آماده با همه‌ی نکات مشکوک ببینه، نه اینکه لایسنس
خودکار باز بشه.

چرا این تفکیک مهمه: تشخیص فتوشاپ از روی یه اسکرین‌شات فشرده‌شده‌ی تلگرام
عملاً غیرقابل‌اعتماده. هر ادعای قطعی‌تری از این، در عمل یا مشتری واقعی رو
رد می‌کنه یا تقلب رو رد می‌کنه.

## چی چک می‌شه

  ۱. مبلغ: عددهای متن استخراج و با مبلغ فاکتور مقایسه می‌شن (ریال و تومان
     هر دو، چون رسید بانکی معمولاً ریال می‌ده).
  ۲. شماره کارت مقصد: ۴ رقم آخر کارت ما توی متن هست؟
  ۳. تاریخ/ساعت: رسید مال بعد از ثبت سفارشه؟
  ۴. شماره پیگیری: یه عدد بلند (۶ رقم به بالا) هست؟
  ۵. تکراری نبودن: هش تصویر و شماره پیگیری قبلاً استفاده نشده باشن — این
     مهم‌ترین چک واقعیه، چون رایج‌ترین تقلب «فرستادن یه رسید درست، چند بار»
     است، نه ساختن رسید جعلی.
  ۶. نشانه‌های ویرایش: اگه Pillow نصب باشه، وجود نرم‌افزار ویرایش توی
     متادیتای EXIF گزارش می‌شه (فقط به‌عنوان یه نکته، نه حکم).

## وابستگی‌ها همه اختیاری‌ان

اگه pytesseract یا Pillow نصب نباشن، ماژول به‌جای خطا یه نتیجه‌ی
«قابل‌خواندن نبود» برمی‌گردونه و سفارش مستقیم می‌ره برای بررسی دستی
ادمین. هیچ‌وقت جلوی فروش رو نمی‌گیره.
"""

import hashlib
import os
import re
import time

from licensing import i18n

# ارقام فارسی/عربی رو به لاتین تبدیل می‌کنیم، وگرنه هیچ عددی از رسید
# ایرانی درست خونده نمی‌شه.
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# کلمه‌هایی که توی یه رسید واقعی کارت‌به‌کارت/انتقال تقریباً همیشه هستن.
_RECEIPT_KEYWORDS = (
    "پیگیری", "رسید", "انتقال", "کارت", "مبلغ", "ریال", "تومان", "موفق",
    "تراکنش", "واریز", "مقصد", "مبدا", "مبدأ", "بانک", "شبا", "شماره",
    "reference", "receipt", "transfer", "amount", "success", "paid",
)

# نشانه‌های «این یه اسکرین‌شات از یه اپ پرداخت نیست، یه فایل ساخته‌شده‌ست»
_EDITOR_HINTS = ("photoshop", "gimp", "paint", "canva", "picsart", "snapseed", "lightroom")

# کلماتی که یعنی تراکنش **انجام نشده**. این قوی‌ترین سیگنال منفیه: یه رسید
# ناموفق همه‌ی نشانه‌های یه رسید واقعی رو داره (مبلغ، کارت، تاریخ، حتی
# شماره پیگیری) و بدون این چک، امتیاز بالایی می‌گرفت.
_FAILURE_MARKERS = (
    "ناموفق", "نا موفق", "انجام نشد", "برگشت خورد", "عدم موفقیت", "لغو شد",
    "تراکنش ناموفق", "خطا در انتقال", "رد شد", "ابطال",
    "failed", "unsuccessful", "declined", "cancelled", "canceled", "reversed",
)

# کلماتی که یعنی تراکنش موفق بوده.
_SUCCESS_MARKERS = (
    "موفق", "انجام شد", "با موفقیت", "تایید شد", "تأیید شد", "پرداخت شد",
    "successful", "success", "completed", "approved", "paid",
)

# بانک‌های ایرانی. دیدن اسم یه بانک واقعی توی متن، یه سیگنال مثبت ضعیف ولی
# واقعیه -- یه رسید ساختگیِ سرسری معمولاً اینو نداره.
_BANK_NAMES = (
    "ملی", "ملت", "صادرات", "تجارت", "سپه", "کشاورزی", "مسکن", "رفاه",
    "پارسیان", "پاسارگاد", "سامان", "سینا", "دی", "شهر", "آینده", "اقتصاد نوین",
    "گردشگری", "کارآفرین", "خاورمیانه", "قوامین", "انصار", "حکمت", "ایران زمین",
    "بلوبانک", "بلو بانک", "blu", "mellat", "melli", "saderat", "tejarat",
    "parsian", "pasargad", "saman", "sepah", "resalat", "رسالت", "توسعه تعاون",
    "پست بانک", "postbank",
)

# اپ‌های پرداخت رایج -- اسمشون توی اسکرین‌شات یعنی از یه اپ واقعی اومده.
_PAYMENT_APPS = (
    "آپ", "ایوا", "سکه", "تاپ", "همراه بانک", "اینترنت بانک", "بام", "من",
    "شاپرک", "shaparak", "ap", "iva", "top", "snapp", "اسنپ پی", "زرین‌پال",
    "zarinpal", "پرداخت الکترونیک",
)


class ReceiptCheck:
    """
    نتیجه‌ی بررسی.

    score: عددی بین ۰ و ۱ — «چقدر با فاکتور می‌خوره».
    verdict: "match" | "suspicious" | "mismatch" | "unreadable"
    notes: لیست متن فارسی برای نشون دادن به ادمین.
    """

    def __init__(self):
        self.score = 0.0
        self.verdict = "unreadable"
        self.notes = []
        self.text = ""
        self.amounts_found = []
        self.reference = None
        self.image_hash = None
        self.perceptual_hash = None
        self.duplicate_of = None
        # جزئیاتی که ادمین ممکنه بخواد ببینه
        self.amount_state = None
        self.amount_found = None
        self.receipt_date = None
        self.receipt_time = None
        self.bank = None
        self.cards_seen = []

    def add(self, note):
        self.notes.append(note)

    def summary(self):
        return " • ".join(self.notes) if self.notes else i18n.t("receipt_no_notes")

    def as_dict(self):
        return {
            "score": round(self.score, 3),
            "verdict": self.verdict,
            "notes": self.notes,
            "amounts_found": self.amounts_found[:20],
            "reference": self.reference,
            "image_hash": self.image_hash,
            "perceptual_hash": self.perceptual_hash,
            "duplicate_of": self.duplicate_of,
            "amount_state": self.amount_state,
            "amount_found": self.amount_found,
            "receipt_date": self.receipt_date,
            "receipt_time": self.receipt_time,
            "bank": self.bank,
            "cards_seen": [c[-4:] for c in (self.cards_seen or [])],
        }


def _normalize(text):
    return (text or "").translate(_DIGIT_MAP)


def _configure_tesseract_cmd(pytesseract):
    """
    اگه tesseract همراه پروژه باشه (مثلاً نصبِ سایلنتِ install.py روی
    ویندوز، که توی PATH سیستم ثبت نمی‌شه)، pytesseract رو مستقیم به همون
    مسیر اشاره می‌دیم. وگرنه دست‌نخورده می‌مونه و pytesseract طبق پیش‌فرضِ
    خودش دنبال اسمِ «tesseract» روی PATH می‌گرده -- دقیقاً همون‌جایی که
    apt/dnf نصبش می‌کنن.
    """
    from core import platform_paths
    path = platform_paths.find_native_component("tesseract")
    if path:
        pytesseract.pytesseract.tesseract_cmd = path


def ocr_available():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    try:
        import pytesseract
        _configure_tesseract_cmd(pytesseract)
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text(image_path):
    """
    متن رسید. خروجی (text, error). خطا یعنی OCR در دسترس نبود یا شکست
    خورد — نه اینکه رسید بده.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        return "", i18n.t("receipt_ocr_missing", module=e.name)

    _configure_tesseract_cmd(pytesseract)

    # چک زودهنگامِ خودِ موتور (نه فقط کتابخانه‌ی پایتون): اگه باینری
    # tesseract روی سیستم نباشه، image_to_string پایین‌تر با
    # TesseractNotFoundError شکست می‌خوره -- بهتره همین‌جا با یه پیام روشن
    # («موتور نصب نیست») برگردیم، تا این‌که دو بار (با/بدون lang) OCR رو
    # صدا بزنیم و در آخر با پیام گمراه‌کننده‌ی «تصویر خوانده نشد» برگردیم.
    try:
        pytesseract.get_tesseract_version()
    except Exception as e:
        return "", i18n.t("receipt_engine_missing", error=f"{type(e).__name__}: {e}")

    try:
        with Image.open(image_path) as image:
            image = image.convert("L")
            # بزرگ‌کردن تصاویر کوچک: tesseract روی متن ریزِ اسکرین‌شات موبایل
            # ضعیفه و همین یه تغییر ساده تفاوت زیادی می‌سازه.
            if min(image.size) < 1000:
                factor = max(2, int(1000 / max(1, min(image.size))))
                image = image.resize((image.size[0] * factor, image.size[1] * factor))
            # fas+eng: رسید ایرانی هم فارسی داره هم عدد لاتین. اگه دیتای
            # زبان فارسی نصب نباشه، با انگلیسی تنها دوباره تلاش می‌کنیم.
            try:
                text = pytesseract.image_to_string(image, lang="fas+eng")
            except pytesseract.TesseractNotFoundError:
                raise
            except Exception:
                text = pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as e:
        return "", i18n.t("receipt_engine_missing", error=f"{type(e).__name__}: {e}")
    except Exception as e:
        return "", i18n.t("receipt_image_unreadable", error=f"{type(e).__name__}: {e}")

    return _normalize(text), None


def image_fingerprint(image_path):
    """
    هش محتوای فایل. برای تشخیص «همون رسید، بار دوم» کافیه و هیچ وابستگی‌ای
    لازم نداره.

    توجه: تلگرام موقع فشرده‌سازی مجدد، بایت‌ها رو عوض می‌کنه، پس این هش
    یه کاربر زیرک که عکس رو دوباره اسکرین‌شات بگیره نمی‌گیره. چک شماره‌ی
    پیگیری برای اون حالت گذاشته شده.
    """
    digest = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find_numbers(text):
    """همه‌ی عددهای متن، با حذف جداکننده‌های هزارگان."""
    numbers = []
    for raw in re.findall(r"[\d][\d,٬\.\s]{2,}[\d]|\d+", text or ""):
        cleaned = re.sub(r"[,٬\s]", "", raw)
        # نقطه فقط وقتی جداکننده‌ی هزارگانه که بعدش دقیقاً ۳ رقم باشه
        cleaned = re.sub(r"\.(?=\d{3}(\D|$))", "", cleaned)
        if "." in cleaned:
            cleaned = cleaned.split(".")[0]
        if cleaned.isdigit():
            numbers.append(int(cleaned))
    return numbers


def _amount_matches(numbers, expected_irr, tolerance=0.02):
    """
    آیا یکی از عددهای رسید با مبلغ فاکتور می‌خونه؟

    هم تومان و هم ریال (×۱۰) چک می‌شن، چون اپ‌های بانکی معمولاً ریال نشون
    می‌دن ولی فاکتور ما تومانه. یه رواداری کوچک هم هست، چون بعضی بانک‌ها
    کارمزد رو به مبلغ اضافه می‌کنن.
    """
    if not expected_irr:
        return None
    targets = (int(expected_irr), int(expected_irr) * 10)
    best = None
    for number in numbers:
        for target in targets:
            if target <= 0:
                continue
            diff = abs(number - target) / target
            if diff <= tolerance and (best is None or diff < best[1]):
                best = (number, diff)
    return best


def _find_reference(text, numbers):
    """
    شماره پیگیری: اول دنبال عدد بعد از کلمه‌ی «پیگیری/مرجع/reference»
    می‌گردیم، وگرنه بلندترین عدد ۶ رقم به بالا (که شماره کارت نباشه).
    """
    match = re.search(
        r"(?:پیگیری|پي?گيري|مرجع|reference|ref|trace)\D{0,20}(\d{6,})",
        text or "", re.I,
    )
    if match:
        return match.group(1)
    candidates = [n for n in numbers if 100_000 <= n and len(str(n)) != 16]
    if not candidates:
        return None
    return str(max(candidates, key=lambda n: (len(str(n)), n)))


def _exif_notes(image_path):
    notes = []
    try:
        from PIL import Image, ExifTags
    except ImportError:
        return notes
    try:
        with Image.open(image_path) as image:
            exif = getattr(image, "_getexif", lambda: None)() or {}
            for tag_id, value in exif.items():
                name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if name in ("Software", "ProcessingSoftware", "HostComputer"):
                    text = str(value).lower()
                    for hint in _EDITOR_HINTS:
                        if hint in text:
                            notes.append(i18n.t("receipt_editor_metadata", software=value))
                            break
    except Exception:
        pass
    return notes


def perceptual_hash(image_path, size=16):
    """
    هش ادراکی (average hash) -- برخلاف هش فایل، با فشرده‌سازی دوباره، تغییر
    اندازه یا اسکرین‌شاتِ دوباره عوض نمی‌شه.

    این همون حفره‌ایه که هش فایل نمی‌گرفت: کسی که یه رسید درست رو دوباره
    اسکرین‌شات می‌گرفت، هش فایلش کاملاً فرق می‌کرد ولی تصویر همون بود.

    None اگه Pillow نصب نباشه.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as image:
            small = image.convert("L").resize((size, size), Image.LANCZOS)
            pixels = list(small.getdata())
    except Exception:
        return None
    if not pixels:
        return None
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):0{size * size // 4}x}"


def hamming_distance(hash_a, hash_b):
    """فاصله‌ی دو هش ادراکی. کمتر از ~۵ یعنی عملاً همون تصویر."""
    if not hash_a or not hash_b or len(hash_a) != len(hash_b):
        return None
    try:
        return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
    except ValueError:
        return None


# فاصله‌ای که زیرش دو تصویر «همون» حساب می‌شن. ۶۴ بیت داریم؛ ۵ یعنی حدود
# ۹۲٪ شباهت، که برای اسکرین‌شات دوباره از یه تصویر جا داره ولی دو رسید
# واقعیِ متفاوت (که مبلغ و شماره‌شون فرق داره) رو اشتباهی نمی‌گیره.
PERCEPTUAL_MATCH_DISTANCE = 5


def _match_known_image(current_hash, known, reference):
    """
    آیا این تصویر عملاً همون یکی از رسیدهای قبلیه؟

    خروجی: فاصله‌ی هش اگه «تکراری» بود، وگرنه None. اگه فقط ظاهرش شبیه بود
    ولی شماره پیگیری فرق داشت، خروجی رشته‌ی توضیح می‌شه (نه عدد) تا صدا
    زننده بتونه فرقشون رو بفهمه.

    قاعده: تطبیق تصویری به‌تنهایی کافی نیست. دو رسید واقعی از یه اپ بانکی
    قالب یکسان دارن و خیلی شبیه هم‌ان -- رد کردنشون یعنی بلاک کردن یه
    مشتری درست. پس شماره پیگیری باید تأییدش کنه، یا اصلاً شماره‌ای در کار
    نباشه.
    """
    if not current_hash:
        return None
    for previous in (known or ()):
        if isinstance(previous, dict):
            previous_hash = previous.get("phash")
            previous_reference = previous.get("reference")
        else:
            previous_hash, previous_reference = previous, None

        distance = hamming_distance(current_hash, previous_hash)
        if distance is None or distance > PERCEPTUAL_MATCH_DISTANCE:
            continue

        same_reference = (reference and previous_reference
                          and str(reference) == str(previous_reference))
        no_reference = not reference or not previous_reference
        if same_reference or no_reference:
            return distance
        return i18n.t("receipt_similar_diff_ref", distance=distance)
    return None


def _extract_datetime(text):
    """
    تاریخ و ساعت رسید. خروجی (متن تاریخ یا None، متن ساعت یا None).

    فرمت‌های رایج رسید ایرانی: ۱۴۰۳/۰۱/۰۵ یا 1403-01-05 و ساعت 14:32:07.
    """
    date_match = re.search(r"\b(1[34]\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", text or "")
    if not date_match:
        date_match = re.search(r"\b(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})\b", text or "")
    time_match = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b", text or "")
    return (date_match.group(0) if date_match else None,
            time_match.group(0) if time_match else None)


def _find_card_numbers(text):
    """شماره کارت‌های ۱۶ رقمی متن (با یا بدون جداکننده)."""
    cards = []
    for raw in re.findall(r"(?:\d[ \-*·]{0,2}){15}\d", text or ""):
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 16:
            cards.append(digits)
    return cards


def _classify_amount(numbers, expected_irr, tolerance=0.02):
    """
    مبلغ رسید در برابر مبلغ فاکتور.

    خروجی: ("match"|"over"|"under"|"missing", عدد پیداشده یا None)

    تفکیک «کمتر» از «پیدا نشد» مهمه: پرداخت ناقص یه حالت کاملاً متفاوته و
    ادمین باید صریح ببیندش، نه اینکه با «مبلغ پیدا نشد» قاطی بشه.
    """
    if not expected_irr:
        return "missing", None
    targets = (int(expected_irr), int(expected_irr) * 10)

    best_match = None
    closest_below = None
    closest_above = None
    for number in numbers:
        for target in targets:
            if target <= 0:
                continue
            diff = (number - target) / target
            if abs(diff) <= tolerance:
                if best_match is None or abs(diff) < abs(best_match[1]):
                    best_match = (number, diff)
            elif diff < 0 and number >= target * 0.5:
                if closest_below is None or number > closest_below:
                    closest_below = number
            elif diff > 0 and number <= target * 3:
                if closest_above is None or number < closest_above:
                    closest_above = number

    if best_match:
        return "match", best_match[0]
    if closest_below is not None:
        return "under", closest_below
    if closest_above is not None:
        return "over", closest_above
    return "missing", None


def _tamper_hint(image_path):
    """
    یه نشانه‌ی *ضعیف* از ویرایش، با مقایسه‌ی تصویر با نسخه‌ی دوباره
    فشرده‌شده‌ی خودش (شبیه ELA).

    ناحیه‌هایی که دوباره ذخیره شدن معمولاً کمتر تغییر می‌کنن از ناحیه‌های
    دست‌نخورده. یه واریانس خیلی نامتوازن می‌تونه یعنی بخشی از تصویر
    جداگانه ویرایش شده.

    **این اثبات نیست.** روی اسکرین‌شات تلگرام که خودش دوباره فشرده شده،
    نتیجه نویزیه. فقط به‌عنوان یه نکته به ادمین گفته می‌شه، و امتیاز رو
    کم نمی‌کنه مگر خیلی شدید باشه.
    """
    try:
        from PIL import Image, ImageChops
        import io as _io
    except ImportError:
        return None
    try:
        with Image.open(image_path) as original:
            rgb = original.convert("RGB")
            buffer = _io.BytesIO()
            rgb.save(buffer, "JPEG", quality=90)
            buffer.seek(0)
            with Image.open(buffer) as recompressed:
                difference = ImageChops.difference(rgb, recompressed)
            extrema = difference.getextrema()
    except Exception:
        return None

    peak = max(channel[1] for channel in extrema) if extrema else 0
    if peak >= 90:
        return i18n.t("receipt_compression_odd", peak=peak)
    return None


def check(image_path, expected_irr=None, expected_usd=None, card_number="",
          order_created_at=None, known_hashes=(), known_references=(),
          known_phashes=()):
    """
    بررسی کامل یه رسید.

    known_hashes/known_references/known_phashes: چیزهایی که قبلاً توی
    سفارش‌های دیگه استفاده شدن — برای تشخیص رسید تکراری.
    """
    result = ReceiptCheck()

    try:
        result.image_hash = image_fingerprint(image_path)
    except OSError as e:
        result.add(i18n.t("receipt_file_unreadable", error=e))
        result.verdict = "unreadable"
        return result

    result.perceptual_hash = perceptual_hash(image_path)

    if result.image_hash in set(known_hashes or ()):
        result.add(i18n.t("receipt_same_file"))
        result.duplicate_of = "image"
        result.verdict = "mismatch"
        result.score = 0.0
        return result

    text, error = extract_text(image_path)
    result.text = text

    if error or not (text or "").strip():
        # OCR در دسترس نیست یا متن خونده نشد. ولی تشخیص تصویرِ تکراری هیچ
        # نیازی به متن نداره -- و اگه اینجا بدون چک برمی‌گشتیم، روی سروری
        # که tesseract نداره، فرستادن دوباره‌ی یه رسید اصلاً گیر نمی‌افتاد.
        duplicate = _match_known_image(result.perceptual_hash, known_phashes, reference=None)
        if duplicate is not None:
            result.add(i18n.t("receipt_same_image", distance=duplicate))
            result.duplicate_of = "image_similar"
            result.verdict = "mismatch"
            result.score = 0.0
            return result

        result.add(error or i18n.t("receipt_no_text"))
        result.add(i18n.t("receipt_manual_needed"))
        result.verdict = "unreadable"
        result.score = 0.0
        return result

    numbers = _find_numbers(text)
    result.amounts_found = numbers
    result.reference = _find_reference(text, numbers)

    lower_text = text.lower()
    flat_text = re.sub(r"\s", "", text)

    # --- ۰) تراکنش ناموفق: قبل از هر امتیازی ---
    # یه رسید ناموفق همه‌ی نشانه‌های یه رسید واقعی رو داره (مبلغ، کارت،
    # تاریخ، حتی شماره پیگیری)، پس بدون این چک امتیاز بالایی می‌گرفت.
    failure_hits = [marker for marker in _FAILURE_MARKERS if marker in lower_text]
    # «ناموفق» خودش شامل «موفق» است، پس اگه اول دنبال موفقیت بگردیم، یه
    # رسید ناموفق هم «موفق» علامت می‌خوره. برای همین عبارت‌های شکست از متن
    # برداشته می‌شن و بعد دنبال نشانه‌ی موفقیت می‌گردیم.
    success_scan = lower_text
    for marker in failure_hits:
        success_scan = success_scan.replace(marker, " ")
    success_hits = [marker for marker in _SUCCESS_MARKERS if marker in success_scan]
    if failure_hits:
        result.add(i18n.t("receipt_failed_transaction", marker=failure_hits[0]))
        result.verdict = "mismatch"
        result.score = 0.0
        return result

    # --- امتیازدهی ---
    score = 0.0

    # ۱) مبلغ (مهم‌ترین سیگنال) -- «کمتر از فاکتور» از «پیدا نشد» جداست،
    # چون پرداخت ناقص یه حالت کاملاً متفاوته و ادمین باید صریح ببیندش.
    state, found = _classify_amount(numbers, expected_irr)
    result.amount_state, result.amount_found = state, found
    if expected_irr:
        if state == "match":
            score += 0.40
            result.add(i18n.t("receipt_amount_match", amount=f"{found:,}"))
        elif state == "under":
            result.add(i18n.t("receipt_amount_under", amount=f"{found:,}",
                              expected=f"{int(expected_irr):,}"))
        elif state == "over":
            score += 0.15
            result.add(i18n.t("receipt_amount_over", amount=f"{found:,}"))
        else:
            result.add(
                i18n.t("receipt_amount_missing", expected=f"{int(expected_irr):,}")
                + (i18n.t("receipt_amount_seen",
                          numbers=", ".join(f"{n:,}" for n in numbers[:6])) if numbers else "")
            )
    else:
        score += 0.10

    # ۲) کارت مقصد -- شماره‌ی کامل امتیاز بیشتری از ۴ رقم آخر داره، چون
    # ۴ رقم آخر ممکنه اتفاقی هم جور دربیاد.
    result.cards_seen = _find_card_numbers(text)
    digits_only = re.sub(r"\D", "", card_number or "")
    if len(digits_only) == 16 and digits_only in result.cards_seen:
        score += 0.22
        result.add(i18n.t("receipt_card_full"))
    elif len(digits_only) >= 4 and digits_only[-4:] in flat_text:
        score += 0.15
        result.add(i18n.t("receipt_card_last4", last4=digits_only[-4:]))
    elif digits_only:
        result.add(i18n.t("receipt_card_missing", last4=digits_only[-4:]))

    if len(result.cards_seen) >= 2:
        score += 0.05
        result.add(i18n.t("receipt_cards_both", count=len(result.cards_seen)))

    # ۳) ساختار متن
    found_keywords = [k for k in _RECEIPT_KEYWORDS if k in lower_text]
    if len(found_keywords) >= 3:
        score += 0.12
        result.add(i18n.t("receipt_structure_good", count=len(found_keywords)))
    elif found_keywords:
        score += 0.04
        result.add(i18n.t("receipt_structure_weak", count=len(found_keywords)))
    else:
        result.add(i18n.t("receipt_structure_none"))

    if success_hits:
        score += 0.06
        result.add(i18n.t("receipt_success_marked", marker=success_hits[0]))

    # ۴) نام بانک یا اپ پرداخت
    bank = next((name for name in _BANK_NAMES if name in lower_text), None)
    app = next((name for name in _PAYMENT_APPS if name in lower_text), None)
    result.bank = bank or app
    if bank:
        score += 0.06
        result.add(i18n.t("receipt_bank_found", bank=bank))
    elif app:
        score += 0.04
        result.add(i18n.t("receipt_app_found", app=app))
    else:
        result.add(i18n.t("receipt_bank_missing"))

    # ۵) شماره پیگیری -- قاطع‌ترین تشخیص تکراری بودن
    if result.reference:
        if str(result.reference) in set(str(r) for r in (known_references or ())):
            result.add(i18n.t("receipt_reference_reused", reference=result.reference))
            result.duplicate_of = "reference"
            result.verdict = "mismatch"
            result.score = 0.0
            return result
        score += 0.09
        result.add(i18n.t("receipt_reference", reference=result.reference))
    else:
        result.add(i18n.t("receipt_reference_missing"))

    # ۵-ب) تصویرِ تکراری
    #
    # هش ادراکی به‌تنهایی کافی *نیست*: دو رسید واقعی از یه اپ بانکی، چون
    # قالبشون یکیه، خیلی شبیه هم‌ان و یه مشتری درست رو رد می‌کرد. پس تطبیق
    # تصویری فقط وقتی «تکراری» حساب می‌شه که شماره پیگیری هم تأییدش کنه یا
    # اصلاً شماره‌ای خونده نشده باشه.
    #
    # اگه تصویر شبیه بود ولی شماره پیگیری *فرق* داشت، یعنی همون اپ با یه
    # تراکنش دیگه -- که کاملاً عادیه و فقط به‌عنوان یه نکته گفته می‌شه.
    duplicate = _match_known_image(result.perceptual_hash, known_phashes, result.reference)
    if isinstance(duplicate, int):
        result.add(i18n.t("receipt_same_image", distance=duplicate))
        result.duplicate_of = "image_similar"
        result.verdict = "mismatch"
        result.score = 0.0
        return result
    if isinstance(duplicate, str):
        result.add(duplicate)

    # ۶) تاریخ و ساعت
    result.receipt_date, result.receipt_time = _extract_datetime(text)
    if result.receipt_date or result.receipt_time:
        score += 0.08
        stamp = " ".join(x for x in (result.receipt_date, result.receipt_time) if x)
        result.add(i18n.t("receipt_datetime", stamp=stamp))
        if order_created_at and result.receipt_date:
            # رسید باید مال حوالیِ *سفارش* باشه، نه حوالیِ امروز -- یه سفارش
            # قدیمی که دیر بررسی می‌شه نباید رسید درستش کهنه به‌نظر برسه.
            #
            # تبدیل دقیق تقویم عمداً انجام نمی‌شه (یه وابستگی اضافه برای یه
            # چک تقریبی)؛ فقط سال مقایسه می‌شه. اختلاف میلادی/شمسی بین ۶۲۱
            # و ۶۲۲ نوسان داره، پس یه سال کامل رواداری گذاشته شده و فقط
            # رسیدی که **دو سال یا بیشتر** قدیمی‌تر از سفارشه علامت می‌خوره.
            year_match = re.match(r"(\d{4})", result.receipt_date)
            if year_match:
                year = int(year_match.group(1))
                order_year = time.localtime(int(order_created_at)).tm_year
                order_jalali = order_year - 621
                if 1300 < year <= order_jalali - 2:
                    score = max(0.0, score - 0.3)
                    result.add(i18n.t("receipt_year_stale", year=year))
                elif 2000 < year <= order_year - 2:
                    score = max(0.0, score - 0.3)
                    result.add(i18n.t("receipt_year_stale", year=year))
    else:
        result.add(i18n.t("receipt_date_missing"))

    # ۷) نشانه‌های ویرایش
    editor_notes = _exif_notes(image_path)
    for note in editor_notes:
        result.add(note)
    if editor_notes:
        score = max(0.0, score - 0.25)

    tamper = _tamper_hint(image_path)
    if tamper:
        result.add(tamper)
        score = max(0.0, score - 0.1)

    result.score = min(1.0, round(score, 3))

    if result.score >= 0.7:
        result.verdict = "match"
    elif result.score >= 0.4:
        result.verdict = "suspicious"
    else:
        result.verdict = "mismatch"

    return result


def verdict_text(verdict):
    key = f"verdict_{verdict}"
    return i18n.t(key) if i18n.has(key) else verdict


def receipt_dir():
    from licensing import config
    os.makedirs(config.RECEIPTS_DIR, exist_ok=True)
    return config.RECEIPTS_DIR


def receipt_path(order_id, extension=".jpg"):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(receipt_dir(), f"order-{int(order_id)}-{stamp}{extension}")
