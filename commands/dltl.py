"""تایمر پاک‌سازی پوشه‌ی downloads محلی (همیشه مخصوص همین ربات)، جدا از dlt.
    dltl              -> نمایش وضعیت فعلی
    dltl <minutes>    -> تنظیم تایمر
"""

from core import i18n
from core import dl_timer_helpers as dlh

NAME = 'dltl'
REQUIRED_ROLE = "admin_bot"
USAGE = 'dltl [minutes]  (local downloads-folder cleanup timer)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    if not args:
        bot.t.user_message(ctx['uid'], dlh.status_text(bot))
        return

    if args[0].isdigit():
        dlh.apply_local_timer(bot, ctx, int(args[0]))
        return

    bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['dltl']['usage']))
