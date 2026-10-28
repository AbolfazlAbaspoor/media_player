"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'cv'
ADMIN_ONLY = False
USAGE = 'cv'

def run(ctx):
    command_helpers.run_channel_content_command(ctx, 'get_channel_videos', 'loading_channel_videos', capability_check=False)
