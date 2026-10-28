"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ns'
ADMIN_ONLY = False
USAGE = 'ns'

def run(ctx):
    bot = ctx["bot"]
    bot.normalize_enabled = not bot.normalize_enabled
    bot.cfg['audio_normalize'] = bot.normalize_enabled
    bot.apply_normalize()
    bot.save_config()
    state = i18n.t('state_enabled') if bot.normalize_enabled else i18n.t('state_disabled')
    bot.channel_broadcast(i18n.t('normalize_toggled', state=state, nickname=ctx['nickname']))
