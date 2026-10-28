"""جستجوی کاربر توی اینستاگرام (با اکانتِ وصل‌شده). بعدش با iu/ist/ihl
صداشون رو پخش کن."""
from core import i18n, instagram_api, instagram_bot

NAME = 'iss'
ADMIN_ONLY = False
USAGE = 'iss <name>  (search Instagram users)'


def run(ctx):
    bot, uid, username = ctx['bot'], ctx['uid'], ctx['username']
    query = ' '.join(ctx.get('args') or []).strip()
    if not query:
        bot.t.user_message(uid, i18n.t('usage_generic', usage=USAGE))
        return
    client, error = instagram_bot.client_for(bot, username)
    if error:
        bot.t.user_message(uid, error)
        return
    try:
        users = instagram_api.search_users(client, query)
    except Exception as e:
        instagram_bot.reply_failure(bot, ctx, e)
        return
    if not users:
        bot.t.user_message(uid, i18n.t('ig_no_users', query=query))
        return
    lines = [f"@{name}" + (f" ({full})" if full else "") + (" [private]" if private else "")
             for name, full, private in users]
    bot.t.user_message(uid, i18n.t('ig_users_found', users=' | '.join(lines)))
