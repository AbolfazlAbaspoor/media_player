"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import proxy_state

NAME = 'pp'
REQUIRED_ROLE = "admin_server"
USAGE = 'pp'

def run(ctx):
    bot = ctx["bot"]
    proxy_url = bot.cfg.get('proxy', {}).get('url')
    if not proxy_url:
        bot.t.user_message(ctx['uid'], i18n.t('proxy_not_configured'))
        return
    enabled = bot.cfg.get('proxy', {}).get('enabled', False)
    state = i18n.t('state_enabled') if enabled else i18n.t('state_disabled')
    lines = [i18n.t('ping_proxy_header', url=proxy_state.mask(proxy_url)), i18n.t('ping_proxy_state', state=state)]
    general = proxy_state.test_proxy('https://www.google.com/generate_204', proxy_url)
    if general['ok']:
        lines.append(i18n.t('ping_general_ok', ms=f"{general['ms']:.0f}"))
    else:
        lines.append(i18n.t('ping_general_failed', error=general['error']))
    yt = proxy_state.test_proxy('https://www.youtube.com/generate_204', proxy_url)
    if yt['ok']:
        lines.append(i18n.t('ping_yt_ok', ms=f"{yt['ms']:.0f}"))
    else:
        lines.append(i18n.t('ping_yt_failed', error=yt['error']))
    bot.t.user_message(ctx['uid'], '\n'.join(lines))
