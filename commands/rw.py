"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'rw'
REQUIRED_ROLE = "admin_server"
USAGE = 'rw <first_seconds> <repeat_seconds>  (first=0 means retry immediately)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        rw_cfg = bot.cfg.get('reconnect_wait', {'first_seconds': 0, 'repeat_seconds': 10})
        bot.t.user_message(ctx['uid'], i18n.t(
            'reconnect_wait_status', first=rw_cfg.get('first_seconds', 0), repeat=rw_cfg.get('repeat_seconds', 10),
        ))
        return
    if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['rw']['usage']))
        return
    first_seconds = int(args[0])
    repeat_seconds = int(args[1])
    bot.cfg['reconnect_wait'] = {'first_seconds': first_seconds, 'repeat_seconds': repeat_seconds}
    bot.save_config()
    bot.t.user_message(ctx['uid'], i18n.t('reconnect_wait_set', first=first_seconds, repeat=repeat_seconds))
