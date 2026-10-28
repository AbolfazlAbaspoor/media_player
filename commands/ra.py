"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'ra'
REQUIRED_ROLE = "admin_server"
USAGE = 'ra <username>'

def run(ctx):
    bot = ctx["bot"]
    if not ctx['args']:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['ra']['usage']))
        return
    username = ctx['args'][0]
    if username not in bot.cfg.get('admins', []):
        bot.t.user_message(ctx['uid'], i18n.t('not_admin', username=username))
        return
    bot.cfg['admins'].remove(username)
    bot.save_config()
    bot.t.user_message(ctx['uid'], i18n.t('admin_removed_confirm', username=username))
