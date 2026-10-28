"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import logging_setup
import os
import time
import sys

NAME = 'rs'
REQUIRED_ROLE = "admin_server"
USAGE = 'rs [all|services|languages|aliases|...]'

def run(ctx):
    bot = ctx["bot"]
    mode = ctx['args'][0].lower() if ctx['args'] else 'all'
    if mode == 'all':
        bot.channel_broadcast(i18n.t('restarting', nickname=ctx['nickname']))
        bot.full_shutdown()
        time.sleep(1)
        os.execv(sys.executable, ['python'] + sys.argv)
        return
    reloader = bot.reloaders.get(mode)
    if not reloader:
        bot.t.user_message(ctx['uid'], i18n.t('unknown_reload_target', options=', '.join(sorted(bot.reloaders.keys()))))
        return
    try:
        reloader()
        bot.channel_broadcast(i18n.t('target_reloaded', target=mode, nickname=ctx['nickname']))
    except Exception as e:
        bot.t.user_message(ctx['uid'], i18n.t('reload_error', target=mode, error=logging_setup.safe_error_text(e)))
