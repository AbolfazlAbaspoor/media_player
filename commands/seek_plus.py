"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = ('+', '-')
ADMIN_ONLY = False
USAGE = '+/- [seconds]  (no number = default step from config)'

def run(ctx):
    bot = ctx["bot"]
    if bot.player.current_url is None:
        bot.t.user_message(ctx['uid'], i18n.t('nothing_playing'))
        return
    args = ctx['args']
    default_step = bot.cfg.get('seek_default_seconds', 15)
    step = int(args[0]) if args and args[0].isdigit() else default_step
    val = step if ctx['cmd'] == '+' else -step
    bot.player.seek_relative(val)
    bot.channel_broadcast(i18n.t('seeked', nickname=ctx['nickname'], seconds=val))
