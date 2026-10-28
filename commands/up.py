"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import proxy_state

NAME = 'up'
REQUIRED_ROLE = "admin_server"
USAGE = 'up [true|false]'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        enabled = not bot.cfg['proxy'].get('enabled', False)
    else:
        if args[0].lower() not in ('true', 'false'):
            bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['up']['usage']))
            return
        enabled = args[0].lower() == 'true'
    if enabled and (not bot.cfg['proxy'].get('url')):
        bot.t.user_message(ctx['uid'], i18n.t('proxy_not_configured'))
        return
    bot.cfg['proxy']['enabled'] = enabled
    proxy_state.configure(enabled, bot.cfg['proxy'].get('url'))
    bot.apply_proxy_to_player()
    bot.save_config()
    state = i18n.t('state_enabled') if enabled else i18n.t('state_disabled')
    bot.t.user_message(ctx['uid'], i18n.t('proxy_toggled_confirm', state=state))
