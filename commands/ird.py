# commands/ird.py
"""فید ریلز چندنفره از یه هشتگ (نزدیک‌ترین چیزی که بدون اکانت واقعی/API
خصوصی اینستا می‌شه به فید 'کشف' ساخت -- الگوریتم شخصی‌سازی‌شده‌ی خودِ
اینستا در دسترس نیست، ولی این‌جوری حداقل محتوای چندنفره‌ست، نه یه پروفایل."""

from core import i18n
from core import command_helpers

NAME = 'ird'
ADMIN_ONLY = False
USAGE = 'ird <hashtag>  (multi-creator reels feed from that hashtag, audio only)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ird']['usage']))
        return

    service = bot.services.get('instagram')
    if not service:
        bot.t.user_message(ctx['uid'], i18n.t('instagram_not_available'))
        return
    if not hasattr(service, 'get_hashtag_feed'):
        bot.t.user_message(ctx['uid'], i18n.t('channel_not_supported', service='instagram'))
        return

    hashtag = args[0].lstrip('#')
    command_helpers.run_search_and_play_command(
        ctx, lambda: service.get_hashtag_feed(hashtag), 'instagram',
        announce_key='search_requested', announce_query=f'#{hashtag}',
        set_operation_desc=f"loading Instagram hashtag feed '#{hashtag}' (requested by {ctx['username']})",
    )
