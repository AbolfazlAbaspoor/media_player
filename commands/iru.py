"""Play Instagram reel/post by URL (via the Instagram service, with proxy fallback)."""
from core import command_helpers, i18n, logging_setup

NAME = 'iru'
ADMIN_ONLY = False
USAGE = 'iru <instagram_reel_url>  (play a direct Instagram link)'


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = ctx.get('args', [])

    if not args:
        bot.t.user_message(uid, i18n.t('usage_generic', usage=bot.commands['iru']['usage']))
        return

    url = args[0]
    if 'instagram.com' not in url.lower():
        bot.t.user_message(uid, i18n.t('invalid_instagram_url'))
        return

    service = bot.services.get('instagram')
    if not service:
        bot.t.user_message(uid, i18n.t('instagram_not_available'))
        return

    command_helpers.acknowledge_request(bot, ctx, url, 'instagram')
    logging_setup.set_operation(f"resolving Instagram link '{url}' (requested by {ctx['username']})")
    try:
        result = service.search(url)
        if not result:
            command_helpers.notify(bot, ctx, 'no_stream_found')
            return
        bot.load_and_play(result, private=True, service_name='instagram')
        command_helpers.broadcast_now_playing(bot)
    except Exception as e:
        # پیام نباید لینک رو تکرار کنه (لینکِ کاربر خصوصیه)؛ لاگ کامل جدا ذخیره می‌شه.
        command_helpers.notify(bot, ctx, 'link_play_failed', error=logging_setup.safe_error_text(e))
        logging_setup.log_debug(f"iru failed: {e}")
    finally:
        logging_setup.set_operation('idle')
