"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'cm'
REQUIRED_ROLE = "admin_server"
USAGE = 'cm [true|false]'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    was_enabled = bot.channel_messages_enabled
    if not args:
        new_value = not bot.channel_messages_enabled
    elif args[0].lower() in ('true', 'false'):
        new_value = args[0].lower() == 'true'
    else:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['cm']['usage']))
        return
    bot.channel_messages_enabled = new_value
    bot.cfg['channel_messages_enabled'] = new_value
    bot.save_config()
    state = i18n.t('state_enabled') if new_value else i18n.t('state_disabled')
    if new_value or was_enabled:
        bot.t.channel_message(i18n.t('channel_messages_toggled', state=state, nickname=ctx['nickname']))
    bot.t.user_message(ctx['uid'], i18n.t('channel_messages_toggled_confirm', state=state))
