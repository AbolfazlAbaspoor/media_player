"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ln'
ADMIN_ONLY = False
USAGE = 'ln'

def run(ctx):
    bot = ctx["bot"]
    code, name = i18n.current_language()
    bot.t.user_message(ctx['uid'], i18n.t('current_language', name=name, code=code))
