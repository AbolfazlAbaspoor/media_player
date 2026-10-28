"""
آرشیو پخش‌های زنده‌ی کانالِ فعلی.

    lp

خیلی از کانال‌ها لایوهاشون رو ضبط و نگه می‌دارن. اون‌ها توی تبِ جداگانه‌ی
«پخش‌های زنده» می‌شینن و توی تبِ ویدیوها دیده نمی‌شن -- این دستور همون
تب رو لود می‌کنه.
"""

from core import command_helpers

NAME = "lp"
ADMIN_ONLY = False
USAGE = "lp  (load the current channel's past live streams)"


def run(ctx):
    command_helpers.run_channel_content_command(
        ctx, "get_channel_streams",
        loading_key="channel_streams_loading",
        empty_key="channel_no_streams",
    )
