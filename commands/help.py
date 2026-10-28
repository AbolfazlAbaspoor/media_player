"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'help'
ADMIN_ONLY = False
USAGE = None

def run(ctx):
    bot = ctx["bot"]
    lines = []
    for name in sorted(bot.commands.keys()):
        info = bot.commands[name]
        if info['role'] != 'normal':
            continue
        lines.append(info['usage'] or name)
    bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), i18n.t('help_header') + '\n' + '\n'.join(lines))
