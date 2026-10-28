"""Migrated from bot.py's built-in commands."""

from core import i18n
from core import command_helpers
from core import manager

NAME = 'w'
ADMIN_ONLY = False
USAGE = 'w [name or number]  (no arg = cycle to next; only services with text search)'

def run(ctx):
    bot = ctx["bot"]
    # فقط سرویس‌هایی که سرچ متنی واقعی دارن (نه instagram/tiktok/soundcloud/
    # spotify که فقط لینک مستقیم قبول می‌کنن و دستور اختصاصی خودشون رو دارن).
    srv_list = manager.searchable_service_names(bot.services)
    if not srv_list:
        bot.t.user_message(ctx['uid'], command_helpers.no_services_message(bot))
        return
    args = ctx['args']
    if not args:
        bot.current_service_index = (bot.current_service_index + 1) % len(srv_list)
    else:
        query = ' '.join(args).lower()
        if query.isdigit() and 1 <= int(query) <= len(srv_list):
            bot.current_service_index = int(query) - 1
        else:
            match = next((i for i, name in enumerate(srv_list) if name.lower() == query), None)
            if match is None:
                bot.t.user_message(ctx['uid'], i18n.t('service_not_found', query=query, options=', '.join(srv_list)))
                return
            bot.current_service_index = match
    # اسم رو ذخیره می‌کنیم (نه فقط شماره): اگه دفعه‌ی بعد یه سرویس لود نشه،
    # شماره‌ها می‌لغزن ولی اسم همچنان درست به همون سرویس اشاره می‌کنه.
    last_state = bot.cfg.setdefault('last_state', {})
    last_state['service'] = srv_list[bot.current_service_index]
    last_state['service_index'] = bot.current_service_index
    bot.save_config()
    bot.channel_broadcast(i18n.t('service_changed', nickname=ctx['nickname'], service=srv_list[bot.current_service_index]))
