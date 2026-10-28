"""
لایسنس‌های بدون پرداخت که ادمین می‌سازه: «ربات نامحدود» و لایسنس اجاره‌ای.
"""

import asyncio
import time

from core import logging_setup
from licensing import catalog
from licensing import config
from licensing import i18n
from licensing import licenses
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import HTML, _admin_ask, _db, _is_admin, _send
from licensing.telegram.sales.wizard import _setup_prompt


# ۱۰۰ سال یعنی عملاً بی‌انقضا، ولی از همون مسیر همیشگیِ لایسنس رد می‌شه.
_UNLIMITED_MONTHS = 12 * 100
_UNLIMITED_BOTS = 99
_UNLIMITED_USERS = 999

# جواب‌هایی که یعنی «برای خودم»
_SELF_MARKERS = {"-", "me", "self", "من", "خودم"}


def _grant_unlimited(db, owner_id, granted_by):
    """
    لایسنسِ بدون پرداخت، با همه‌ی امکانات و سهمیه‌ی عملاً نامحدود.

    چرا لایسنس صادر می‌شه، وقتی خواسته «ربات بدون لایسنس» بود: خودِ ربات
    بدون license.json معتبر بالا نمی‌آد و این عمدیه
    (core/license_gate.py). یه سوییچِ «لایسنس لازم نیست» دقیقاً همون راه
    فراری می‌شد که اونجا نوشته نباید وجود داشته باشه -- هر کس دیگه‌ای هم
    می‌تونست پیداش کنه. پس به‌جای سوراخ‌کردن قفل، یه لایسنس واقعیِ ۱۰۰
    ساله با همه‌ی امکانات صادر می‌شه: از بیرون همون «بدون محدودیت»، بدون
    ضعیف‌کردن قفل.
    """
    db.upsert_user(owner_id)
    features = list(catalog.features())
    order = db.create_order(user_id=owner_id, months=_UNLIMITED_MONTHS,
                            users=_UNLIMITED_USERS, bots=_UNLIMITED_BOTS,
                            features=features, amount_usd=0.0,
                            status="approved", kind="new")
    db.update_order(int(order["id"]), decided_by=granted_by,
                    decided_at=int(time.time()), admin_note="admin unlimited bot")
    license_row = licenses.create_from_order(db, db.get_order(int(order["id"])))
    db.update_license(int(license_row["id"]), notes="admin unlimited")
    return db.get_license(int(license_row["id"]))


async def admin_rental_start(update, context):
    """
    صدور لایسنس اجاره‌ای، کامل از داخل تلگرام.

    قبلاً دو مرحله‌ی دستی بود: `manage.py rental` و بعد کپی/پیست یه
    دستور `wrangler kv put` توی ترمینال. یعنی برای هر مشتری باید پای
    کامپیوتر می‌رفتی. این‌جا ربات خودش روی Cloudflare می‌نویسه.
    """
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return

    from licensing import cloudflare
    if not cloudflare.available():
        await _send(update,
                    i18n.t("admin_rental_not_configured",
                           missing=", ".join(cloudflare.missing_settings()),
                           config_file=config.CONFIG_FILE),
                    kb.admin_back())
        return

    context.user_data.pop("setup", None)
    # مدت/ربات/امکانات همه با دکمه (admin_gift.py) -- دیگه عدد و کدِ امکانات
    # تایپ نمی‌شه.
    from licensing.telegram.sales import admin_gift
    admin_gift.gift_new_state(context, "rental")
    await admin_gift.gift_show_summary(update, context)


async def admin_rental_revoke(update, context, key):
    """لایسنس اجاره‌ای رو از راه دور می‌خوابونه."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return

    from licensing import cloudflare
    await _send(update, i18n.t("setup_working"))
    try:
        ok = await asyncio.to_thread(cloudflare.revoke_licence, key, False)
    except Exception as e:
        logging_setup.log_exception("revoking rental licence")
        await _send(update, i18n.t("admin_rental_failed",
                                   error=logging_setup.safe_error_text(e)),
                    kb.admin_back())
        return

    _db(context).log_event("rental_revoked", user_id=update.effective_user.id,
                           detail={"key": key})
    await _send(update,
                i18n.t("admin_rental_revoked" if ok else "admin_rental_not_found", key=key),
                kb.admin_back())


async def admin_rental_machines(update, context, key):
    """چند دستگاه این لایسنس رو چک کردن — نشانه‌ی اشتراک‌گذاری."""
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return

    from licensing import cloudflare
    try:
        seen = await asyncio.to_thread(cloudflare.machines_seen, key)
    except Exception as e:
        await _send(update, i18n.t("admin_rental_failed",
                                   error=logging_setup.safe_error_text(e)),
                    kb.admin_back())
        return

    if not seen:
        await _send(update, i18n.t("admin_rental_no_machines", key=key), kb.admin_back())
        return

    lines = []
    for fingerprint, info in sorted(seen.items(), key=lambda kv: kv[1].get("last", 0), reverse=True):
        last = info.get("last")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last / 1000)) if last else "—"
        lines.append(i18n.t("admin_rental_machine_line", fingerprint=fingerprint[:12],
                            count=info.get("count", 0), when=when))

    await _send(update,
                i18n.t("admin_rental_machines", key=key, count=len(seen),
                       lines="\n".join(lines)),
                kb.admin_back())


async def admin_freebot_start(update, context):
    await _admin_ask(update, context, _is_admin(update), _send, "freebot_owner", "admin_freebot_ask_owner", clear=('setup',))


async def admin_freebot_owner(update, context, text):
    """
    آیدی مالک رو می‌گیره، لایسنس نامحدود صادر می‌کنه، و بعد می‌ره توی
    *همون* ویزارد همیشگی که مشخصات تیم‌تاک (هاست، پورت، یوزر/پسِ ربات،
    کانال، اپراتورها) رو می‌پرسه. یعنی همه‌ی کار توی یه گفت‌وگو تموم
    می‌شه و هیچ منطق جداگانه‌ای برای ساخت ربات دوباره نوشته نشده.
    """
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    context.user_data.pop("awaiting", None)

    raw = (text or "").strip()
    if raw.lower() in _SELF_MARKERS:
        owner_id = update.effective_user.id
    else:
        try:
            owner_id = int(raw.lstrip("@").strip())
        except ValueError:
            await _send(update, i18n.t("admin_freebot_bad_id"), kb.admin_back())
            return

    await _freebot_issue(update, context, owner_id)


async def admin_freebot_self(update, context):
    """
    👑 یه‌ضرب: لایسنسِ نامحدود (همه‌ی امکانات، بدونِ محدودیتِ ماه/ربات)
    برای *خودِ* ادمینی که دکمه رو زده -- بدونِ پرسیدنِ آیدی. همون مسیرِ
    «ربات نامحدود»، فقط گیرنده همیشه خودشه.
    """
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    context.user_data.pop("awaiting", None)
    await _freebot_issue(update, context, update.effective_user.id)


async def _freebot_issue(update, context, owner_id):
    db = _db(context)
    try:
        license_row = _grant_unlimited(db, owner_id, update.effective_user.id)
    except Exception:
        logging_setup.log_exception("granting unlimited licence")
        await _send(update, T.UNEXPECTED_ERROR, kb.admin_back())
        return

    db.log_event("license_granted_unlimited", user_id=owner_id,
                 license_id=int(license_row["id"]),
                 detail={"by": update.effective_user.id})

    context.user_data["setup"] = {"license_id": int(license_row["id"]), "step": 0}
    context.user_data["awaiting"] = "setup"
    await _send(update, i18n.t("admin_freebot_created", key=license_row["key"],
                               user_id=owner_id, bots=license_row["max_bots"],
                               date=T.fmt_date(license_row["expires_at"])))
    await update.effective_chat.send_message(_setup_prompt(0), parse_mode=HTML)


# ---------------------------------------------------------------------------
# صدورِ دستیِ لایسنس -- ویزاردِ دکمه‌ای (B8، معادلِ /grant)
# ---------------------------------------------------------------------------
# همون منطقِ /grant (admin_commands.do_grant)، فقط این‌جا به‌جای یه دستورِ
# متنی با چهار آرگومان: آیدیِ مشتری تایپ می‌شه، بقیه با دکمه (admin_gift.py).

async def admin_grant_start(update, context):
    await _admin_ask(update, context, _is_admin(update), _send, "grant_user_id", "admin_grant_ask_user_id", clear=('grant', 'gift'))


async def admin_grant_user_id(update, context, text):
    raw = (text or "").strip()
    try:
        user_id = int(raw.lstrip("@"))
    except ValueError:
        await _send(update, i18n.t("admin_freebot_bad_id"))
        return
    # بقیه (مدت با روز/ماه، ربات، امکانات) با دکمه -- admin_gift.py.
    from licensing.telegram.sales import admin_gift
    admin_gift.gift_new_state(context, "grant", user_id=user_id)
    await admin_gift.gift_show_summary(update, context)


# ---------------------------------------------------------------------------
# ریست لایسنسِ اجاره‌ای -- ویزاردِ دکمه‌ای (B8، معادلِ manage.py rental-reset)
# ---------------------------------------------------------------------------

async def admin_rental_reset_start(update, context):
    await _admin_ask(update, context, _is_admin(update), _send, "rental_reset_key", "admin_rental_reset_ask_key")


async def admin_rental_reset_key_text(update, context, text):
    context.user_data.pop("awaiting", None)
    key = (text or "").strip().upper()
    await _send(update, i18n.t("admin_rental_reset_pick_days", key=T.esc(key)),
                kb.admin_rental_reset_days(key))


async def admin_rental_reset_attempt(update, context, key, days, force=False):
    """
    منطقِ واقعی توی licensing.cloudflare.reset_rental هست (همون که
    manage.py rental-reset صدا می‌زنه) -- اینجا فقط UI. چکِ «پروتکتد» هم
    عیناً مثلِ CLI با licensing.config.is_protected_licence انجام می‌شه.
    """
    from licensing import cloudflare
    from licensing import config as config_module

    key = (key or "").strip().upper()
    days = int(days)

    if config_module.is_protected_licence(key):
        await _send(update, i18n.t("admin_rental_reset_protected", key=T.esc(key)), kb.admin_back())
        return
    if not cloudflare.available():
        await _send(update,
                    i18n.t("admin_rental_not_configured",
                           missing=", ".join(cloudflare.missing_settings()),
                           config_file=config.CONFIG_FILE),
                    kb.admin_back())
        return

    try:
        result = await asyncio.to_thread(cloudflare.reset_rental, key, days, force)
    except cloudflare.RentalResetRefused:
        # بایندشده و force نداده -- به‌جای پرچمِ --force، یه دکمه‌ی تأیید.
        await _send(update, i18n.t("admin_rental_reset_bound", key=T.esc(key)),
                    kb.confirm(f"adm:rresetok:{key}:{days}", "adm:panel",
                              i18n.t("btn_rental_reset_force")))
        return
    except cloudflare.CloudflareError as e:
        if str(e) == "not_found":
            await _send(update, i18n.t("admin_rental_not_found", key=T.esc(key)), kb.admin_back())
        else:
            logging_setup.log_exception("resetting rental licence")
            await _send(update, T.UNEXPECTED_ERROR, kb.admin_back())
        return

    _db(context).log_event("rental_reset", user_id=update.effective_user.id,
                           detail={"key": key, "days": days, "was_bound": result["was_bound"]})
    await _send(update,
                i18n.t("admin_rental_reset_done", key=T.esc(key), days=days,
                       expires=time.strftime("%Y-%m-%d", time.localtime(result["expires_at"])),
                       bound_note=(i18n.t("admin_rental_reset_was_bound")
                                   if result["was_bound"] else "")),
                kb.admin_rental_done(key))


async def admin_rental_reset_days_button(update, context, key, days):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await admin_rental_reset_attempt(update, context, key, days, force=False)


async def admin_rental_reset_force_button(update, context, key, days):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await admin_rental_reset_attempt(update, context, key, days, force=True)
