"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ral'
REQUIRED_ROLE = "admin_bot"
USAGE = 'ral <trigger>'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ral']['usage']))
        return
    trigger = args[0].lower()
    if trigger not in bot.aliases:
        bot.t.user_message(ctx['uid'], i18n.t('alias_not_found', trigger=trigger))
        return
    del bot.aliases[trigger]
    bot.save_aliases()
    bot.channel_broadcast(i18n.t('alias_removed', nickname=ctx['nickname'], trigger=trigger))
