"""پخش دوباره‌ی یه آیتم از تاریخچه (شماره‌ها همون ترتیب hi هستن)."""

import threading

from core import command_helpers
from core import i18n
from core import history
from core import link_resolver
from core import logging_setup

NAME = 'hip'
ADMIN_ONLY = False
USAGE = 'hip <number>  (replay an item from hi)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args or not args[0].isdigit():
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['hip']['usage']))
        return

    entries = history.load(bot)
    idx = int(args[0]) - 1
    if not (0 <= idx < len(entries)):
        bot.t.user_message(ctx['uid'], i18n.t('invalid_playlist_number'))
        return

    entry = entries[idx]
    url = entry['url']

    def _play():
        command_helpers.acknowledge_request(bot, ctx, entry.get('title') or None)
        logging_setup.set_operation(f"replaying history item #{idx + 1} (requested by {ctx['username']})")
        try:
            if link_resolver.looks_like_direct_media(url):
                item = {"url": url, "title": entry.get('title')}
            else:
                item = link_resolver.resolve(url)
                if not item:
                    command_helpers.notify(bot, ctx, "no_stream_found")
                    return
                item.setdefault('title', entry.get('title'))
            bot.load_and_play(item, private=True)
            command_helpers.broadcast_now_playing(bot)
        except Exception as e:
            command_helpers.notify(bot, ctx, 'link_play_failed', error=logging_setup.safe_error_text(e))
        finally:
            logging_setup.set_operation('idle')

    threading.Thread(target=_play, daemon=True).start()
