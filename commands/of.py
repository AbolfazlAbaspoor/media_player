"""
جابه‌جایی حساب شخصیِ لاگین‌شده بین خصوصی (فقط همین سرور) و عمومی (همه‌ی
سرورها). دوباره زدن of حالت رو برمی‌گردونه (toggle).
"""

from core import command_helpers, i18n
from core import accounts

NAME = 'of'
ADMIN_ONLY = False
USAGE = 'of  (toggle your account between private-to-this-server and public)'


def run(ctx):
    bot = ctx["bot"]
    account = command_helpers.session_account(bot, ctx)
    if account is None:
        return
    account_username, path, data, is_public = account

    if is_public:
        accounts.set_private(bot, account_username, data)
        bot.t.user_message(ctx['uid'], i18n.t('sf_now_private', username=account_username))
        return

    result = accounts.set_public(bot, account_username, data)
    if result == "name_taken":
        bot.t.user_message(ctx['uid'], i18n.t('sf_name_taken', username=account_username))
    elif result == "already_public":
        bot.t.user_message(ctx['uid'], i18n.t('sf_already_public'))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('sf_now_public', username=account_username))
