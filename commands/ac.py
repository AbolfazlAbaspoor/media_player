"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ac'
REQUIRED_ROLE = "admin_server"
USAGE = 'ac [all|admins_outside|none]'

def run(ctx):
    bot = ctx["bot"]
    bot.cfg.setdefault('access', {'mode': 'all'})
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('access_mode_status', mode=bot.cfg['access'].get('mode', 'all')))
        return
    mode = args[0].lower()
    if mode not in ('all', 'admins_outside', 'none'):
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ac']['usage']))
        return
    bot.cfg['access']['mode'] = mode
    bot.save_config()
    bot.channel_broadcast(i18n.t('access_mode_changed', nickname=ctx['nickname'], mode=mode))
