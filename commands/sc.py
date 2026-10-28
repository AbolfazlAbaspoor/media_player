"""
SoundCloud track/playlist playback from URL.

Usage: sc <soundcloud_url>

آلبوم/پلی‌لیست (set) یا صفحه‌ی هنرمند: اولین ترک فوری پخش می‌شه و بقیه با n
لود می‌شن. قبلاً این دستور رشد صف رو راه نمی‌انداخت، پس از یه set فقط ترک
اول پخش می‌شد و n به «آخر صف» می‌خورد.
"""

from core import command_helpers

NAME = "sc"
ADMIN_ONLY = False
USAGE = "sc <soundcloud_url>"


def run(ctx):
    command_helpers.run_service_url_command(ctx, USAGE, "soundcloud", "SoundCloud", "soundcloud.com")
