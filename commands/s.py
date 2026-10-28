"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 's'
ADMIN_ONLY = False
USAGE = None

def run(ctx):
    bot = ctx["bot"]
    if bot.player.current_url is not None:
        bot.player.resume()
        bot.stop_player()
        bot.roam_set_deadline()
        bot.channel_broadcast(i18n.t('stopped_by', nickname=ctx['nickname']))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('nothing_playing'))
