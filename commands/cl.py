"""
پخش زنده‌ی کانالِ آهنگ/ویدیوی فعلی.

    cl

اگه کانالِ چیزی که الان پخش می‌شه *همین لحظه* لایو داره، لایو رو پخش
می‌کنه. اگه نداره، همین رو می‌گه و چیزی عوض نمی‌شه.
"""

from core import command_helpers
from core import i18n

NAME = "cl"
ADMIN_ONLY = False
USAGE = "cl  (play the current channel's live stream, if it is live now)"


def run(ctx):
    bot = ctx["bot"]
    name, service = bot.require_channel_service(ctx)
    if not service:
        return
    if not hasattr(service, "get_channel_live"):
        bot.t.user_message(ctx["uid"], i18n.t("channel_not_supported", service=name))
        return

    # «زنده نیست» یه خطا نیست، یه جوابه -- پس پیام اختصاصی خودش رو داره،
    # نه «چیزی پیدا نشد»ِ عمومی.
    command_helpers.run_channel_content_command(
        ctx, "get_channel_live",
        loading_key="channel_live_checking",
        empty_key="channel_not_live",
    )
