"""Migrated from bot.py's built-in commands."""

from core import command_helpers
from core import i18n
from core import logging_setup

NAME = 'p'
ADMIN_ONLY = False
USAGE = 'p [search query or url]  (no args = replay last track)'

def run(ctx):
    bot = ctx["bot"]
    if not ctx['args']:
        if not bot.last_started:
            bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['p']['usage']))
            return
        try:
            bot.load_and_play(dict(bot.last_started), private=bot.last_started['private'])
            command_helpers.broadcast_now_playing(bot)
        except Exception as e:
            command_helpers.notify(bot, ctx, 'link_play_failed', error=logging_setup.safe_error_text(e))
        return
    query = ' '.join(ctx['args'])
    active = command_helpers.active_search_service(bot, ctx)
    if active is None:
        return
    active_name, service = active
    is_url = query.startswith('http://') or query.startswith('https://')
    # پیامِ اول: به کل کانال (E12) -- تأییدِ خصوصی قبلاً باعث می‌شد بقیه‌ی
    # کانال هیچی نبینن تا خودِ پخش شروع بشه.
    command_helpers.acknowledge_request(bot, ctx, query, active_name)
    try:
        logging_setup.set_operation(f"searching '{query}' on {active_name} (requested by {ctx['username']})")
        result = service.search(query)
        first = result[0] if isinstance(result, list) else result
        if isinstance(first, dict) and first.get('channel_url'):
            bot.last_channel_url = first['channel_url']
        # لینکی که کاربر داده خصوصیه؛ نتیجه‌ی جستجو عمومی.
        count = bot.load_and_play(result, private=is_url, service_name=active_name)
    except Exception as e:
        command_helpers.notify(bot, ctx, 'service_error', service=active_name, error=logging_setup.safe_error_text(e))
        return
    finally:
        logging_setup.set_operation('idle')

    # همون منطقی که هر دستور دیگه‌ای هم ازش استفاده می‌کنه (یه نسخه، نه
    # دوتا). m دیگه اینجا اثری نداره (E5): جستجو همیشه رشد می‌کنه.
    count = command_helpers.start_growth_session(
        bot, service, active_name, query, first, is_url, count)

    command_helpers.broadcast_now_playing(bot)
