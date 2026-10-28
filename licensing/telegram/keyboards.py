"""
کیبوردهای inline.

قاعده‌ی callback_data: همیشه "<حوزه>:<کار>[:<آرگومان>...]" — مثل
"order:approve:42". تلگرام سقف ۶۴ بایت داره، پس هیچ‌جا متن طولانی توی
callback گذاشته نمی‌شه؛ فقط شناسه‌ی عددی و کد کوتاه.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from licensing import catalog
from licensing import config
from licensing import crypto_pay
from licensing import i18n
from licensing import licenses
from licensing import pricing

# میان‌بر: هر برچسب دکمه از فایل ترجمه می‌آد، نه از متن درون‌کد.
_ = i18n.t


def main_menu(has_license, is_admin=False):
    rows = [
        [InlineKeyboardButton(_("menu_buy"), callback_data="buy:panels")],
    ]
    if has_license:
        rows.append([
            InlineKeyboardButton(_("menu_licenses"), callback_data="lic:list"),
            InlineKeyboardButton(_("menu_bots"), callback_data="inst:list"),
        ])
        rows.append([InlineKeyboardButton(_("menu_personal_bot"), callback_data="pbot:info")])
    rows.append([InlineKeyboardButton(_("menu_promo"), callback_data="promo:new")])
    rows.append([
        InlineKeyboardButton(_("menu_help"), callback_data="nav:help"),
        InlineKeyboardButton(_("menu_support"), callback_data="sup:new"),
    ])
    rows.append([InlineKeyboardButton(_("menu_language"), callback_data="lang:pick")])
    if is_admin:
        rows.append([InlineKeyboardButton(_("menu_admin"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def back_to_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")]])


def language_picker(current):
    """
    انتخاب زبان. اسم هر زبان به *خودِ اون زبان* نوشته می‌شه، نه ترجمه‌شده --
    کسی که زبان فعلی رو نمی‌فهمه باید بتونه زبان خودش رو پیدا کنه.
    """
    rows = []
    for code, name in i18n.available():
        mark = "✅" if code == current else "▫️"
        rows.append([InlineKeyboardButton(
            _("language_button", mark=mark, name=name), callback_data=f"lang:set:{code}")])
    rows.append([InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# خرید
# ---------------------------------------------------------------------------

def _panel_title(panel):
    """عنوان پنل به زبان فعلی (کاتالوگ هر دو رو داره)."""
    if i18n.get_language() == "fa":
        return panel.get("title_fa") or panel.get("title_en") or panel.get("code")
    return panel.get("title_en") or panel.get("title_fa") or panel.get("code")


def _feature_title(feature, code):
    if i18n.get_language() == "fa":
        return feature.get("title_fa") or feature.get("title_en") or code
    return feature.get("title_en") or feature.get("title_fa") or code


def panels(db=None):
    rows = []
    for panel in catalog.panels():
        # panel.get("features", []) — نه panel["users"]: یه override قدیمی
        # ممکنه هنوز کلید users رو روی پنل داشته باشه (سازگاری)، ولی دیگه
        # به quote پاس داده نمی‌شه.
        quote = pricing.quote(panel["months"], panel["bots"],
                              panel.get("features", []), db=db)
        price = pricing.format_usd(quote["total_usd"])
        if quote["total_irr"]:
            price += f" / {pricing.format_irr(quote['total_irr'])}"
        rows.append([InlineKeyboardButton(
            f"{_panel_title(panel)} — {price}",
            callback_data=f"buy:panel:{panel['code']}",
        )])
    rows.append([InlineKeyboardButton(_("btn_custom"), callback_data="buy:custom")])
    rows.append([InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")])
    return InlineKeyboardMarkup(rows)


def configurator(months, bots):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data="cfg:months:-1"),
            InlineKeyboardButton(_("cfg_months_label", months=months), callback_data="cfg:noop"),
            InlineKeyboardButton("➕", callback_data="cfg:months:+1"),
        ],
        [
            InlineKeyboardButton("➖", callback_data="cfg:bots:-1"),
            InlineKeyboardButton(_("cfg_bots_label", bots=bots), callback_data="cfg:noop"),
            InlineKeyboardButton("➕", callback_data="cfg:bots:+1"),
        ],
        [InlineKeyboardButton(_("btn_pick_features"), callback_data="cfg:features")],
        [InlineKeyboardButton(_("btn_see_invoice"), callback_data="cfg:review")],
        [InlineKeyboardButton(_("btn_ready_panels"), callback_data="buy:panels")],
    ])


def feature_picker(selected, target="cfg", show_price=True, allow_all=False):
    """
    هر امکان یه دکمه‌ی toggle. عدد قیمت روی دکمه‌ست تا کاربر لازم نباشه
    جای دیگه‌ای دنبالش بگرده.

    show_price=False برای لایسنسِ هدیه‌ی ادمین (قیمت اون‌جا بی‌معنیه)؛
    allow_all یه دکمه‌ی «همه» اضافه می‌کنه ({target}:tall).
    """
    selected = set(selected or [])
    rows = []
    for code, feature in catalog.features().items():
        mark = "✅" if code in selected else "◻️"
        title = _feature_title(feature, code)
        if show_price:
            label = _("feature_button", mark=mark, title=title,
                      price=pricing.format_usd(feature.get("price_usd", 0)))
        else:
            label = f"{mark} {title}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{target}:tf:{code}")])
    for code, bundle in catalog.bundles().items():
        title = _feature_title(bundle, code)
        if show_price:
            label = _("bundle_button", title=title,
                      price=pricing.format_usd(bundle.get("price_usd", 0)))
        else:
            label = f"📦 {title}"
        rows.append([InlineKeyboardButton(label, callback_data=f"{target}:tb:{code}")])
    last = [InlineKeyboardButton(_("btn_clear_all"), callback_data=f"{target}:tclear")]
    if allow_all:
        last.insert(0, InlineKeyboardButton(_("btn_select_all"), callback_data=f"{target}:tall"))
    rows.append(last)
    rows.append([InlineKeyboardButton(_("btn_done"), callback_data=f"{target}:done")])
    return InlineKeyboardMarkup(rows)


def admin_gift(state):
    """
    ویزاردِ دکمه‌ایِ لایسنسِ هدیه/اجاره‌ای (admin_gift.py): مدت با روز و ماه،
    تعداد ربات، انتخابِ امکانات، و صدور -- بدونِ تایپِ هیچ عدد یا کدی.
    """
    days, bots = int(state["days"]), int(state["bots"])
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_("btn_gift_day_minus"), callback_data="agr:d:-1"),
            InlineKeyboardButton(_("gift_days_label", days=days), callback_data="agr:noop"),
            InlineKeyboardButton(_("btn_gift_day_plus"), callback_data="agr:d:+1"),
        ],
        [
            InlineKeyboardButton(_("btn_gift_month_minus"), callback_data="agr:d:-30"),
            InlineKeyboardButton(_("btn_gift_month_plus"), callback_data="agr:d:+30"),
        ],
        [
            InlineKeyboardButton("➖", callback_data="agr:b:-1"),
            InlineKeyboardButton(_("cfg_bots_label", bots=bots), callback_data="agr:noop"),
            InlineKeyboardButton("➕", callback_data="agr:b:+1"),
        ],
        [InlineKeyboardButton(_("btn_pick_features"), callback_data="agr:feat")],
        [
            InlineKeyboardButton(_("btn_gift_issue"), callback_data="agr:issue"),
            InlineKeyboardButton(_("btn_gift_cancel"), callback_data="agr:cancel"),
        ],
    ])


def _crypto_pay_button(callback_data):
    """دکمه‌ی پرداخت با تتر، یا None اگه خاموشه/آدرس نداره."""
    settings = config.crypto_settings()
    if not crypto_pay.available(settings):
        return None
    label = crypto_pay.NETWORKS[settings["network"]].label
    return [InlineKeyboardButton(_("btn_pay_crypto", label=label), callback_data=callback_data)]


def invoice_actions(order_id=None, from_config=True, card=True):
    """card=False فقط وقتی که کارتی تنظیم نشده و تتر جایگزینشه."""
    rows = []
    if card:
        rows.append([InlineKeyboardButton(_("btn_pay"), callback_data="buy:confirm")])
    crypto_row = _crypto_pay_button("buy:crypto")
    if crypto_row:
        rows.append(crypto_row)
    if from_config:
        rows.append([InlineKeyboardButton(_("btn_change_order"), callback_data="buy:custom")])
    rows.append([InlineKeyboardButton(_("btn_ready_panels"), callback_data="buy:panels")])
    return InlineKeyboardMarkup(rows)


def payment_actions(order_id):
    rows = []
    crypto_row = _crypto_pay_button(f"buy:crypto:{order_id}")
    if crypto_row:
        rows.append(crypto_row)
    rows.append([InlineKeyboardButton(_("btn_cancel_order"), callback_data=f"buy:cancel:{order_id}")])
    rows.append([InlineKeyboardButton(_("menu_support"), callback_data="sup:new")])
    return InlineKeyboardMarkup(rows)


def crypto_actions(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_crypto_check"), callback_data=f"buy:cchk:{order_id}")],
        [InlineKeyboardButton(_("btn_cancel_order"), callback_data=f"buy:cancel:{order_id}")],
        [InlineKeyboardButton(_("menu_support"), callback_data="sup:new")],
    ])


# ---------------------------------------------------------------------------
# لایسنس و نمونه‌ها
# ---------------------------------------------------------------------------

def license_list(license_rows):
    rows = []
    for row in license_rows:
        marker = {"active": "🟢", "expired": "🔴", "suspended": "🟡", "revoked": "⚫️"}.get(row["status"], "⚪️")
        rows.append([InlineKeyboardButton(
            f"{marker} {row['key']}", callback_data=f"lic:show:{row['id']}")])
    rows.append([InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")])
    return InlineKeyboardMarkup(rows)


def license_actions(license_row, can_add_bot, is_admin=False):
    rows = []
    if can_add_bot:
        rows.append([InlineKeyboardButton(_("btn_setup_bot"), callback_data=f"setup:start:{license_row['id']}")])
    rows.append([
        InlineKeyboardButton(_("btn_renew"), callback_data=f"lic:renew:{license_row['id']}"),
        InlineKeyboardButton(_("btn_add_features"), callback_data=f"lic:addon:{license_row['id']}"),
    ])
    rows.append([InlineKeyboardButton(_("btn_license_bots"), callback_data=f"inst:of:{license_row['id']}")])
    # کارهای ادمینی (B8): تمدیدِ سریع، تعلیق/رفعِ تعلیق، لغو -- همه با
    # دکمه، بدون این‌که لازم باشه دستورِ متنی یاد بگیره. هر لایسنسی که
    # ادمین باز می‌کنه این‌ها رو داره، نه فقط لایسنسِ خودش.
    if is_admin:
        rows.append([
            InlineKeyboardButton(_("btn_admin_extend", months=1), callback_data=f"adm:ext:{license_row['id']}:1"),
            InlineKeyboardButton(_("btn_admin_extend", months=3), callback_data=f"adm:ext:{license_row['id']}:3"),
            InlineKeyboardButton(_("btn_admin_extend", months=12), callback_data=f"adm:ext:{license_row['id']}:12"),
        ])
        if license_row["status"] == licenses.STATUS_SUSPENDED:
            rows.append([InlineKeyboardButton(_("btn_admin_resume"),
                                              callback_data=f"adm:resume:{license_row['id']}")])
        else:
            rows.append([InlineKeyboardButton(_("btn_admin_suspend"),
                                              callback_data=f"adm:suspend:{license_row['id']}")])
        if license_row["status"] != licenses.STATUS_REVOKED:
            rows.append([InlineKeyboardButton(_("btn_admin_revoke"),
                                              callback_data=f"adm:revoke:{license_row['id']}")])
    # پاک‌کردن لایسنس فقط دست ادمینه و برگشت‌ناپذیره، پس جدا از بقیه و
    # آخر از همه می‌شینه تا تصادفی زده نشه.
    if is_admin:
        rows.append([InlineKeyboardButton(_("btn_delete_license"),
                                          callback_data=f"lic:del:{license_row['id']}")])
    rows.append([InlineKeyboardButton(_("btn_licenses"), callback_data="lic:list")])
    return InlineKeyboardMarkup(rows)


def admin_rental_done(license_key):
    """کارهای بعدیِ یه لایسنس اجاره‌ایِ تازه صادرشده."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_rental_machines"), callback_data=f"adm:rmach:{license_key}")],
        [InlineKeyboardButton(_("btn_rental_reset"), callback_data=f"adm:rreset:{license_key}:30")],
        [InlineKeyboardButton(_("btn_rental_revoke"), callback_data=f"adm:rrev:{license_key}")],
        [InlineKeyboardButton(_("btn_back"), callback_data="adm:panel")],
    ])


def renew_durations(license_id):
    rows = []
    for months in sorted(int(m) for m in catalog.pricing().get("duration_multipliers", {})):
        rows.append([InlineKeyboardButton(
            _("renew_button", months=months), callback_data=f"lic:renewm:{license_id}:{months}")])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data=f"lic:show:{license_id}")])
    return InlineKeyboardMarkup(rows)


def instance_list(instance_rows, back="nav:menu"):
    rows = []
    for row in instance_rows:
        marker = {"running": "🟢", "stopped": "⚪️", "crashed": "🟡",
                  "blocked": "🔴", "missing": "⚠️"}.get(row["status"], "⚪️")
        rows.append([InlineKeyboardButton(
            f"{marker} {row['slug']} — {row['tt_host']}",
            callback_data=f"inst:show:{row['id']}")])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data=back)])
    return InlineKeyboardMarkup(rows)


def instance_actions(instance_row, is_admin=False):
    rows = [[
        InlineKeyboardButton(_("btn_restart"), callback_data=f"inst:restart:{instance_row['id']}"),
        InlineKeyboardButton(_("btn_stop"), callback_data=f"inst:stop:{instance_row['id']}"),
    ], [
        InlineKeyboardButton(_("btn_start"), callback_data=f"inst:start:{instance_row['id']}"),
        InlineKeyboardButton(_("btn_edit_bot"), callback_data=f"inst:edit:{instance_row['id']}"),
    ], [
        InlineKeyboardButton(_("btn_delete_bot"), callback_data=f"inst:del:{instance_row['id']}"),
        InlineKeyboardButton(_("btn_cookies"), callback_data=f"ck:menu:{instance_row['id']}"),
    ]]
    rows.append([InlineKeyboardButton(_("btn_bots"), callback_data="inst:list")])
    return InlineKeyboardMarkup(rows)


def cookies_menu(instance_id, services, present):
    """
    صفحه‌ی کوکی‌های یه ربات: برای هر سرویس یه دکمه‌ی افزودن/جایگزینی، و برای
    سرویس‌هایی که کوکی دارن دکمه‌ی حذف. `services` لیست اسم‌ها، `present`
    مجموعه‌ی اسم‌هایی که فایل دارن.
    """
    rows = []
    for name in services:
        mark = "✅" if name in present else "➕"
        row = [InlineKeyboardButton(f"{mark} {name}", callback_data=f"ck:add:{instance_id}:{name}")]
        if name in present:
            row.append(InlineKeyboardButton(_("btn_cookies_delete"),
                                            callback_data=f"ck:del:{instance_id}:{name}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(_("btn_cookies_other"), callback_data=f"ck:other:{instance_id}")])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data=f"inst:show:{instance_id}")])
    return InlineKeyboardMarkup(rows)


def cookie_alert_actions(instance_id):
    """زیرِ پیامِ «ربات کوکی می‌خواد»: یه دکمه مستقیم به منوی کوکیِ همون ربات."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_cookies"), callback_data=f"ck:menu:{instance_id}")]])


def cookies_saved_actions(instance_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_restart"), callback_data=f"inst:restart:{instance_id}")],
        [InlineKeyboardButton(_("btn_back"), callback_data=f"ck:menu:{instance_id}")],
    ])


def cookies_cancel(instance_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_confirm_no"), callback_data=f"ck:menu:{instance_id}")]])


def admin_panels_list(panel_rows):
    """
    panel_rows: [(code, title, price_text)]. مدیریتِ پنل‌های آماده‌ی
    فروش -- دیدن/ویرایش/افزودن/حذف، همه با دکمه.
    """
    rows = [[InlineKeyboardButton(f"{title} — {price}", callback_data=f"pnl:show:{code}")]
            for code, title, price in panel_rows]
    rows.append([InlineKeyboardButton(_("btn_panel_add"), callback_data="pnl:new")])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def admin_panel_editor(state, is_new):
    bots = int(state["bots"])
    rows = [
        [
            InlineKeyboardButton(_("btn_panel_edit_title_fa"), callback_data="pnl:tfa"),
            InlineKeyboardButton(_("btn_panel_edit_title_en"), callback_data="pnl:ten"),
        ],
        [
            InlineKeyboardButton("➖", callback_data="pnl:b:-1"),
            InlineKeyboardButton(_("cfg_bots_label", bots=bots), callback_data="pnl:noop"),
            InlineKeyboardButton("➕", callback_data="pnl:b:+1"),
        ],
        [InlineKeyboardButton(_("btn_pick_features"), callback_data="pnl:feat")],
        [InlineKeyboardButton(_("btn_panel_save"), callback_data="pnl:save")],
    ]
    if not is_new:
        rows.append([InlineKeyboardButton(_("btn_panel_delete"), callback_data="pnl:del")])
    rows.append([InlineKeyboardButton(_("btn_cancel"), callback_data="pnl:cancel")])
    return InlineKeyboardMarkup(rows)


def confirm(action_data, cancel_data, confirm_label=None):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(confirm_label or _("btn_confirm_yes"), callback_data=action_data)],
        [InlineKeyboardButton(_("btn_confirm_no"), callback_data=cancel_data)],
    ])




# ---------------------------------------------------------------------------
# ربات شخصی
# ---------------------------------------------------------------------------

def personal_bot(has_bot):
    rows = []
    if has_bot:
        rows.append([InlineKeyboardButton(_("btn_personal_change_token"), callback_data="pbot:set")])
        rows.append([InlineKeyboardButton(_("btn_personal_delete"), callback_data="pbot:del")])
    else:
        rows.append([InlineKeyboardButton(_("btn_personal_send_token"), callback_data="pbot:set")])
    rows.append([InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# ادمین
# ---------------------------------------------------------------------------

def admin_panel(pending_count, ticket_count):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_admin_pending", count=pending_count), callback_data="adm:pending")],
        [InlineKeyboardButton(_("btn_admin_tickets", count=ticket_count), callback_data="adm:tickets")],
        [
            InlineKeyboardButton(_("btn_admin_rate"), callback_data="adm:rate"),
            InlineKeyboardButton(_("btn_admin_card"), callback_data="adm:card"),
        ],
        [
            InlineKeyboardButton(_("btn_admin_bots"), callback_data="adm:bots"),
            InlineKeyboardButton(_("btn_admin_lines"), callback_data="adm:lines"),
        ],
        [InlineKeyboardButton(_("btn_admin_licenses"), callback_data="adm:lics:active:0")],
        [InlineKeyboardButton(_("btn_admin_crypto"), callback_data="adm:crypto")],
        [
            InlineKeyboardButton(_("btn_admin_catalog"), callback_data="adm:catalog"),
            InlineKeyboardButton(_("btn_admin_quote"), callback_data="adm:quote"),
        ],
        [InlineKeyboardButton(_("btn_admin_panels"), callback_data="pnl:list")],
        [InlineKeyboardButton(_("btn_admin_grant"), callback_data="adm:grant")],
        [InlineKeyboardButton(_("btn_admin_freebot_self"), callback_data="adm:freeself")],
        [InlineKeyboardButton(_("btn_admin_freebot"), callback_data="adm:freebot")],
        [
            InlineKeyboardButton(_("btn_admin_rental"), callback_data="adm:rental"),
            InlineKeyboardButton(_("btn_admin_rental_reset"), callback_data="adm:rrstart"),
        ],
        [InlineKeyboardButton(_("btn_admin_broadcast"), callback_data="adm:broadcast")],
        [InlineKeyboardButton(_("btn_admin_errors"), callback_data="adm:errors")],
        [InlineKeyboardButton(_("btn_admin_sweep"), callback_data="adm:sweep")],
        [InlineKeyboardButton(_("btn_admin_report"), callback_data="adm:report")],
        [InlineKeyboardButton(_("btn_admin_gc"), callback_data="adm:gc")],
        [InlineKeyboardButton(_("btn_admin_commands"), callback_data="adm:commands")],
        [InlineKeyboardButton(_("btn_back_menu"), callback_data="nav:menu")],
    ])


def admin_order_decision(order_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(_("btn_approve"), callback_data=f"adm:ok:{order_id}"),
            InlineKeyboardButton(_("btn_reject"), callback_data=f"adm:no:{order_id}"),
        ],
        [InlineKeyboardButton(_("btn_view_receipt"), callback_data=f"adm:receipt:{order_id}")],
        [InlineKeyboardButton(_("btn_reject_reason"), callback_data=f"adm:noreason:{order_id}")],
    ])


def admin_crypto(order_ids):
    """هر پرداختِ در انتظار یه دکمه داره که سفارشش رو باز می‌کنه (تأییدِ دستی)."""
    rows = [[InlineKeyboardButton(_("admin_crypto_order_button", order_id=order_id),
                                  callback_data=f"adm:show:{order_id}")] for order_id in order_ids]
    rows.append([InlineKeyboardButton(_("btn_admin_crypto_check"), callback_data="adm:cryptock")])
    rows.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def admin_pending_list(orders):
    rows = [[InlineKeyboardButton(
        _("admin_pending_button", order_id=row["id"], amount=pricing.format_usd(row["amount_usd"])),
        callback_data=f"adm:show:{row['id']}")] for row in orders]
    rows.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def admin_tickets(tickets):
    rows = [[InlineKeyboardButton(
        _("admin_ticket_button", ticket_id=row["id"], preview=(row["message"] or "")[:28]),
        callback_data=f"adm:ticket:{row['id']}")] for row in tickets]
    rows.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def admin_ticket_actions(ticket_id, user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_ticket_reply"), callback_data=f"adm:treply:{ticket_id}")],
        [InlineKeyboardButton(_("btn_ticket_close"), callback_data=f"adm:tclose:{ticket_id}")],
        [InlineKeyboardButton(_("btn_tickets"), callback_data="adm:tickets")],
    ])


def admin_rate():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_rate_refresh"), callback_data="adm:raterefresh")],
        [InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")],
    ])


def admin_gc_summary(counts, attention_count):
    """counts: {دسته: تعداد قابل‌حذف}."""
    rows = [[InlineKeyboardButton(_("btn_gc_review", name=_(f"gc_cat_{cat}"), count=n),
                                  callback_data=f"adm:gcc:{cat}:0")]
            for cat, n in counts.items()]
    if any(counts.values()):
        rows.append([InlineKeyboardButton(_("btn_gc_delete_all"), callback_data="adm:gcd:all")])
    if attention_count:
        rows.append([InlineKeyboardButton(_("btn_gc_attention", count=attention_count),
                                          callback_data="adm:gca")])
    rows.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


def admin_gc_category(cat, page, pages, deletable):
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("«", callback_data=f"adm:gcc:{cat}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"adm:gcc:{cat}:{page + 1}"))
    rows = [nav] if nav else []
    if deletable:
        rows.append([InlineKeyboardButton(_("btn_gc_delete_cat", count=deletable),
                                          callback_data=f"adm:gcd:{cat}")])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data="adm:gc")])
    return InlineKeyboardMarkup(rows)


def admin_gc_attention(candidates):
    rows = []
    for c in candidates:
        rows.append([
            InlineKeyboardButton(f"🤖 #{c.meta['instance_id']}", callback_data=f"inst:show:{c.meta['instance_id']}"),
            InlineKeyboardButton(f"🔑 #{c.meta['license_id']}", callback_data=f"lic:show:{c.meta['license_id']}"),
        ])
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data="adm:gc")])
    return InlineKeyboardMarkup(rows)


def admin_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")],
    ])


# ---------------------------------------------------------------------------
# لیست همه‌ی لایسنس‌ها -- ادمین (B8)
# ---------------------------------------------------------------------------

#: فیلترهای وضعیت که ادمین می‌تونه لیست رو باهاشون محدود کنه.
LICENSE_FILTERS = ("active", "expired", "suspended", "paused", "revoked", "all")
_LICENSE_FILTER_ICON = {"active": "🟢", "expired": "🔴", "suspended": "🟡",
                        "paused": "⏸", "revoked": "⚫️", "all": "📋"}
_LICENSE_STATUS_ICON = {"active": "🟢", "expired": "🔴", "suspended": "🟡",
                        "paused": "⏸", "revoked": "⚫️"}


def admin_license_list(rows, status, page, has_more):
    """
    لیستِ لایسنس‌ها + ردیفِ فیلتر + صفحه‌بندی -- همه با دکمه. هیچ‌جا لازم
    نیست ادمین کلید لایسنس رو تایپ کنه؛ زدنِ هر ردیف همون کارتِ همیشگی رو
    باز می‌کنه (با دکمه‌های تمدید/تعلیق/لغو/حذف).
    """
    rows_kb = []
    for row in rows:
        marker = _LICENSE_STATUS_ICON.get(row["status"], "⚪️")
        rows_kb.append([InlineKeyboardButton(
            f"{marker} {row['key']} — {row['user_id']}", callback_data=f"lic:show:{row['id']}")])

    filters = []
    for code in LICENSE_FILTERS:
        mark = "✅" if code == status else _LICENSE_FILTER_ICON[code]
        filters.append(InlineKeyboardButton(
            f"{mark} {i18n.t(f'license_filter_{code}')}", callback_data=f"adm:lics:{code}:0"))
    for i in range(0, len(filters), 3):
        rows_kb.append(filters[i:i + 3])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"adm:lics:{status}:{page - 1}"))
    if has_more:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"adm:lics:{status}:{page + 1}"))
    if nav:
        rows_kb.append(nav)

    rows_kb.append([InlineKeyboardButton(_("btn_admin_find_license"), callback_data="adm:licfind")])
    rows_kb.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows_kb)


def admin_license_search_results(rows):
    rows_kb = [[InlineKeyboardButton(
        f"{_LICENSE_STATUS_ICON.get(row['status'], '⚪️')} {row['key']}",
        callback_data=f"lic:show:{row['id']}")] for row in rows]
    rows_kb.append([InlineKeyboardButton(_("btn_admin_licenses"), callback_data="adm:lics:active:0")])
    rows_kb.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows_kb)


# ---------------------------------------------------------------------------
# لاین‌های صدا -- افزودن/حذف/بازسازی (B8)
# ---------------------------------------------------------------------------

def admin_lines_actions(lines):
    rows = [[InlineKeyboardButton(f"🗑 {line['slug']}", callback_data=f"adm:linedel:{line['slug']}")]
            for line in lines]
    rows.append([
        InlineKeyboardButton(_("btn_line_add"), callback_data="adm:lineadd"),
        InlineKeyboardButton(_("btn_line_ensure"), callback_data="adm:lineensure"),
    ])
    rows.append([InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# ریست لایسنسِ اجاره‌ای -- ادمین (B8)
# ---------------------------------------------------------------------------

def admin_rental_reset_days(key):
    rows = [[
        InlineKeyboardButton(f"{d} {i18n.t('unit_days')}", callback_data=f"adm:rreset:{key}:{d}")
        for d in days_group
    ] for days_group in ((7, 30), (90, 365))]
    rows.append([InlineKeyboardButton(_("btn_back"), callback_data="adm:panel")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# پیام همگانی (C1)
# ---------------------------------------------------------------------------

def broadcast_audiences(counts):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_broadcast_all", count=counts.get("all", 0)),
                              callback_data="adm:bcast:all")],
        [InlineKeyboardButton(_("btn_broadcast_active", count=counts.get("active", 0)),
                              callback_data="adm:bcast:active")],
        [InlineKeyboardButton(_("btn_broadcast_inactive", count=counts.get("inactive", 0)),
                              callback_data="adm:bcast:inactive")],
        [InlineKeyboardButton(_("btn_admin_panel"), callback_data="adm:panel")],
    ])


def broadcast_running():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_("btn_broadcast_cancel"), callback_data="adm:bcastcancel")],
    ])
