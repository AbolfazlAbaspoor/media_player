"""Migrated from bot.py's built-in commands."""

from core import command_helpers
from core import i18n

NAME = ('cp', 'cpl')
ADMIN_ONLY = False
USAGE = 'cpl [number]  (cp = always the first playlist)'

def run(ctx):
    bot = ctx["bot"]
    found = command_helpers.channel_playlists(ctx)
    if found is None:
        return
    service, playlists = found
    args = ctx['args']
    if ctx['cmd'] == 'cp':
        index = 1
    elif not args:
        lines = [f"{i + 1}. {pl['title']}" for i, pl in enumerate(playlists)]
        bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), i18n.t('channel_playlists_header') + '\n' + '\n'.join(lines))
        return
    elif args[0].isdigit():
        index = int(args[0])
    else:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['cpl']['usage']))
        return
    bot.load_channel_playlist_by_index(ctx['uid'], ctx['nickname'], service, playlists, index)
