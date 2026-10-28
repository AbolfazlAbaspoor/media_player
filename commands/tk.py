"""
TikTok direct URL playback.

Usage: tk <tiktok_url>

صفحه‌ی یه کاربر: اولین ویدیو فوری پخش می‌شه و بقیه با n لود می‌شن (قبلاً
رشد صف راه نمی‌افتاد و فقط ویدیوی اول پخش می‌شد).
"""

from core import command_helpers

NAME = "tk"
ADMIN_ONLY = False
USAGE = "tk <tiktok_url>"


def run(ctx):
    command_helpers.run_service_url_command(ctx, USAGE, "tiktok", "TikTok", "tiktok.com")
