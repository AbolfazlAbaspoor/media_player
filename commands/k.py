"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'k'
ADMIN_ONLY = False
USAGE = 'k'

def run(ctx):
    bot = ctx["bot"]
    meta = command_helpers.current_shareable_meta(bot, ctx)
    if meta is None:
        return
    bot.t.user_message(ctx['uid'], meta['public_url'])
