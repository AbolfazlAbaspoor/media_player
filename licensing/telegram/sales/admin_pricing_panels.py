"""
مدیریتِ دکمه‌ایِ پنل‌های آماده‌ی فروش (📋 «پنل ۱»..«پنل ۴» که مشتری موقعِ
خرید می‌بینه): دیدن، ویرایش، افزودن، حذف -- بدونِ ویرایشِ دستیِ
data/licensing/catalog.json.

state (context.user_data["panel_edit"]):
    code       کدِ پنلِ موجود، یا None برای پنلِ تازه
    title_fa   عنوانِ فارسی
    title_en   عنوانِ انگلیسی
    bots       تعدادِ ربات
    features   لیستِ کدها

ماهِ پنل همیشه ۱ است (تصمیمِ صاحبِ کسب‌وکار: هیچ خرید/تمدیدی بیشتر از یه
ماه نباشه -- catalog.PRICING["duration_multipliers"]) پس اصلاً پرسیده
نمی‌شه.
"""

from licensing import catalog
from licensing import i18n
from licensing import pricing
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _is_admin, _send

PANEL_MONTHS = 1


def _pnladm_state(context):
    return context.user_data.get("panel_edit")


def _pnladm_title(panel):
    return panel.get("title_fa" if i18n.get_language() == "fa" else "title_en") or panel.get("code")


def _pnladm_next_code(existing_codes):
    n = 1
    while f"p{n}" in existing_codes:
        n += 1
    return f"p{n}"


def _pnladm_features_text(state):
    features = state["features"]
    if not features:
        return i18n.t("gift_features_base_only")
    if set(features) >= set(catalog.features()):
        return i18n.t("word_all")
    return ", ".join(sorted(features))


def _pnladm_price_text(panel):
    quote = pricing.quote(panel["months"], panel["bots"], panel.get("features", []))
    price = pricing.format_usd(quote["total_usd"])
    if quote["total_irr"]:
        price += f" / {pricing.format_irr(quote['total_irr'])}"
    return price


async def panels_admin_list(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    rows = [(p["code"], _pnladm_title(p), _pnladm_price_text(p)) for p in catalog.panels()]
    await _send(update, i18n.t("panels_admin_list_title"), kb.admin_panels_list(rows))


def _pnladm_editor_summary(state, is_new):
    title = i18n.t("panels_admin_new_title" if is_new else "panels_admin_edit_title",
                   title=(state["title_fa"] or "—"))
    return i18n.t("panels_admin_summary", title=title,
                  title_fa=state["title_fa"] or "—", title_en=state["title_en"] or "—",
                  bots=int(state["bots"]), features=_pnladm_features_text(state))


async def _pnladm_show_editor(update, context):
    state = _pnladm_state(context)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    await _send(update, _pnladm_editor_summary(state, state["code"] is None),
                kb.admin_panel_editor(state, state["code"] is None))


async def panels_admin_show(update, context, code):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    panel = next((p for p in catalog.panels() if p["code"] == code), None)
    if panel is None:
        await panels_admin_list(update, context)
        return
    context.user_data["panel_edit"] = {
        "code": panel["code"], "title_fa": panel.get("title_fa", ""),
        "title_en": panel.get("title_en", ""), "bots": int(panel.get("bots", 1)),
        "features": list(panel.get("features") or []),
    }
    await _pnladm_show_editor(update, context)


async def panels_admin_new(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    context.user_data["panel_edit"] = {
        "code": None, "title_fa": "", "title_en": "", "bots": 1, "features": [],
    }
    await _pnladm_show_editor(update, context)


async def _pnladm_show_features(update, context, note_key=None):
    state = _pnladm_state(context)
    text = i18n.t("gift_features_title")
    if note_key:
        text += "\n\n" + i18n.t(note_key)
    await _send(update, text,
                kb.feature_picker(state["features"], target="pnl",
                                  show_price=False, allow_all=True))


async def panels_admin_on_callback(update, context, action, arg=None):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return

    if action == "list":
        context.user_data.pop("panel_edit", None)
        await panels_admin_list(update, context)
        return
    if action == "new":
        await panels_admin_new(update, context)
        return
    if action == "show" and arg:
        await panels_admin_show(update, context, arg)
        return

    state = _pnladm_state(context)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return

    if action == "b" and arg:
        state["bots"] = max(1, min(50, int(state["bots"]) + int(arg)))
        await _pnladm_show_editor(update, context)
    elif action == "feat":
        await _pnladm_show_features(update, context)
    elif action == "tf" and arg:
        if arg in state["features"]:
            state["features"].remove(arg)
        elif arg in catalog.features():
            state["features"].append(arg)
        await _pnladm_show_features(update, context, "features_saved")
    elif action == "tb" and arg:
        members = catalog.expand_features([arg])
        if all(code in state["features"] for code in members):
            state["features"] = [c for c in state["features"] if c not in members]
        else:
            state["features"] += [c for c in members if c not in state["features"]]
        await _pnladm_show_features(update, context, "features_saved")
    elif action == "tall":
        state["features"] = list(catalog.features())
        await _pnladm_show_features(update, context, "features_saved")
    elif action == "tclear":
        state["features"] = []
        await _pnladm_show_features(update, context, "features_cleared")
    elif action == "done":
        await _pnladm_show_editor(update, context)
    elif action == "tfa":
        context.user_data["awaiting"] = "panel_title_fa"
        await _send(update, i18n.t("panels_admin_ask_title_fa"))
    elif action == "ten":
        context.user_data["awaiting"] = "panel_title_en"
        await _send(update, i18n.t("panels_admin_ask_title_en"))
    elif action == "save":
        await panels_admin_save(update, context)
    elif action == "del":
        await _send(update, i18n.t("panels_admin_confirm_delete", title=state["title_fa"] or state["code"]),
                    kb.confirm(f"pnl:delok:{state['code']}", f"pnl:show:{state['code']}"))
    elif action == "delok" and arg:
        await panels_admin_delete(update, context, arg)
    elif action == "cancel":
        context.user_data.pop("panel_edit", None)
        await panels_admin_list(update, context)


async def panels_admin_title_fa_text(update, context, text):
    state = _pnladm_state(context)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    state["title_fa"] = (text or "").strip()[:80]
    context.user_data.pop("awaiting", None)
    await _pnladm_show_editor(update, context)


async def panels_admin_title_en_text(update, context, text):
    state = _pnladm_state(context)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    state["title_en"] = (text or "").strip()[:80]
    context.user_data.pop("awaiting", None)
    await _pnladm_show_editor(update, context)


async def panels_admin_save(update, context):
    state = context.user_data.get("panel_edit")
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    if not state["title_fa"].strip() or not state["title_en"].strip():
        await _send(update, i18n.t("panels_admin_need_titles"), kb.admin_panel_editor(state, state["code"] is None))
        return

    panels_list_ = catalog.panels()
    code = state["code"]
    if code is None:
        code = _pnladm_next_code([p["code"] for p in panels_list_])

    entry = {
        "code": code, "title_fa": state["title_fa"], "title_en": state["title_en"],
        "months": PANEL_MONTHS, "bots": int(state["bots"]), "features": list(state["features"]),
    }
    updated = [p for p in panels_list_ if p["code"] != code]
    updated.append(entry)
    updated.sort(key=lambda p: p["code"])
    catalog.save_panels(updated)

    context.user_data.pop("panel_edit", None)
    await _send(update, i18n.t("panels_admin_saved", title=entry["title_fa"]), kb.admin_back())


async def panels_admin_delete(update, context, code):
    updated = [p for p in catalog.panels() if p["code"] != code]
    catalog.save_panels(updated)
    context.user_data.pop("panel_edit", None)
    await _send(update, i18n.t("panels_admin_deleted", code=code), kb.admin_back())
