"""
/catalog و /quote (B8) -- همون داده‌ای که manage.py catalog/quote نشون
می‌ده، از همون منبع (licensing.catalog / licensing.pricing)، فقط قالبِ
نمایشش با ترجمه‌ی تلگرامیه به‌جای پرینتِ فارسیِ ثابتِ CLI. محاسبه‌ی قیمت
جایی تکرار نشده -- هر دو مستقیم از همون توابع می‌خونن.

هر دو هم به‌عنوانِ دستورِ متنی (/catalog، /quote <ماه> <ربات> [امکانات])
هم با دکمه در دسترسن؛ /quote با دکمه یه ویزاردِ سه‌مرحله‌ایه (ماه -> ربات ->
امکانات) تا لازم نباشه سینتکسش رو حفظ کنی.
"""

from licensing import catalog
from licensing import i18n
from licensing import pricing
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _admin_ask, _db, _is_admin, _send


def _catalog_text(db):
    cfg = catalog.pricing()
    lines = [
        i18n.t("admin_catalog_title"), "",
        i18n.t("admin_catalog_base", amount=pricing.format_usd(cfg.get("base_monthly_usd", 0))),
        i18n.t("admin_catalog_extra_bot", amount=pricing.format_usd(cfg.get("extra_bot_usd", 0))),
        i18n.t("admin_catalog_max_bots", count=cfg.get("max_bots", 10)),
        "", i18n.t("admin_catalog_durations_title"),
    ]
    for months, multiplier in sorted(cfg.get("duration_multipliers", {}).items(),
                                     key=lambda kv: int(kv[0])):
        months_i = int(months)
        discount = (months_i - float(multiplier)) / months_i * 100 if months_i else 0
        suffix = (i18n.t("admin_catalog_discount_suffix", percent=round(discount))
                 if discount > 0.5 else "")
        lines.append(i18n.t("admin_catalog_duration_line", months=months, multiplier=multiplier,
                            discount=suffix))

    lines += ["", i18n.t("admin_catalog_features_title")]
    for code, feature in catalog.features().items():
        lines.append(i18n.t("admin_catalog_feature_line", code=T.esc(code),
                            title=T.esc(T.feature_title(code)),
                            price=pricing.format_usd(feature.get("price_usd", 0))))

    lines += ["", i18n.t("admin_catalog_bundles_title")]
    for code, bundle in catalog.bundles().items():
        lines.append(i18n.t("admin_catalog_bundle_line", code=T.esc(code),
                            title=T.esc(T.feature_title(code)),
                            price=pricing.format_usd(bundle.get("price_usd", 0))))

    lines += ["", i18n.t("admin_catalog_panels_title")]
    for panel in catalog.panels():
        quote = pricing.quote(panel["months"], panel["bots"], panel.get("features", []), db=db)
        irr = f" / {pricing.format_irr(quote['total_irr'])}" if quote["total_irr"] else ""
        title = panel.get("title_en") or panel.get("title_fa") or panel["code"]
        lines.append(i18n.t("admin_catalog_panel_line", code=T.esc(panel["code"]),
                            title=T.esc(title), price=pricing.format_usd(quote["total_usd"]) + irr))
    return "\n".join(lines)


async def cmd_catalog(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await _send(update, _catalog_text(_db(context)), kb.admin_back())


def _quote_text(quote):
    lines = [
        i18n.t("admin_quote_title", months=quote["months"], bots=quote["bots"]),
        i18n.t("admin_quote_features", features=T.esc(T.feature_list(quote["features"]))),
        "",
    ]
    for line in quote["lines"]:
        lines.append(i18n.t("invoice_line", title=T.esc(line["title"]),
                            amount=pricing.format_usd(line["usd"])))
    lines += [
        "", i18n.t("admin_quote_monthly", amount=pricing.format_usd(quote["monthly_usd"])),
        i18n.t("admin_quote_multiplier", multiplier=quote["duration_multiplier"]),
        i18n.t("admin_quote_total", amount=pricing.format_usd(quote["total_usd"])),
    ]
    if quote["total_irr"]:
        lines.append(i18n.t("admin_quote_irr", amount=pricing.format_irr(quote["total_irr"]),
                            rate=pricing.format_irr(quote["usd_rate"]),
                            source=T.esc(quote["rate_source"])))
    else:
        lines.append(i18n.t("admin_quote_no_rate"))
    return "\n".join(lines)


async def cmd_quote(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    args = context.args or []
    if len(args) < 2:
        await _send(update, i18n.t("admin_usage_quote"))
        return
    try:
        months = int(args[0])
        bots = int(args[1])
    except ValueError:
        await _send(update, i18n.t("admin_bad_number"))
        return
    features = args[2:]
    quote = pricing.quote(months, bots, features, db=_db(context))
    await _send(update, _quote_text(quote), kb.admin_back())


# --------------------------------------------------------------------
# ویزاردِ دکمه‌ایِ /quote (B8): ماه -> ربات -> امکانات
# --------------------------------------------------------------------

async def admin_quote_start(update, context):
    await _admin_ask(update, context, _is_admin(update), _send, "quote_months", "admin_quote_ask_months", clear=('quote_wizard',))


async def admin_quote_months(update, context, text):
    raw = (text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await _send(update, i18n.t("admin_bad_months"))
        return
    context.user_data["quote_wizard"] = {"months": int(raw)}
    context.user_data["awaiting"] = "quote_bots"
    await _send(update, i18n.t("admin_quote_ask_bots"))


async def admin_quote_bots(update, context, text):
    raw = (text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await _send(update, i18n.t("admin_bad_number"))
        return
    context.user_data["quote_wizard"]["bots"] = int(raw)
    context.user_data["awaiting"] = "quote_features"
    await _send(update, i18n.t("admin_quote_ask_features",
                               codes="\n".join(f"  • {code}" for code in sorted(catalog.features()))))


async def admin_quote_features(update, context, text):
    from licensing.telegram.sales.wizard import _NO_PASSWORD_MARKERS

    raw = (text or "").strip()
    features = [] if raw.lower() in _NO_PASSWORD_MARKERS \
        else [f.strip() for f in raw.replace("،", ",").split(",") if f.strip()]

    state = context.user_data.pop("quote_wizard", {})
    context.user_data.pop("awaiting", None)
    quote = pricing.quote(state.get("months", 1), state.get("bots", 1), features, db=_db(context))
    await _send(update, _quote_text(quote), kb.admin_back())
