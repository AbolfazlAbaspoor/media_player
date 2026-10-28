"""نمایش لیست فروریت (علاقه‌مندی‌های شخصی) حساب لاگین‌شده‌ی فعلی."""

from core import i18n
from core import command_helpers

NAME = 'sfl'
ADMIN_ONLY = False
USAGE = 'sfl  (list your personal favorites)'


def run(ctx):
    bot = ctx["bot"]
    found = command_helpers.session_favorites(bot, ctx)
    if found is None:
        return
    (account_username, path, data, is_public), favorites = found

    scope = i18n.t('sf_scope_public') if is_public else i18n.t('sf_scope_private')
    lines = [i18n.t('sf_favorites_header', username=account_username, scope=scope)]
    for i, entry in enumerate(favorites, start=1):
        title = entry.get('title') or entry.get('url')
        resume = entry.get('time') or 0
        marker = f" [{bot.format_time(resume)}]" if resume else ""
        lines.append(f"{i}. {title}{marker}")
    bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), '\n'.join(lines))
