"""Migrated from bot.py's built-in commands."""

from core import i18n
import time

NAME = 'come'
ADMIN_ONLY = False
USAGE = 'come'

def run(ctx):
    bot = ctx["bot"]
    if not bot.cfg.get('roaming', {}).get('enabled', True):
        bot.t.user_message(ctx['uid'], i18n.t('roaming_disabled'))
        return
    try:
        others_here = bot.t.get_channel_users(exclude_self=True)
    except Exception:
        others_here = []
    if others_here and bot.player.current_url is not None and not bot.player.is_paused:
        bot.t.user_message(ctx['uid'], i18n.t('come_busy_playing'))
        return
    with bot.roam_lock:
        already_active = bot.roam_state['active']
        current_requester = bot.roam_state['requester_username']
    if already_active and ctx['username'] != current_requester and (not bot.is_admin(ctx['username'])):
        bot.t.user_message(ctx['uid'], i18n.t('come_already_busy'))
        return
    try:
        target_channel = bot.t.get_user_info(ctx['uid'])['channel_id']
    except Exception:
        bot.t.user_message(ctx['uid'], i18n.t('come_join_failed'))
        return
    with bot.roam_lock:
        if not bot.roam_state['active']:
            try:
                my_channel = bot.t.get_user_info()['channel_id']
            except Exception:
                my_channel = bot.cfg.get('channel', {}).get('id', 1)
            bot.roam_state['origin_channel_id'] = my_channel
            bot.roam_state['origin_channel_password'] = bot.cfg.get('channel', {}).get('password', '')
        bot.roam_state['active'] = True
        bot.roam_state['requester_uid'] = ctx['uid']
        bot.roam_state['requester_username'] = ctx['username']
        bot.roam_state['deadline'] = time.time() + bot.roam_timeout_seconds
    if not bot.do_join(target_channel, ''):
        with bot.roam_lock:
            bot.roam_state['active'] = False
        bot.t.user_message(ctx['uid'], i18n.t('come_join_failed'))
        return
    try:
        bot.t.set_name(f"{bot.cfg['server']['nickname']} for {ctx['username']}")
    except Exception:
        from core import logging_setup
        logging_setup.log_debug("setting per-user nickname on 'come' failed")
    bot.t.user_message(ctx['uid'], i18n.t('come_arrived', minutes=bot.roam_timeout_seconds // 60))
