"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'aa'
REQUIRED_ROLE = "admin_server"
USAGE = 'aa <username>'

def run(ctx):
    command_helpers.add_admin_command(ctx, 'aa', 'admins', 'already_admin', 'admin_added_confirm')
