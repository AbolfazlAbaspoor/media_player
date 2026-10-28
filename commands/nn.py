"""Migrated from bot.py's built-in commands."""

from core import command_helpers
from core import i18n

NAME = ('nn', 'bb')
ADMIN_ONLY = False
USAGE = 'nn/bb  (switch to the next/previous channel playlist)'

def run(ctx):
    bot = ctx["bot"]
    found = command_helpers.channel_playlists(ctx)
    if found is None:
        return
    service, playlists = found
    if bot.channel_playlist_index is None:
        bot.t.user_message(ctx['uid'], i18n.t('load_playlist_first'))
        return
    current = bot.channel_playlist_index
    step = 1 if ctx['cmd'] == 'nn' else -1
    new_index = current + step
    if new_index < 1 or new_index > len(playlists):
        bot.t.user_message(ctx['uid'], i18n.t('no_more_playlists'))
        return
    bot.load_channel_playlist_by_index(ctx['uid'], ctx['nickname'], service, playlists, new_index)
