"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import proxy_state

NAME = 'sp'
REQUIRED_ROLE = "admin_bot"
USAGE = 'sp'

def run(ctx):
    bot = ctx["bot"]
    cur = bot.cfg.get('proxy', {})
    state = i18n.t('state_enabled') if cur.get('enabled') else i18n.t('state_disabled')
    bot.t.user_message(ctx['uid'], i18n.t('proxy_status', state=state, url=proxy_state.mask(cur.get('url')) or 'not set'))
