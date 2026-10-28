"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'l'
REQUIRED_ROLE = "admin_server"
USAGE = 'l [name]  (no name = list languages)'

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        lines = [i18n.t('language_list_header')]
        for idx, (code, name) in enumerate(i18n.available_languages(), start=1):
            lines.append(f'{idx}. {name} ({code})')
        bot.t.user_message(ctx['uid'], '\n'.join(lines))
        return
    query = ' '.join(args)
    if i18n.set_language(query):
        bot.cfg['language'] = i18n.current_language()[0]
        bot.save_config()
        code, name = i18n.current_language()
        bot.t.user_message(ctx['uid'], i18n.t('language_switched', name=name))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('language_not_found', query=query))
