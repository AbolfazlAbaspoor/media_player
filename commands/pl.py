from core import i18n
from core import command_helpers
from core import logging_setup

NAME = 'pl'
ADMIN_ONLY = False
USAGE = 'pl  (load the playlist/mix that the current track belongs to)'


def _extract_video_id(url):
    if not url:
        return None
    if "v=" in url:
        return url.split("v=")[1].split("&")[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    return None


def run(ctx):
    bot = ctx["bot"]
    meta = command_helpers.current_track_meta(bot, ctx)
    if meta is None:
        return

    public_url = meta.get('public_url')
    vid = _extract_video_id(public_url)
    if not vid:
        bot.t.user_message(ctx['uid'], i18n.t('pl_not_youtube'))
        return

    active = command_helpers.active_search_service(bot, ctx)
    if active is None:
        return
    active_name, service = active

    mix_url = f"https://www.youtube.com/watch?v={vid}&list=RD{vid}"
    logging_setup.set_operation(f"loading mix playlist for '{vid}' (requested by {ctx['username']})")
    try:
        result = service.search(mix_url)
        count = bot.load_and_play(result, private=False, service_name=active_name)

        # همون تابعِ مشترکی که هر دستور دیگه‌ای هم برای رشد صف ازش استفاده
        # می‌کنه (نه یه کپیِ جدا) -- مسیرِ رشدش همون مسیرِ پلی‌لیسته
        # (is_url=True رد می‌شه تا شاخه‌ی سرچِ متنی امتحان نشه).
        first = result[0] if isinstance(result, list) else result
        count = command_helpers.start_growth_session(
            bot, service, active_name, mix_url, first, True, count)

        command_helpers.broadcast_now_playing(bot)
    except Exception as e:
        command_helpers.notify(bot, ctx, 'service_error', service=active_name, error=logging_setup.safe_error_text(e))
    finally:
        logging_setup.set_operation('idle')
