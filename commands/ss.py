"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ss'
ADMIN_ONLY = False
USAGE = 'ss'

def run(ctx):
    bot = ctx["bot"]
    """برخلاف s (که فقط فایل فعلی رو استاپ می\u200cکنه)، ss کل صف پلی\u200cلیست رو هم خالی می\u200cکنه."""
    with bot.playback_lock:
        bot.stop_player()
        bot.player.clear_queue()
        bot.track_meta = []
    with bot.search_lock:
        bot.search_session['service'] = None
        bot.search_session['query'] = None
        bot.search_session['stubs'] = []
        bot.search_session['resolved_upto'] = 0
        bot.search_session['loading'] = False
    bot.channel_broadcast(i18n.t('playlist_reset', nickname=ctx['nickname']))
