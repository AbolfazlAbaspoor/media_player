"""
پاکسازیِ پسماند (ادمین): اسکن -> مرور دسته‌ها -> تأیید -> اجرا -> یک گزارش.

منطقش توی licensing/gc.py هست (manage.py gc هم همون رو صدا می‌زنه)؛ اینجا
فقط نمایش و دکمه‌هاست. فقط ادمین و فقط ربات فروش -- ربات شخصیِ مشتری این
رو ندارد. هر هندلر خودش هم ادمین بودن رو چک می‌کنه، نه فقط روتر.
"""

import asyncio

from licensing import gc
from licensing import i18n
from licensing.provisioning import DATA_DIR
from licensing.telegram import keyboards as kb
from licensing.telegram import texts as T
from licensing.telegram.sales.common import _db, _is_admin, _send, _supervisor
from core import logging_setup

PAGE_SIZE = 8
CONFIRM_LIST = 15


async def _scan(context):
    return await asyncio.to_thread(gc.scan, _db(context), DATA_DIR)


def _valid(cat):
    return cat == "all" or cat in gc.CATEGORIES


async def gc_start(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    await _send(update, i18n.t("gc_scanning"))
    try:
        report = await _scan(context)
    except Exception:
        logging_setup.log_exception("gc scan")
        await _send(update, T.UNEXPECTED_ERROR, kb.admin_back())
        return
    lines = [i18n.t("gc_title"), ""]
    counts = {}
    for cat in gc.CATEGORIES:
        items = report.items.get(cat, [])
        if not items:
            continue
        size = sum(c.size for c in items)
        note = "" if all(c.deletable for c in items) else i18n.t("gc_report_only")
        lines.append(i18n.t("gc_summary_line", name=i18n.t(f"gc_cat_{cat}"), count=len(items),
                            size=gc.fmt_size(size)) + note)
        counts[cat] = sum(1 for c in items if c.deletable)
    if report.attention:
        lines.append(i18n.t("gc_attention_line", count=len(report.attention)))
    if not counts and not report.attention:
        lines.append(i18n.t("gc_nothing"))
    elif counts:
        lines += ["", i18n.t("gc_total", size=gc.fmt_size(report.total_size()))]
    await _send(update, "\n".join(lines), kb.admin_gc_summary(counts, len(report.attention)))


async def gc_category(update, context, cat, page=0):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    if cat not in gc.CATEGORIES:
        return
    report = await _scan(context)
    items = report.items.get(cat, [])
    pages = max(1, -(-len(items) // PAGE_SIZE))
    page = min(max(int(page), 0), pages - 1)
    lines = [i18n.t("gc_category_title", name=i18n.t(f"gc_cat_{cat}"), count=len(items),
                    page=page + 1, pages=pages), ""]
    for c in items[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        lines.append(i18n.t("gc_item", label=T.esc(c.label), size=gc.fmt_size(c.size),
                            reason=i18n.t(f"gc_reason_{c.reason}")))
    if not items:
        lines.append(i18n.t("gc_nothing"))
    deletable = sum(1 for c in items if c.deletable)
    await _send(update, "\n".join(lines), kb.admin_gc_category(cat, page, pages, deletable))


async def gc_confirm(update, context, cat):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    if not _valid(cat):
        return
    report = await _scan(context)
    picked = report.deletable(None if cat == "all" else cat)
    if not picked:
        await _send(update, i18n.t("gc_nothing"), kb.admin_gc_summary({}, len(report.attention)))
        return
    lines = [i18n.t("gc_confirm_title", count=len(picked),
                    size=gc.fmt_size(sum(c.size for c in picked))), ""]
    for c in picked[:CONFIRM_LIST]:
        lines.append(i18n.t("gc_confirm_item", category=i18n.t(f"gc_cat_{c.category}"),
                            label=T.esc(c.label)))
    if len(picked) > CONFIRM_LIST:
        lines.append(i18n.t("gc_confirm_more", count=len(picked) - CONFIRM_LIST))
    lines += ["", i18n.t("gc_irreversible")]
    await _send(update, "\n".join(lines),
                kb.confirm(f"adm:gcok:{cat}", "adm:gc", i18n.t("btn_delete_yes")))


async def gc_apply(update, context, cat):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    if not _valid(cat):
        return
    await _send(update, i18n.t("setup_working"))
    db = _db(context)
    try:
        report = await _scan(context)
        selection = [c.id for c in report.deletable(None if cat == "all" else cat)]
        result = await asyncio.to_thread(
            gc.apply, db, DATA_DIR, selection, None, None, _supervisor(context))
    except Exception:
        logging_setup.log_exception("gc apply")
        await _send(update, T.UNEXPECTED_ERROR, kb.admin_back())
        return
    lines = [i18n.t("gc_done_title", size=gc.fmt_size(result["freed"])), ""]
    for name in gc.CATEGORIES:
        if result["deleted"].get(name):
            lines.append(i18n.t("gc_done_line", name=i18n.t(f"gc_cat_{name}"),
                                count=result["deleted"][name]))
    if not result["deleted"]:
        lines.append(i18n.t("gc_nothing"))
    if result["errors"]:
        lines.append(i18n.t("gc_done_errors", count=result["errors"]))
    await _send(update, "\n".join(lines), kb.admin_back())


async def gc_attention(update, context):
    if not _is_admin(update):
        await _send(update, T.ADMIN_ONLY)
        return
    report = await _scan(context)
    lines = [i18n.t("gc_attention_title"), ""]
    for c in report.attention:
        lines.append(i18n.t("gc_attention_item", label=T.esc(c.label)))
    if not report.attention:
        lines.append(i18n.t("gc_nothing"))
    await _send(update, "\n".join(lines), kb.admin_gc_attention(report.attention))
