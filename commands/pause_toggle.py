"""Migrated from bot.py's built-in commands."""

from core import command_helpers

NAME = 'pause_toggle'
ADMIN_ONLY = False
USAGE = None

def run(ctx):
    # E6: تنها منطقِ پاز/ادامه‌ی پخش همینِ یه تابعِ مشترکه (استاتوس فوراً
    # عوض می‌شه، کانال فقط یه خط کوتاه می‌گیره).
    command_helpers.toggle_pause(ctx["bot"], ctx)
