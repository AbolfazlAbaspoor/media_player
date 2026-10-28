"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 't'
ADMIN_ONLY = False
USAGE = None

def run(ctx):
    bot = ctx["bot"]
    if bot.player.current_url is None:
        bot.t.user_message(ctx['uid'], i18n.t('nothing_playing'))
        return
    duration = bot.player.duration_seconds
    pos = bot.player.position_seconds
    remaining = None
    if duration is not None and pos is not None:
        remaining = max(0, duration - pos)
    bot.t.user_message(ctx['uid'], i18n.t('time_info', position=bot.format_time(pos), duration=bot.format_time(duration), remaining=bot.format_time(remaining)))
