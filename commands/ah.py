"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ah'
REQUIRED_ROLE = "admin_bot"
USAGE = 'ah'

def run(ctx):
    bot = ctx["bot"]
    lines = []
    for name in sorted(bot.commands.keys()):
        info = bot.commands[name]
        if info['role'] == 'normal':
            continue
        lines.append(f"[{info['role']}] {info['usage'] or name}")
    bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), i18n.t('admin_help_header') + '\n' + '\n'.join(lines))
