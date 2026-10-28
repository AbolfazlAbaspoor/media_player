# commands/ir.py
"""لود ریلزهای یه پروفایل اینستاگرام به‌عنوان یه صف پخش مشترک (فقط صدا)."""

from core import i18n
from core import command_helpers

NAME = 'ir'
ADMIN_ONLY = False
USAGE = 'ir <username>  (loads that profile\'s reels feed, audio only)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ir']['usage']))
        return

    username = args[0].lstrip('@').strip('/')
    if not username:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ir']['usage']))
        return

    service = bot.services.get('instagram')
    if not service:
        bot.t.user_message(ctx['uid'], i18n.t('instagram_not_available'))
        return

    # نکته: yt-dlp از /reels/ (تب مخصوص ریلز) پشتیبانی نمی‌کنه
    # (yt_dlp.utils.UnsupportedError) -- فقط خودِ پروفایل قابل‌استخراجه،
    # که شامل همه‌ی پست‌ها می‌شه (نه فقط ریلز، چون اینستاگرام فیلتر
    # تب‌به‌تب رو بدون API خصوصی در اختیار نمی‌ذاره).
    url = f"https://www.instagram.com/{username}/"
    command_helpers.run_search_and_play_command(
        ctx, lambda: service.search(url), 'instagram',
        announce_key='search_requested', announce_query=url,
        set_operation_desc=f"loading Instagram reels for '{username}' (requested by {ctx['username']})",
    )
