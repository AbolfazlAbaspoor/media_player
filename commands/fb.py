"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import logging_setup
import os
import time

NAME = 'fb'
ADMIN_ONLY = False
USAGE = 'fb <suggestion text>'

def run(ctx):
    bot = ctx["bot"]
    """پیشنهاد کاربر رو توی data/feedback.log ذخیره می\u200cکنه."""
    if not ctx['args']:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['fb']['usage']))
        return
    text = ' '.join(ctx['args'])
    feedback_dir = os.path.join(bot.server_dir, 'feedback')
    os.makedirs(feedback_dir, exist_ok=True)
    entry = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {ctx['username']} ({ctx['nickname']}): {text}\n"
    try:
        with open(os.path.join(feedback_dir, 'suggestions.log'), 'a', encoding='utf-8') as f:
            f.write(entry)
        bot.t.user_message(ctx['uid'], i18n.t('feedback_saved'))
    except Exception as e:
        bot.t.user_message(ctx['uid'], i18n.t('generic_error', error=logging_setup.safe_error_text(e)))
