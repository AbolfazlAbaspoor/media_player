"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'v'
ADMIN_ONLY = False
USAGE = 'v <0-100>'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    vol = int(args[0]) if args and args[0].isdigit() else 50
    vol = max(0, min(100, vol))
    bot.player.volume = vol
    bot.cfg.setdefault('last_state', {})['volume'] = vol
    bot.save_config()
    bot.channel_broadcast(i18n.t('volume_set', nickname=ctx['nickname'], volume=vol))
