"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'cs'
ADMIN_ONLY = False
USAGE = 'cs'

def run(ctx):
    command_helpers.run_channel_content_command(ctx, 'get_channel_shorts', 'loading_channel_shorts')
