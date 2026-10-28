"""
متن‌های ربات — همه از فایل‌های ترجمه (licensing/locales/*.json) می‌آن.

## چرا هیچ متنی اینجا نوشته نشده

قبلاً همه‌ی متن‌ها فارسیِ درون‌کد بودن. حالا این فایل فقط «چطور سرهم
می‌شن» رو می‌دونه، نه «چی نوشته شده». اضافه‌کردن یه زبان جدید یعنی یه فایل
JSON، بدون هیچ تغییری توی کد.

## چرا ثابت‌ها هنوز ثابت به‌نظر می‌رسن

جاهای فراخوانی از قبل `T.ADMIN_ONLY` و `T.CANCELLED` می‌نویسن. اگه این‌ها
به تابع تبدیل می‌شدن، صدها نقطه باید عوض می‌شد -- و بدتر: یه ثابت
ماژول‌سطح *لحظه‌ی import* مقدار می‌گیره، یعنی زبانِ اولین کاربر روی همه
قفل می‌شد.

`__getattr__` سطح ماژول (PEP 562) هر دو مشکل رو حل می‌کنه: `T.ADMIN_ONLY`
دقیقاً همون شکل قبلی رو داره ولی *لحظه‌ی دسترسی* ترجمه می‌شه، با زبان
همون کاربر.

## زبان از کجا می‌آد

از یه ContextVar که اول هر آپدیت ست می‌شه (licensing/i18n.py). چون هر
آپدیت تلگرام توی Task جدای asyncio اجرا می‌شه، دو کاربر هم‌زمان با دو
زبان مختلف تداخلی ندارن.
"""

import html
import time

from licensing import catalog
from licensing import i18n
from licensing import pricing

# ثابت‌هایی که اسمشون دقیقاً lower() کلیدشون نیست.
_ALIASES = {
    "LICENSE_BOT_QUOTA_FULL": "license_quota_full",
}

# چیزهایی که واقعاً ماژول‌سطح‌ان و نباید از ترجمه بیان.
_REAL_ATTRS = {"html", "time", "catalog", "i18n", "pricing"}


def __getattr__(name):
    """
    `T.SOMETHING` -> ترجمه‌ی کلید `something` به زبان کاربر فعلی.

    فقط برای اسم‌های ALL_CAPS کار می‌کنه تا یه اشتباه تایپی توی اسم تابع،
    بی‌سروصدا به یه رشته تبدیل نشه.
    """
    if not name.isupper():
        raise AttributeError(f"module 'texts' has no attribute {name!r}")
    if name == "HELP":
        return _help_text()
    return i18n.t(_ALIASES.get(name, name.lower()))


def _help_text():
    """راهنما لیست امکانات رو از کاتالوگ می‌گیره، پس نمی‌تونه ثابت باشه."""
    is_fa = i18n.get_language() == "fa"
    lines = [
        i18n.t("help_feature_line",
               title=esc(feature.get("title_fa") if is_fa
                         else feature.get("title_en") or feature.get("title_fa")),
               # قبلاً همیشه note_fa بود، حتی توی راهنمای انگلیسی.
               note=esc(feature.get("note_fa" if is_fa else "note_en")
                        or feature.get("note_fa" if not is_fa else "note_en", "")))
        for feature in catalog.features().values()
    ]
    return i18n.t("help", features="\n".join(lines))


# ---------------------------------------------------------------- ابزار

def esc(value):
    return html.escape(str(value if value is not None else ""))


def fmt_date(timestamp):
    if not timestamp:
        return i18n.t("dash")
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))


def fmt_duration(seconds):
    seconds = int(seconds)
    if seconds <= 0:
        return i18n.t("duration_finished")
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return i18n.t("duration_days_hours", days=days, hours=hours)
    if hours:
        return i18n.t("duration_hours_minutes", hours=hours, minutes=minutes)
    return i18n.t("duration_minutes", minutes=minutes)


def feature_title(code):
    """
    اسم یه امکان به زبان فعلی. کاتالوگ فارسی و انگلیسی هر دو رو داره.
    """
    feature = catalog.features().get(code) or catalog.bundles().get(code)
    if not feature:
        return code
    if i18n.get_language() == "fa":
        return feature.get("title_fa") or feature.get("title_en") or code
    return feature.get("title_en") or feature.get("title_fa") or code


def feature_list(codes, empty_key="features_only_youtube"):
    codes = catalog.expand_features(codes or [])
    if not codes:
        return i18n.t(empty_key)
    return "، ".join(feature_title(code) for code in codes) if i18n.get_language() == "fa" \
        else ", ".join(feature_title(code) for code in codes)


# ---------------------------------------------------------------- منو

def welcome(first_name, has_license):
    greeting = (i18n.t("greeting_named", name=esc(first_name)) if first_name
                else i18n.t("greeting_plain"))
    body = i18n.t("welcome_returning" if has_license else "welcome_new")
    return f"{greeting}\n\n{body}"


# ---------------------------------------------------------------- خرید

def panels_intro():
    return i18n.t("panels_intro")


def configurator(months, bots, features, quote):
    feature_lines = (
        "\n".join(i18n.t("cfg_feature_line", title=esc(feature_title(code))) for code in features)
        if features else i18n.t("cfg_features_none")
    )
    parts = [
        i18n.t("cfg_title"), "",
        i18n.t("cfg_months", months=months),
        i18n.t("cfg_bots", bots=bots),
        i18n.t("cfg_features"), feature_lines, "",
        i18n.t("cfg_monthly", monthly=pricing.format_usd(quote["monthly_usd"])),
        i18n.t("cfg_total", total=pricing.format_usd(quote["total_usd"]))
        + (f" ≈ <b>{pricing.format_irr(quote['total_irr'])}</b>" if quote["total_irr"] else ""),
    ]
    return "\n".join(parts)


def invoice(quote, order_id=None):
    text = [i18n.t("invoice_title")]
    if order_id:
        text.append(i18n.t("invoice_order_no", order_id=order_id))
    text += [
        "",
        i18n.t("invoice_duration", months=quote["months"]),
        i18n.t("invoice_bots", bots=quote["bots"]),
        "",
        i18n.t("invoice_monthly_lines"),
    ]
    for line in quote["lines"]:
        text.append(i18n.t("invoice_line", title=esc(line["title"]),
                           amount=pricing.format_usd(line["usd"])))
    text += ["", i18n.t("invoice_monthly_total",
                        amount=pricing.format_usd(quote["monthly_usd"]))]

    if quote["months"] > 1:
        saved = quote["months"] - quote["duration_multiplier"]
        if saved > 0.01:
            text.append(i18n.t(
                "invoice_duration_discount", months=quote["months"],
                amount=pricing.format_usd(round(quote["monthly_usd"] * saved, 2))))
    if quote["bundle_savings_usd"]:
        text.append(i18n.t("invoice_bundle_discount",
                           amount=pricing.format_usd(quote["bundle_savings_usd"])))

    text += ["", i18n.t("invoice_payable", amount=pricing.format_usd(quote["total_usd"]))]
    if quote["total_irr"]:
        text.append(i18n.t("invoice_payable_irr", amount=pricing.format_irr(quote["total_irr"])))
        if quote["rate_stale"]:
            text.append(i18n.t("invoice_rate_stale"))
    else:
        text.append(i18n.t("invoice_no_rate"))
    return "\n".join(text)


def payment_instructions(order, payment, quote=None):
    parts = [
        i18n.t("payment_title", order_id=order["id"]), "",
        i18n.t("payment_usd", amount=pricing.format_usd(order["amount_usd"])),
    ]
    if order["amount_irr"]:
        parts.append(i18n.t("payment_irr", amount=pricing.format_irr(order["amount_irr"])))
    parts += ["", i18n.t("payment_card", card=esc(payment["card_number"]))]
    if payment.get("card_holder"):
        parts.append(i18n.t("payment_holder", name=esc(payment["card_holder"])))
    if payment.get("card_bank"):
        parts.append(i18n.t("payment_bank", bank=esc(payment["card_bank"])))
    parts += [
        "", i18n.t("payment_copy_hint"),
        "", i18n.t("payment_send_receipt"),
        i18n.t("payment_receipt_hint"),
        "", i18n.t("payment_expires", timeout=_order_timeout_text()),
    ]
    return "\n".join(parts)


def crypto_invoice(payment, note=None):
    """
    فاکتور پرداخت با تتر. مبلغ و آدرس داخل <code> هستن تا با یه لمس کپی بشن.
    note یه خط اضافه‌ی آخره (نتیجه‌ی آخرین بررسی).
    """
    from licensing import crypto_pay
    label = crypto_pay.NETWORKS[payment["network"]].label
    left = max(0, int(payment["expires_at"]) - int(time.time())) // 60
    parts = [
        i18n.t("crypto_title", order_id=payment["order_id"]), "",
        i18n.t("crypto_send_exact", label=esc(label)),
        i18n.t("crypto_amount", amount=crypto_pay.format_amount(payment["amount_micro"])), "",
        i18n.t("crypto_address", address=esc(payment["address"])), "",
        i18n.t("crypto_warning"), "",
        i18n.t("crypto_expires", time=fmt_date(payment["expires_at"]), minutes=left),
        i18n.t("crypto_auto_hint"),
    ]
    if note:
        parts += ["", note]
    return "\n".join(parts)


def _order_timeout_text():
    from licensing import config
    minutes = int(config.get("order_timeout_minutes", 180))
    if minutes % 60 == 0:
        return i18n.t("payment_timeout_hours", hours=minutes // 60)
    return i18n.t("payment_timeout_minutes", minutes=minutes)


# ---------------------------------------------------------------- رسید

def receipt_check_failed_user(check):
    return i18n.t("receipt_check_failed", summary=esc(check.summary()))


def receipt_duplicate_user():
    return i18n.t("receipt_duplicate")


def order_approved(license_row, needs_setup):
    text = i18n.t("order_approved",
                  key=esc(license_row["key"]),
                  bots=license_row["max_bots"],
                  expires=fmt_date(license_row["expires_at"]))
    if needs_setup:
        text += "\n" + i18n.t("order_approved_setup")
    return text


def order_rejected(reason):
    detail = i18n.t("order_rejected_reason", reason=esc(reason)) if reason else ""
    return i18n.t("order_rejected", reason=detail)


# ------------------------------------------------------- لایسنس و ربات

def license_card(license_row, status_text, instances):
    from licensing.db import json_list
    features = catalog.expand_features(json_list(license_row["features"]))
    feature_lines = (
        "\n".join(i18n.t("cfg_feature_line", title=esc(feature_title(code))) for code in features)
        if features else i18n.t("cfg_features_none")
    )
    instance_lines = (
        "\n".join(i18n.t("license_bot_line", slug=esc(row["slug"]), host=esc(row["tt_host"]),
                         port=row["tt_port"], status=esc(instance_status(row["status"])))
                  for row in instances)
        if instances else i18n.t("license_no_bots")
    )
    return "\n".join([
        i18n.t("license_key", key=esc(license_row["key"])),
        i18n.t("license_status", status=esc(status_text)),
        i18n.t("license_starts", date=fmt_date(license_row["starts_at"])),
        i18n.t("license_ends", date=fmt_date(license_row["expires_at"])),
        i18n.t("license_bot_quota", used=len(instances), total=license_row["max_bots"]),
        "", i18n.t("license_features_title"), feature_lines,
        "", i18n.t("license_bots_title"), instance_lines,
    ])


def instance_status(status):
    return i18n.t(f"status_{status}") if i18n.has(f"status_{status}") else status


def instance_card(instance_row, live_status=None):
    parts = [
        i18n.t("instance_title", slug=esc(instance_row["slug"])),
        i18n.t("instance_server", host=esc(instance_row["tt_host"]), port=instance_row["tt_port"]),
        i18n.t("instance_nickname", nickname=esc(instance_row["tt_nickname"])),
        i18n.t("instance_username", username=esc(instance_row["tt_username"])),
        i18n.t("instance_channel", channel=instance_row["tt_channel_id"]),
        i18n.t("instance_line", line=esc(instance_row["audio_line"])),
        i18n.t("instance_status", status=esc(instance_status(instance_row["status"]))),
    ]
    if live_status:
        if live_status["alive"]:
            parts.append(i18n.t("instance_live_running",
                                uptime=fmt_duration(live_status["uptime_seconds"])))
        else:
            parts.append(i18n.t("instance_live_stopped"))
        if live_status["failures"]:
            parts.append(i18n.t("instance_failures", count=live_status["failures"]))
    return "\n".join(parts)


# ---------------------------------------------------------- راه‌اندازی

def setup_operators_cap(limit):
    """
    هشدارِ بریدنِ اپراتورها به سقفِ فنی (نه سهمیه‌ی خریداری‌شده -- اپراتورها
    از تصمیم ۲۰۲۶-۰۹-۱۶ نامحدودن، فقط setup_wizard.MAX_OPERATORS یه سقفِ
    فنی می‌ذاره).
    """
    return i18n.t("setup_operators_cap", limit=limit)


def setup_review(data):
    locked = i18n.t("setup_review_channel_locked") if data.get("channel_password") else ""
    return "\n".join([
        i18n.t("setup_review_title"), "",
        i18n.t("setup_review_server", host=esc(data["host"]), port=data["port"]),
        i18n.t("setup_review_nickname", nickname=esc(data["nickname"])),
        i18n.t("setup_review_username", username=esc(data["username"])),
        i18n.t("setup_review_password"),
        i18n.t("setup_review_channel", channel=data["channel_id"]) + locked,
        i18n.t("setup_review_operators",
               operators=esc(", ".join(data.get("operators") or []) or i18n.t("dash"))),
        "", i18n.t("setup_review_confirm"),
    ])


def setup_done(instance_row, line_output, line_input):
    return i18n.t("setup_done", slug=esc(instance_row["slug"]),
                  line=esc(instance_row["audio_line"]),
                  output=esc(line_output), input=esc(line_input))


def setup_failed():
    # عمداً بدون جزئیاتِ exception: هیچ‌وقت خطای خام به کاربر نشون داده
    # نمی‌شه؛ traceback کامل با logging_setup.log_exception توی
    # errors/errors.log ذخیره می‌شه، جایی که صداکننده باید صداش زده باشه.
    return i18n.t("setup_failed")


# ------------------------------------------------------- ربات شخصی

def personal_bot_ready(username):
    return i18n.t("personal_bot_ready", username=esc(username))


# ------------------------------------------------------------ هدیه

def gift_received(hours, license_row):
    return i18n.t("gift_received", hours=esc(hours), key=esc(license_row["key"]),
                  expires=fmt_date(license_row["expires_at"]))


# ---------------------------------------------------------- پشتیبانی

def support_reply(text):
    return i18n.t("support_reply", text=esc(text))


# -------------------------------------------------------------- ادمین

def admin_panel(stats, rate_state, capacity):
    if rate_state["rate"]:
        stale = i18n.t("admin_rate_stale_suffix") if rate_state["stale"] else ""
        rate_line = i18n.t("admin_rate_value", amount=pricing.format_irr(rate_state["rate"]),
                           source=esc(rate_state["source"]), stale=stale)
    else:
        rate_line = i18n.t("admin_rate_unset")

    lines_text = i18n.t(
        "admin_lines", count=capacity["lines_total"],
        manageable=i18n.t("admin_lines_manageable" if capacity["manageable"]
                          else "admin_lines_allocate_only"),
        backend=esc(capacity["backend"]))
    if capacity["lines_dead"]:
        lines_text += i18n.t("admin_lines_dead", count=capacity["lines_dead"])
    if capacity.get("free_windows_lines") is not None:
        lines_text += i18n.t("admin_free_windows_lines", count=capacity["free_windows_lines"])

    return "\n".join([
        i18n.t("admin_panel_title"), "",
        i18n.t("admin_users", count=stats["users"]),
        i18n.t("admin_licenses", active=stats["licenses_active"], expired=stats["licenses_expired"]),
        i18n.t("admin_bots", running=stats["instances_running"], total=stats["instances_total"]),
        i18n.t("admin_orders_pending", count=stats["orders_pending"]),
        i18n.t("admin_orders_approved", count=stats["orders_approved"]),
        i18n.t("admin_revenue", amount=pricing.format_usd(stats["revenue_usd"] or 0)),
        i18n.t("admin_tickets", count=stats["tickets_open"]),
        i18n.t("admin_promos", active=stats.get("promos_active", 0),
               redemptions=stats.get("promo_redemptions", 0)),
        "", i18n.t("admin_rate", rate=rate_line), lines_text,
    ])


def amount_shown_to_user(order, current_rate=None):
    """
    دقیقاً همون مبلغی که *لحظه‌ی سفارش* به کاربر نشون داده شد و کپی کرد.

    چرا مهمه: نرخ دلار بین ثبت سفارش و واریز ممکنه تکون خورده باشه. اگه
    ادمین فقط مبلغ «الان» رو ببینه، یه رسید درست ممکنه اشتباهاً کم به‌نظر
    برسه. پس همون عدد تاریخی نشون داده می‌شه، و اگه نرخ عوض شده باشه
    تفاوتش هم صریح گفته می‌شه.
    """
    lines = [
        i18n.t("amount_shown_title"),
        i18n.t("amount_shown_usd", amount=pricing.format_usd(order["amount_usd"])),
    ]
    if order["amount_irr"]:
        lines.append(i18n.t("amount_shown_irr", amount=pricing.format_irr(order["amount_irr"])))
    else:
        lines.append(i18n.t("amount_shown_irr_missing"))

    if order["usd_rate"]:
        lines.append(i18n.t("amount_shown_rate", rate=pricing.format_irr(order["usd_rate"])))
        lines.append(i18n.t("amount_shown_when", date=fmt_date(order["created_at"])))

    if current_rate and order["usd_rate"]:
        drift = current_rate - int(order["usd_rate"])
        percent = drift / int(order["usd_rate"]) * 100
        if abs(percent) >= 1:
            lines.append(i18n.t(
                "amount_shown_drift",
                percent=f"{abs(percent):.0f}",
                direction=i18n.t("rate_direction_up" if drift > 0 else "rate_direction_down"),
                current=pricing.format_irr(current_rate),
                now_amount=pricing.format_irr(
                    pricing.round_irr(float(order["amount_usd"]) * current_rate)),
            ))
    return "\n".join(lines)


def admin_order_review(order, user_row, check_dict, current_rate=None):
    from licensing import receipts
    from licensing.db import json_list

    verdict = check_dict.get("verdict", "unreadable")
    emoji = {"match": "🟢", "suspicious": "🟡", "mismatch": "🔴",
             "unreadable": "⚪️"}.get(verdict, "⚪️")
    notes = "\n".join(f"  • {esc(note)}" for note in check_dict.get("notes", [])) or "  —"
    username = f"@{esc(user_row['username'])}" if user_row and user_row["username"] else i18n.t("dash")

    return "\n".join([
        i18n.t("admin_order_title", order_id=order["id"]), "",
        i18n.t("admin_order_user", username=username, user_id=order["user_id"]),
        i18n.t("admin_order_package", months=order["months"], bots=order["bots"]),
        i18n.t("admin_order_features",
               features=esc(feature_list(json_list(order["features"])))),
        "", amount_shown_to_user(order, current_rate), "",
        i18n.t("admin_order_check", emoji=emoji,
               verdict=esc(receipts.verdict_text(verdict)),
               score=check_dict.get("score", 0)),
        notes, "",
        i18n.t("admin_order_reference",
               reference=esc(check_dict.get("reference") or i18n.t("dash"))),
        "", i18n.t("admin_order_final_say"),
    ])


def admin_rate_report(state):
    if not state.get("rate"):
        return i18n.t("rate_report_unavailable", error=esc(state.get("error", "unknown")))
    age = state.get("age_seconds")
    age_text = i18n.t("rate_ago", duration=fmt_duration(age)) if age else i18n.t("rate_just_now")
    text = "\n".join([
        i18n.t("rate_report_current", rate=pricing.format_irr(state["rate"])),
        i18n.t("rate_report_source", source=esc(state["source"])),
        i18n.t("rate_report_updated", age=esc(age_text)),
    ])
    if state.get("stale"):
        text += i18n.t("rate_report_stale")
    if state["source"] == "manual":
        text += i18n.t("rate_report_manual")
    return text


def sweep_report(result):
    lines = [i18n.t("sweep_title"), "", esc(sweep_summary(result))]
    if result.expired:
        lines.append(i18n.t("sweep_expired_title"))
        lines += [i18n.t("sweep_entry", key=esc(row["key"])) for row in result.expired]
    if result.purged:
        lines.append(i18n.t("sweep_purged_title"))
        lines += [i18n.t("sweep_entry", key=esc(row["key"])) for row in result.purged]
    if result.errors:
        lines.append(i18n.t("sweep_errors_title"))
        lines += [i18n.t("sweep_error_entry", error=esc(err)) for err in result.errors[:10]]
    return "\n".join(lines)


def daily_report(data):
    """گزارشِ روزانه‌ی ادمین‌ها از خروجیِ licensing.daily_report.collect."""
    from licensing import crypto_pay
    bots, errors, expiring = data["bots"], data["errors"], data["expiring"]
    lines = [i18n.t("report_title", date=fmt_date(data["now"])), "",
             i18n.t("report_bots", running=bots["running"], crashed=bots["crashed"],
                    blocked=bots["blocked"]),
             i18n.t("report_errors", count=errors["count"])]
    lines += [i18n.t("report_error_line", context=esc(context), count=count)
              for context, count in errors["top"]]
    lines.append(i18n.t("report_expiring", count=expiring["count"]))
    lines += [i18n.t("report_expiring_line", key=esc(item["key"]), user=esc(item["user"]),
                     date=fmt_date(item["expires_at"]))
              for item in expiring["items"]]
    if expiring["count"] > len(expiring["items"]):
        lines.append(i18n.t("report_more", count=expiring["count"] - len(expiring["items"])))
    lines.append(i18n.t("report_orders", count=data["orders_pending"]))
    if data["crypto"] is not None:
        crypto = data["crypto"]
        lines.append(i18n.t("report_crypto", pending=crypto["pending"],
                            received=crypto["received"],
                            amount=crypto_pay.format_amount(crypto["received_micro"])))
    return "\n".join(lines)


def sweep_summary(result):
    return result.summary_fa()
