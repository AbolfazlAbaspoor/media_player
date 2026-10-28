"""
همه‌ی لایسنس‌های سرور -- نه فقط لایسنسِ خودِ ادمین (B8، الزامِ سوم).

/admin -> «🔑 لایسنس‌ها» یه لیستِ صفحه‌بندی‌شده و فیلترپذیر از *همه‌ی*
لایسنس‌های دیتابیس نشون می‌ده -- با وضعیت (فعال/منقضی/معلق/متوقف/لغوشده/
همه) و جست‌وجو با کلید یا آیدی تلگرامِ مشتری. هر ردیف همون کارتِ همیشگیِ
لایسنس رو باز می‌کنه (my_licenses.show_license)، که چون ادمینه همه‌ی
دکمه‌های مدیریتی رو داره: تمدیدِ سریع، تعلیق/رفعِ تعلیق، لغو، و حذفِ کامل
(my_licenses.admin_delete_license -- برگشت‌ناپذیر و جدا از revoke که فقط
تاریخچه رو نگه می‌داره).

منطقِ واقعیِ تمدید/تعلیق/رفعِ تعلیق/لغو توی admin_commands.py هست
(_do_extend، _do_license_status_action) -- هم دستورِ متنی (/extend،
/suspend...) هم این دکمه‌ها همونا رو صدا می‌زنن، تا دو نسخه از یه منطق
نباشه.
"""

from licensing import i18n
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales import admin_commands
from licensing.telegram.sales.common import _admin_ask, _db, _is_admin, _send
from licensing.telegram.sales.my_licenses import show_license

_PAGE_SIZE = 8


async def admin_licenses_list(update, context, status="active", page=0):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    db = _db(context)
    status = status if status in kb.LICENSE_FILTERS else "active"
    page = max(0, int(page))
    rows = db.licenses_by_status(status, limit=_PAGE_SIZE + 1, offset=page * _PAGE_SIZE)
    has_more = len(rows) > _PAGE_SIZE
    rows = rows[:_PAGE_SIZE]
    total = db.count_licenses(status)

    if not rows:
        await _send(update, i18n.t("admin_licenses_empty", status=i18n.t(f"license_filter_{status}")),
                    kb.admin_license_list([], status, page, False))
        return

    await _send(update,
                i18n.t("admin_licenses_title", status=i18n.t(f"license_filter_{status}"), count=total),
                kb.admin_license_list(rows, status, page, has_more))


async def admin_license_find_start(update, context):
    """دکمه‌ی «🔍 پیدا کردنِ لایسنس»: به‌جای تایپِ دستور، فقط یه سؤال."""
    await _admin_ask(update, context, _is_admin(update), _send, "license_find", "admin_license_find_ask")


async def admin_license_find_text(update, context, text):
    if not _is_admin(update):
        return
    context.user_data.pop("awaiting", None)
    db = _db(context)
    query = (text or "").strip()

    if query.upper().startswith("TT-"):
        row = db.get_license_by_key(query.upper())
        rows = [row] if row else []
    elif query.lstrip("-").isdigit():
        rows = db.licenses_by_user(int(query))
    else:
        rows = []

    if not rows:
        await _send(update, i18n.t("admin_license_find_none"), kb.admin_back())
        return
    if len(rows) == 1:
        await show_license(update, context, int(rows[0]["id"]))
        return
    await _send(update, i18n.t("admin_license_find_many", count=len(rows)),
                kb.admin_license_search_results(rows))


async def _admin_license(update, context, license_id):
    """
    چکِ ادمین + گرفتنِ ردیفِ لایسنس. اگه ادمین نبود یا لایسنس وجود نداشت
    خودش جواب می‌ده و None برمی‌گردونه (فراخوان فقط return می‌کنه).
    """
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return None
    license_row = _db(context).get_license(license_id)
    if license_row is None:
        await _send(update, i18n.t("license_not_found"), kb.admin_back())
    return license_row


async def admin_extend_license(update, context, license_id, months):
    license_row = await _admin_license(update, context, license_id)
    if license_row is None:
        return
    await admin_commands.do_extend(context, license_row, int(months))
    await show_license(update, context, license_id)


async def _license_action_button(update, context, license_id, action):
    """suspend/revoke: بعد از اجرای عمل، کارتِ لایسنس دوباره نشون داده می‌شه."""
    license_row = await _admin_license(update, context, license_id)
    if license_row is None:
        return
    await admin_commands.do_license_status_action(context, license_row, action)
    await show_license(update, context, license_id)


async def admin_suspend_button(update, context, license_id):
    await _license_action_button(update, context, license_id, "suspend")


async def admin_resume_button(update, context, license_id):
    license_row = await _admin_license(update, context, license_id)
    if license_row is None:
        return
    try:
        await admin_commands.do_license_status_action(context, license_row, "resume")
    except ValueError:
        await _send(update, i18n.t("admin_resume_expired", key=license_row["key"]))
        return
    await show_license(update, context, license_id)


async def admin_revoke_confirm(update, context, license_id):
    """لغو برگشت‌ناپذیره (دیتا و لاینِ صدا همون لحظه پاک می‌شن) -- تأیید لازمه."""
    license_row = await _admin_license(update, context, license_id)
    if license_row is None:
        return
    await _send(update,
                i18n.t("admin_revoke_confirm", key=T.esc(license_row["key"])),
                kb.confirm(f"adm:revokeok:{license_id}", f"lic:show:{license_id}",
                          i18n.t("btn_admin_revoke")))


async def admin_revoke_button(update, context, license_id):
    await _license_action_button(update, context, license_id, "revoke")


