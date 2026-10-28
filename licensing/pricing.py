"""
محاسبه‌ی قیمت و تبدیل دلار به تومان.

## چرا نرخ دلار جدا نگه داشته می‌شه

قیمت‌ها توی کاتالوگ به دلارن (پایدار)، ولی کاربر ایرانی باید عدد تومانی
ببینه. نرخ روز از یه API گرفته می‌شه، **ولی هیچ‌وقت به API تکیه نمی‌کنیم**:

  ۱. نرخ موفق توی دیتابیس کش می‌شه (با زمانش).
  ۲. اگه API جواب نده، آخرین نرخ کش‌شده استفاده می‌شه.
  ۳. اگه ادمین نرخ دستی ست کرده باشه (`/rate 105000`)، اون همیشه برنده‌ست.
  ۴. اگه هیچ نرخی نباشه، فقط مبلغ دلاری نشون داده می‌شه و به ادمین هشدار
     داده می‌شه -- نه اینکه یه عدد تومانی الکی ساخته بشه.

این ترتیب مهمه: API های نرخ آزاد ناپایدارن و ممکنه از سرور در دسترس
نباشن؛ یه عدد غلط توی فاکتور بدتر از نبودِ عدده.

## فرمت شمارش

مبلغ تومانی همیشه به مضرب هزار تومان رند *بالا* می‌شه. رند بالا (نه
نزدیک‌ترین) عمدیه: با رند پایین ممکنه مبلغ دریافتی از مبلغ فاکتور کمتر
بشه و بررسی رسید بی‌دلیل رد بخوره.
"""

import json
import math
import time
import urllib.error
import urllib.request

from licensing import catalog
from licensing import i18n

# نرخ‌های خارج از این بازه قطعاً غلطن (خطای API یا اشتباه تایپی ادمین).
# مقدارها «تومان به ازای یک دلار» هستن.
RATE_SANITY_MIN = 10_000
RATE_SANITY_MAX = 5_000_000

# سن قابل‌قبول نرخ کش‌شده. بیشتر از این، به ادمین هشدار داده می‌شه (ولی
# همچنان استفاده می‌شه -- چون نبودِ عدد بدتره).
RATE_STALE_SECONDS = 24 * 3600

REQUEST_TIMEOUT = 12

# منابع نرخ. هر کدوم (اسم، آدرس، تابع استخراج) است و به ترتیب امتحان
# می‌شن. همه باید «تومان به ازای دلار» برگردونن.
#
# نکته: این‌ها نرخ بازار آزادن، نه نرخ رسمی. اگه منبع بهتری داشتی، توی
# data/licensing/catalog.json چیزی لازم نیست -- همین‌جا اضافه کن یا نرخ رو
# دستی ست کن.
_SOURCES = [
    (
        "tgju-pricedollarrl",
        "https://call1.tgju.org/ajax.json",
        lambda data: _tgju_extract(data),
    ),
    (
        "nobitex-usdt",
        "https://api.nobitex.ir/market/stats?srcCurrency=usdt&dstCurrency=rls",
        lambda data: _nobitex_extract(data),
    ),
]


def _tgju_extract(data):
    # ساختار: {"current": {"price_dollar_rl": {"p": "1,234,500", ...}, ...}}
    node = (data.get("current") or {}).get("price_dollar_rl") or {}
    raw = str(node.get("p") or "").replace(",", "").strip()
    if not raw:
        return None
    # tgju قیمت رو به ریال می‌ده
    return float(raw) / 10.0


def _nobitex_extract(data):
    stats = (data.get("stats") or {})
    for key, value in stats.items():
        if "usdt" in key.lower():
            raw = str(value.get("latest") or "").strip()
            if raw:
                # نوبیتکس به ریال می‌ده
                return float(raw) / 10.0
    return None


def _http_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ttbot-licensing/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def fetch_usd_rate():
    """
    نرخ دلار به تومان از منابع آنلاین. خروجی (rate, source) یا (None, error_text).
    هیچ exception ای بیرون نمی‌ده -- شکست یه حالت عادیه، نه خطا.
    """
    errors = []
    for name, url, extract in _SOURCES:
        try:
            value = extract(_http_json(url))
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as e:
            errors.append(f"{name}: {type(e).__name__}")
            continue
        if value and RATE_SANITY_MIN <= value <= RATE_SANITY_MAX:
            return int(round(value)), name
        errors.append(f"{name}: implausible value ({value})")
    return None, "; ".join(errors) or "no rate source responded"


def current_rate(db):
    """
    نرخی که همین الان باید برای فاکتور استفاده بشه.

    خروجی dict:
        {"rate": int|None, "source": str, "age_seconds": int|None, "stale": bool}
    """
    manual = db.get_setting("usd_rate_manual")
    if manual:
        try:
            value = int(float(manual))
            if RATE_SANITY_MIN <= value <= RATE_SANITY_MAX:
                return {"rate": value, "source": "manual", "age_seconds": 0, "stale": False}
        except (TypeError, ValueError):
            pass

    cached = db.get_setting("usd_rate_cached")
    cached_at = db.get_setting("usd_rate_cached_at")
    if cached:
        try:
            value = int(float(cached))
            age = int(time.time()) - int(float(cached_at or 0))
            return {
                "rate": value,
                "source": db.get_setting("usd_rate_source") or "auto",
                "age_seconds": age,
                "stale": age > RATE_STALE_SECONDS,
            }
        except (TypeError, ValueError):
            pass

    return {"rate": None, "source": "none", "age_seconds": None, "stale": True}


def refresh_rate(db):
    """
    نرخ رو از اینترنت می‌گیره و کش می‌کنه. خروجی همون شکل current_rate،
    به‌علاوه‌ی کلید "error" اگه گرفتن نشد.
    """
    rate, source = fetch_usd_rate()
    if rate is None:
        state = current_rate(db)
        state["error"] = source
        return state
    db.set_setting("usd_rate_cached", str(rate))
    db.set_setting("usd_rate_cached_at", str(int(time.time())))
    db.set_setting("usd_rate_source", source)
    return current_rate(db)


# ---------------------------------------------------------------------------
# محاسبه‌ی قیمت سفارش
# ---------------------------------------------------------------------------

def duration_multiplier(months):
    """
    ضریب مدت. اگه تعداد ماه توی جدول نباشه، خطی حساب می‌شه (بدون تخفیف)،
    چون یه سفارش ۴ماهه نباید بی‌دلیل رد بشه.
    """
    table = catalog.pricing().get("duration_multipliers", {})
    key = str(int(months))
    if key in table:
        return float(table[key])
    return float(months)


def feature_price_usd(feature_codes):
    """
    قیمت ماهانه‌ی امکاناتِ انتخاب‌شده، با در نظر گرفتن بسته‌ها.

    اگه همه‌ی اعضای یه بسته انتخاب شده باشن و قیمت بسته کمتر از جمعشون
    باشه، قیمت بسته حساب می‌شه -- یعنی کاربر خودکار تخفیف می‌گیره، لازم
    نیست بدونه بسته‌ای وجود داره.
    """
    selected = set(catalog.expand_features(feature_codes))
    if not selected:
        return 0.0, []

    all_features = catalog.features()
    remaining = set(selected)
    total = 0.0
    applied = []

    # بسته‌های بزرگ‌تر اول، تا «بسته‌ی کامل» بر «بسته‌ی سرویس‌ها» اولویت بگیره.
    for code, bundle in sorted(
        catalog.bundles().items(), key=lambda kv: -len(kv[1].get("features", []))
    ):
        members = set(catalog.expand_features(bundle.get("features", [])))
        if not members or not members.issubset(remaining):
            continue
        separate = sum(float(all_features[m].get("price_usd", 0)) for m in members)
        bundle_price = float(bundle.get("price_usd", separate))
        if bundle_price < separate:
            total += bundle_price
            applied.append({"code": code, "title": bundle.get("title_fa", code),
                            "price_usd": bundle_price, "saved_usd": separate - bundle_price})
            remaining -= members

    for code in sorted(remaining):
        total += float(all_features[code].get("price_usd", 0))

    return total, applied


def server_cost_per_bot():
    """
    سهم هر ربات از اجاره‌ی سرور، در ماه (دلار).

    صریح و جدا نگه داشته می‌شه نه قاطیِ قیمت پایه، تا دو چیز معلوم باشه:
    وقتی سرور عوض شد فقط دو عدد توی کاتالوگ به‌روز می‌شه، و توی فاکتور
    می‌بینی حاشیه‌ی سودت واقعاً چقدره.
    """
    config = catalog.pricing().get("server") or {}
    try:
        monthly = float(config.get("monthly_usd", 0) or 0)
        capacity = int(config.get("capacity_bots", 0) or 0)
        overhead = float(config.get("overhead_multiplier", 1) or 1)
    except (TypeError, ValueError):
        return 0.0
    if monthly <= 0 or capacity <= 0:
        return 0.0
    return round(monthly / capacity * overhead, 4)


def quote(months, bots, feature_codes, db=None):
    """
    فاکتور کامل یه سفارش.

    تعداد کاربر مدیر (اپراتور) دیگه بُعدِ قیمت نیست (تصمیم ۲۰۲۶-۰۹-۱۶):
    هر ربات هر چند اپراتور لازم داشته باشه می‌تونه داشته باشه، فقط سقفِ
    فنیِ setup_wizard.MAX_OPERATORS رو داره که ربطی به قیمت‌گذاری نداره.

    خروجی dict:
        months, bots, features (لیست کدهای واقعی)
        monthly_usd, total_usd
        total_irr (یا None اگه نرخ نداریم), usd_rate, rate_source, rate_stale
        lines: ردیف‌های فاکتور برای نشون دادن به کاربر
        bundle_savings_usd
    """
    config = catalog.pricing()
    months = max(1, int(months))
    bots = max(1, min(int(config.get("max_bots", 10)), int(bots)))
    selected = catalog.expand_features(feature_codes)

    base = float(config.get("base_monthly_usd", 5.0))
    extra_bots = (bots - 1) * float(config.get("extra_bot_usd", 4.0))
    features_usd, bundles_applied = feature_price_usd(selected)

    # زیرساخت به ازای *هر* ربات حساب می‌شه (نه فقط ربات‌های اضافه): ربات
    # اول هم روی سرور جا می‌گیره و منابع مصرف می‌کنه.
    infra = server_cost_per_bot() * bots

    monthly = base + extra_bots + features_usd + infra
    multiplier = duration_multiplier(months)
    total_usd = round(monthly * multiplier, 2)

    lines = [{"title": i18n.t("invoice_base_line"), "usd": round(base, 2)}]
    if infra:
        lines.append({
            "title": i18n.t("invoice_server_line", bots=bots),
            "usd": round(infra, 2),
        })
    if extra_bots:
        lines.append({"title": i18n.t("invoice_extra_bots", count=bots - 1),
                      "usd": round(extra_bots, 2)})
    for bundle in bundles_applied:
        lines.append({"title": bundle["title"], "usd": round(bundle["price_usd"], 2)})
    covered = set()
    for bundle in bundles_applied:
        covered |= set(catalog.expand_features(catalog.bundles()[bundle["code"]].get("features", [])))
    for code in selected:
        if code in covered:
            continue
        lines.append({
            "title": catalog.feature_title(code),
            "usd": round(float(catalog.features()[code].get("price_usd", 0)), 2),
        })

    result = {
        "months": months,
        "bots": bots,
        "features": selected,
        "monthly_usd": round(monthly, 2),
        "total_usd": total_usd,
        "duration_multiplier": multiplier,
        "lines": lines,
        "bundle_savings_usd": round(sum(b["saved_usd"] for b in bundles_applied), 2),
        "infra_monthly_usd": round(infra, 2),
        "margin_monthly_usd": round(monthly - infra, 2),
        "total_irr": None,
        "usd_rate": None,
        "rate_source": "none",
        "rate_stale": True,
    }

    if db is not None:
        rate_state = current_rate(db)
        if rate_state["rate"]:
            result["usd_rate"] = rate_state["rate"]
            result["rate_source"] = rate_state["source"]
            result["rate_stale"] = rate_state["stale"]
            result["total_irr"] = round_irr(total_usd * rate_state["rate"])

    return result


def round_irr(amount):
    """
    رند *بالا* به مضرب irr_rounding. رند بالا عمدیه: اگه پایین رند کنیم،
    مبلغ واریزی کاربر از فاکتور کمتر می‌شه و بررسی رسید بی‌دلیل رد می‌خوره.
    """
    step = int(catalog.pricing().get("irr_rounding", 1000)) or 1
    return int(math.ceil(float(amount) / step) * step)


def format_irr(amount):
    """۱٬۲۳۴٬۰۰۰ تومان -- با جداکننده‌ی هزارگان فارسی‌پسند."""
    if amount is None:
        return "—"
    return f"{int(amount):,}".replace(",", "٬")


def format_usd(amount):
    if amount is None:
        return "—"
    text = f"{float(amount):.2f}".rstrip("0").rstrip(".")
    return f"${text}"
