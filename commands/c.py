"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'c'
ADMIN_ONLY = False
USAGE = 'c'

def run(ctx):
    command_helpers.run_channel_content_command(ctx, 'get_channel_all', 'loading_channel_all')
