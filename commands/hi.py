"""نمایش تاریخچه‌ی پخش این ربات (جدیدترین اول)."""

from core import i18n
from core import history

NAME = ('hi', 'history')
ADMIN_ONLY = False
USAGE = 'hi  (show recent playback history)'


def run(ctx):
    bot = ctx["bot"]
    entries = history.load(bot)
    if not entries:
        bot.t.user_message(ctx['uid'], i18n.t('no_history'))
        return
    lines = [i18n.t('history_header')]
    for i, entry in enumerate(entries, start=1):
        title = entry.get('title') or entry.get('url')
        lines.append(f"{i}. {title}")
    bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), '\n'.join(lines))
