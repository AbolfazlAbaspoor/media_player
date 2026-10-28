"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import logging_setup

NAME = 'cn'
REQUIRED_ROLE = "admin_bot"
USAGE = 'cn <name>'

def run(ctx):
    bot = ctx["bot"]
    if not ctx['args']:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['cn']['usage']))
        return
    new_name = ' '.join(ctx['args'])
    try:
        bot.t.set_name(new_name)
    except Exception as e:
        bot.t.user_message(ctx['uid'], i18n.t('generic_error', error=logging_setup.safe_error_text(e)))
        return
    bot.cfg['server']['nickname'] = new_name
    bot.save_config()
    bot.channel_broadcast(i18n.t('name_changed', nickname=ctx['nickname'], name=new_name))
