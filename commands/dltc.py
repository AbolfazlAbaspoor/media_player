"""تایمر حذف فایل دانلودی از کانال (طبق scope فعلی: shared یا per_bot)، جدا از dlt.
    dltc              -> نمایش وضعیت فعلی
    dltc <minutes>    -> تنظیم تایمر
"""

from core import i18n
from core import dl_timer_helpers as dlh

NAME = 'dltc'
REQUIRED_ROLE = "admin_bot"
USAGE = 'dltc [minutes]  (channel-removal timer for downloaded files)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if not args:
        bot.t.user_message(ctx['uid'], dlh.status_text(bot))
        return

    if args[0].isdigit():
        dlh.apply_channel_timer(bot, ctx, int(args[0]))
        return

    bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['dltc']['usage']))
