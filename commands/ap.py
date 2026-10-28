"""
پخش از آپارات، با لینک یا با جستجوی فارسی.

    ap <لینک آپارات>
    ap <عبارت فارسی>

برخلاف sc/tk/spt که فقط لینک قبول می‌کنن، این یکی جستجو هم می‌گیره --
آپارات از داخل ایران بدون پروکسی در دسترسه، پس وقتی یوتیوب و ساندکلاد
پشت فیلترن این همچنان کار می‌کنه.
"""

from core import command_helpers
from core import i18n

NAME = "ap"
ADMIN_ONLY = False
USAGE = "ap <aparat link or search text>"


def run(ctx):
    bot = ctx["bot"]
    args = ctx["args"]
    if not args:
        bot.t.user_message(ctx["uid"], i18n.t("usage_generic", usage=USAGE))
        return

    service = bot.services.get("aparat")
    if not service:
        bot.t.user_message(ctx["uid"], i18n.t("service_not_loaded", service="Aparat"))
        return

    query = " ".join(args)
    command_helpers.run_search_and_play_command(
        ctx, lambda: service.search(query), "aparat",
        announce_key="search_requested", announce_query=query,
        set_operation_desc=f"searching '{query}' on aparat")
