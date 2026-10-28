"""
ویزاردِ دکمه‌ایِ لایسنسِ هدیه (🎁 صدورِ لایسنس) و لایسنسِ اجاره‌ای (🔑).

قبلاً هر دو یه گفت‌وگوی متنیِ پشت‌سرهم بودن: «چند ماه؟» -> عدد تایپ کن،
«چند ربات؟» -> عدد، «کدوم امکانات؟» -> کدهای انگلیسی رو با کاما تایپ کن.
یعنی ادمین باید کدِ دقیقِ هر امکان رو از حفظ می‌دونست و هر اشتباهِ تایپی
کلِ مرحله رو رد می‌کرد. حالا یه صفحه‌ی خلاصه با دکمه داریم -- مدت با
دکمه‌های روز/ماه، ربات با ➖/➕، امکانات با همون انتخاب‌گرِ toggleِ خرید
(keyboards.feature_picker) -- و فقط آیدیِ مشتری (که ذاتاً یه عدده) تایپ
می‌شه.

state (context.user_data["gift"]):
    mode      "grant" (لایسنسِ دیتابیسی برای یه کاربرِ تلگرام) یا
              "rental" (لایسنسِ اجاره‌ای روی Cloudflare KV)
    user_id   فقط برای grant
    days      مدت به روز
    bots      تعداد ربات
    features  لیستِ کدها (لیستِ خالی = فقط پایه)
"""

import asyncio
import secrets
import time

from core import logging_setup
from licensing import catalog
from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _is_admin, _send

DEFAULT_DAYS = 30
MIN_DAYS = 1
MAX_DAYS = 3650
MIN_BOTS = 1
# همون سقفِ فنیِ B7؛ برای هدیه‌ی ادمین قیمت مطرح نیست، پس سقفِ خریدِ
# مشتری (catalog.pricing()["max_bots"]) این‌جا اعمال نمی‌شه.
MAX_BOTS = 50


def _gift_state(context):
    return context.user_data.get("gift")


def gift_new_state(context, mode, user_id=None):
    """یه ویزاردِ تازه. اجاره‌ای پیش‌فرض همه‌ی امکانات رو داره (مثلِ «-» قدیم)."""
    features = list(catalog.features()) if mode == "rental" else []
    state = {"mode": mode, "user_id": user_id, "days": DEFAULT_DAYS,
             "bots": MIN_BOTS, "features": features}
    context.user_data["gift"] = state
    context.user_data.pop("awaiting", None)
    return state


def _gift_features_text(state):
    features = state["features"]
    if not features:
        return i18n.t("gift_features_base_only")
    if set(features) >= set(catalog.features()):
        return i18n.t("word_all")
    return ", ".join(sorted(features))


def _gift_duration_text(days):
    if days >= 30:
        return i18n.t("gift_duration_months", days=days, months=round(days / 30, 1))
    return i18n.t("gift_duration_days", days=days)


def gift_summary_text(state):
    title = i18n.t("gift_title_rental" if state["mode"] == "rental" else "gift_title_grant")
    target = ""
    if state["mode"] == "grant":
        target = i18n.t("gift_target_line", user_id=state["user_id"])
    return i18n.t("gift_summary", title=title, target=target,
                  duration=_gift_duration_text(int(state["days"])),
                  bots=int(state["bots"]), features=_gift_features_text(state))


async def gift_show_summary(update, context):
    state = _gift_state(context)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    await _send(update, gift_summary_text(state), kb.admin_gift(state))


async def _gift_show_features(update, context, note_key=None):
    state = _gift_state(context)
    text = i18n.t("gift_features_title")
    if note_key:
        text += "\n\n" + i18n.t(note_key)
    await _send(update, text,
                kb.feature_picker(state["features"], target="agr",
                                  show_price=False, allow_all=True))


async def gift_on_callback(update, context, action, arg=None):
    """دکمه‌های agr:* -- فقط ادمین (callbacks.py قبلش چک می‌کنه، این‌جا هم دوباره)."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    state = _gift_state(context)
    if state is None and action != "noop":
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return

    if action == "d" and arg:
        state["days"] = max(MIN_DAYS, min(MAX_DAYS, int(state["days"]) + int(arg)))
        await gift_show_summary(update, context)
    elif action == "b" and arg:
        state["bots"] = max(MIN_BOTS, min(MAX_BOTS, int(state["bots"]) + int(arg)))
        await gift_show_summary(update, context)
    elif action == "feat":
        await _gift_show_features(update, context)
    elif action == "tf" and arg:
        if arg in state["features"]:
            state["features"].remove(arg)
        elif arg in catalog.features():
            state["features"].append(arg)
        await _gift_show_features(update, context, "features_saved")
    elif action == "tb" and arg:
        members = catalog.expand_features([arg])
        if all(code in state["features"] for code in members):
            state["features"] = [c for c in state["features"] if c not in members]
        else:
            state["features"] += [c for c in members if c not in state["features"]]
        await _gift_show_features(update, context, "features_saved")
    elif action == "tall":
        state["features"] = list(catalog.features())
        await _gift_show_features(update, context, "features_saved")
    elif action == "tclear":
        state["features"] = []
        await _gift_show_features(update, context, "features_cleared")
    elif action == "done":
        await gift_show_summary(update, context)
    elif action == "issue":
        await gift_issue(update, context)
    elif action == "cancel":
        context.user_data.pop("gift", None)
        await _send(update, i18n.t("gift_cancelled"), kb.admin_back())


async def gift_issue(update, context):
    state = context.user_data.pop("gift", None)
    if state is None:
        await _send(update, i18n.t("gift_expired"), kb.admin_back())
        return
    if state["mode"] == "rental":
        await _gift_issue_rental(update, context, state)
    else:
        await _gift_issue_grant(update, context, state)


async def _gift_issue_grant(update, context, state):
    from licensing.telegram.sales import admin_commands

    days = int(state["days"])
    features = catalog.expand_features(state["features"]) if state["features"] else []
    license_row = await admin_commands.do_grant(
        context, update.effective_user.id, state["user_id"],
        months=max(1, -(-days // 30)), bots=int(state["bots"]),
        features=features, days=days)
    await _send(update, i18n.t("admin_license_granted_days", key=license_row["key"],
                               user_id=state["user_id"], days=days),
                kb.admin_back())


async def _gift_issue_rental(update, context, state):
    """کلید می‌سازه و روی Cloudflare می‌نویسه (همون کارِ قبلیِ admin_rental_features)."""
    from licensing import cloudflare

    days = int(state["days"])
    # همه‌ی امکانات انتخاب شده = None، یعنی «همه» -- حتی امکاناتی که بعداً
    # به کاتالوگ اضافه بشن (رفتارِ قبلیِ «-»).
    selected = list(state["features"])
    features = None if set(selected) >= set(catalog.features()) else selected

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # بدون I/O/0/1
    key = "TT-" + "-".join("".join(secrets.choice(alphabet) for _ in range(4))
                           for _ in range(3))
    expires_at = int(time.time()) + days * 86400

    await _send(update, i18n.t("setup_working"))
    try:
        await asyncio.to_thread(
            cloudflare.write_licence, key, expires_at, features, int(state["bots"]),
            f"issued by {update.effective_user.id}")
    except Exception as e:
        logging_setup.log_exception("writing rental licence to Cloudflare")
        await _send(update, i18n.t("admin_rental_failed",
                                   error=logging_setup.safe_error_text(e)),
                    kb.admin_back())
        return

    services = catalog.allowed_services(features) if features is not None else None
    commands = catalog.allowed_commands(features) if features is not None else None
    _db(context).log_event("rental_issued", user_id=update.effective_user.id,
                           detail={"key": key, "days": days, "features": features,
                                   "bots": int(state["bots"])})

    await _send(update,
                i18n.t("admin_rental_done",
                       key=key, days=days,
                       expires=time.strftime("%Y-%m-%d", time.localtime(expires_at)),
                       features=(i18n.t("word_all") if features is None else ", ".join(features)),
                       services=(i18n.t("word_all") if services is None else ", ".join(services)),
                       commands=(i18n.t("word_all") if commands is None else str(len(commands)))),
                kb.admin_rental_done(key))
