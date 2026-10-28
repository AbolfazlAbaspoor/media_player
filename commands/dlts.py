"""انتخاب scope تایمر حذف کانال (shared یا مخصوص همین ربات)، جدا از dlt.
    dlts              -> نمایش وضعیت فعلی
    dlts shared       -> استفاده از تایمر مشترک سرور
    dlts mine <min>   -> استفاده از تایمر مخصوص همین ربات
"""

from core import i18n
from core import dl_timer_helpers as dlh

NAME = 'dlts'
REQUIRED_ROLE = "admin_bot"
USAGE = 'dlts [shared | mine <minutes>]  (channel-removal timer scope)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if not args:
        bot.t.user_message(ctx['uid'], dlh.status_text(bot))
        return

    sub = args[0].lower()

    if sub == 'shared':
        dlh.apply_scope_shared(bot, ctx)
        return

    if sub == 'mine':
        minutes = int(args[1]) if len(args) >= 2 and args[1].isdigit() else None
        dlh.apply_scope_mine(bot, ctx, minutes)
        return

    bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['dlts']['usage']))
