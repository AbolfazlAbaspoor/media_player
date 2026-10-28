"""اضافه‌کردن ادمینِ مخصوصِ همین یه ربات (سطح admin_bot -- پایین‌تر از admin_server)."""

from core import command_helpers

NAME = 'aab'
REQUIRED_ROLE = "admin_server"
USAGE = 'aab <username>'

def run(ctx):
    command_helpers.add_admin_command(ctx, 'aab', 'bot_admins', 'already_bot_admin', 'bot_admin_added_confirm')
