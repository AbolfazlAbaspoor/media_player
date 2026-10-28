# commands/dlt.py
"""تنظیم تایمرهای dl (دستور همه‌کاره -- برای هر بخش جدا هم dltc/dltl/dlts هست):
    dlt                          -> نمایش وضعیت فعلی
    dlt channel <minutes>        -> تایمر حذف از کانال (طبق scope فعلی)
    dlt local <minutes>          -> تایمر حذف از پوشه‌ی downloads (همیشه مخصوص همین ربات)
    dlt scope shared             -> این ربات از تایمر مشترک سرور استفاده کنه
    dlt scope mine <minutes>     -> این ربات از تایمر مخصوص خودش استفاده کنه
"""

from core import i18n
from core import dl_timer_helpers as dlh

NAME = 'dlt'
REQUIRED_ROLE = "admin_bot"
USAGE = 'dlt [channel <min> | local <min> | scope shared | scope mine <min>]  (or use dltc/dltl/dlts separately)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if not args:
        bot.t.user_message(ctx['uid'], dlh.status_text(bot))
        return

    sub = args[0].lower()

    if sub == 'channel' and len(args) >= 2 and args[1].isdigit():
        dlh.apply_channel_timer(bot, ctx, int(args[1]))
        return

    if sub == 'local' and len(args) >= 2 and args[1].isdigit():
        dlh.apply_local_timer(bot, ctx, int(args[1]))
        return

    if sub == 'scope' and len(args) >= 2 and args[1].lower() == 'shared':
        dlh.apply_scope_shared(bot, ctx)
        return

    if sub == 'scope' and len(args) >= 2 and args[1].lower() == 'mine':
        minutes = int(args[2]) if len(args) >= 3 and args[2].isdigit() else None
        dlh.apply_scope_mine(bot, ctx, minutes)
        return

    bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['dlt']['usage']))
