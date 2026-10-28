"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'al'
REQUIRED_ROLE = "admin_bot"
USAGE = 'al <trigger> <command>  (no args = list)'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        if not bot.aliases:
            bot.t.user_message(ctx['uid'], i18n.t('no_aliases'))
            return
        lines = [f'{trig} -> {cmd}' for trig, cmd in bot.aliases.items()]
        bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), i18n.t('alias_list_header') + '\n' + '\n'.join(lines))
        return
    if len(args) < 2:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['al']['usage']))
        return
    trigger = args[0].lower()
    target_cmd = args[1].lower()
    if target_cmd not in bot.commands:
        bot.t.user_message(ctx['uid'], i18n.t('alias_unknown_target', command=target_cmd))
        return
    bot.aliases[trigger] = target_cmd
    bot.save_aliases()
    bot.channel_broadcast(i18n.t('alias_added', nickname=ctx['nickname'], trigger=trigger, command=target_cmd))
