"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ic'
REQUIRED_ROLE = "admin_server"
USAGE = 'ic [true|false] | ic <pause_seconds> <stop_seconds> [resume_rewind_seconds]'

_DEFAULTS = {'enabled': True, 'pause_after_seconds': 0, 'stop_after_seconds': 300, 'resume_rewind_seconds': 4}

def run(ctx):
    bot = ctx["bot"]
    bot.cfg.setdefault('idle_channel', dict(_DEFAULTS))
    for key, value in _DEFAULTS.items():
        bot.cfg['idle_channel'].setdefault(key, value)
    args = ctx['args']
    if not args or args[0].lower() in ('true', 'false'):
        enabled = not bot.cfg['idle_channel'].get('enabled', True) if not args else args[0].lower() == 'true'
        bot.cfg['idle_channel']['enabled'] = enabled
        bot.save_config()
        state = i18n.t('state_enabled') if enabled else i18n.t('state_disabled')
        bot.channel_broadcast(i18n.t('idle_channel_toggled', state=state, nickname=ctx['nickname']))
        return
    if len(args) >= 2 and args[0].isdigit() and args[1].isdigit():
        bot.cfg['idle_channel']['pause_after_seconds'] = int(args[0])
        bot.cfg['idle_channel']['stop_after_seconds'] = int(args[1])
        rewind = bot.cfg['idle_channel']['resume_rewind_seconds']
        if len(args) >= 3 and args[2].isdigit():
            rewind = int(args[2])
            bot.cfg['idle_channel']['resume_rewind_seconds'] = rewind
        bot.save_config()
        bot.t.user_message(ctx['uid'], i18n.t('idle_channel_times_set', pause=args[0], stop=args[1], rewind=rewind))
        return
    bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ic']['usage']))
