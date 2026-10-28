"""Play a direct URL (any site link_resolver knows how to handle, with proxy fallback)."""
from core import command_helpers, i18n

NAME = 'u'
ADMIN_ONLY = False
USAGE = 'u <url>  (alias; just paste the link)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx.get('args', [])

    if not args:
        bot.t.user_message(ctx["uid"], i18n.t('usage_generic', usage=bot.commands['u']['usage']))
        return

    url = args[0]
    if not (url.startswith('http://') or url.startswith('https://')):
        bot.t.user_message(ctx["uid"], i18n.t('invalid_url'))
        return

    # فقط پوسته‌ی نازک دورِ منطقِ مشترک (core/command_helpers.py::run_link_command)
    # -- همون چیزی که پیستِ خامِ یه لینک (بدون دستور، توی bot.py) هم صدا
    # می‌زنه. `u` هنوز کار می‌کنه (مثلاً عادتِ قدیمی یا وقتی کاربر می‌خواد
    # صریحاً یه چیز رو «لینک» تلقی کنه نه عبارتِ سرچ)، ولی دیگه رفتارِ جدا
    # نداره -- یه اصلاح هرجا، هر دو راه رو می‌گیره.
    command_helpers.run_link_command(bot, ctx, url)
