"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'sd'
ADMIN_ONLY = False
USAGE = 'sd <seconds>'

def run(ctx):
    bot = ctx["bot"]
    """چند ثانیه\u200cی پیش\u200cفرض که + و - بدون عدد جابه\u200cجا می\u200cکنن."""
    args = ctx['args']
    if not args or not args[0].isdigit():
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['sd']['usage']))
        return
    bot.cfg['seek_default_seconds'] = int(args[0])
    bot.save_config()
    bot.channel_broadcast(i18n.t('seek_default_set', nickname=ctx['nickname'], seconds=args[0]))
