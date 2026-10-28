"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'back'
ADMIN_ONLY = False
USAGE = 'back'

def run(ctx):
    bot = ctx["bot"]
    with bot.roam_lock:
        active = bot.roam_state['active']
        requester_username = bot.roam_state['requester_username']
    if not active:
        bot.t.user_message(ctx['uid'], i18n.t('not_roaming'))
        return
    if ctx['username'] != requester_username and (not bot.is_admin(ctx['username'])):
        bot.t.user_message(ctx['uid'], i18n.t('back_denied'))
        return
    bot.return_home()
    bot.t.user_message(ctx['uid'], i18n.t('back_done'))
