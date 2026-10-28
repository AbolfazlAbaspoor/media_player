"""
اسپاتیفای: پخش لینک ترک/آلبوم/پلی‌لیست، یا فقط دیدن لیست ترک‌هاش.

    spt <لینک اسپاتیفای>        پخش (آلبوم و پلی‌لیست: اولی فوری، بقیه با n)
    spt info <لینک اسپاتیفای>   اسم ترک‌ها و خواننده‌ها، بدون پخش

صدا از یوتیوب پیدا می‌شه، چون صدای خودِ اسپاتیفای DRM داره -- توضیح کامل
توی core/services/spotify.py. قبلاً این دستور فقط متادیتا نشون می‌داد؛ اون
حالت با info مونده.
"""

from core import command_helpers
from core import i18n
from core import logging_setup

NAME = "spt"
ADMIN_ONLY = False
USAGE = "spt [info] <spotify_url>"

_INFO_WORDS = ("info", "i", "list")


def _show_tracks(bot, ctx, service, url):
    uid = ctx["uid"]
    logging_setup.set_operation("reading a Spotify link")
    try:
        name, tracks = service.describe(url)
    except Exception as e:
        bot.t.user_message(uid, i18n.t("service_error", service="Spotify",
                                       error=logging_setup.safe_error_text(e)))
        return
    finally:
        logging_setup.set_operation("idle")

    if not tracks:
        command_helpers.notify(bot, ctx, "nothing_found")
        return

    from core.services.spotify import display_name
    lines = [name] if name and len(tracks) > 1 else []
    for number, track in enumerate(tracks, 1):
        line = f"{number}. {display_name(track)}"
        if track.get("duration"):
            line += f" ({bot.format_time(track['duration'])})"
        lines.append(line)
    bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))


def run(ctx):
    bot = ctx["bot"]
    uid = ctx["uid"]
    args = list(ctx["args"] or [])

    show_info = bool(args) and args[0].lower() in _INFO_WORDS
    if show_info:
        args = args[1:]
    if not args:
        bot.t.user_message(uid, i18n.t("usage_generic", usage=USAGE))
        return

    service = bot.services.get("spotify")
    if not service:
        bot.t.user_message(uid, i18n.t("service_not_loaded", service="Spotify"))
        return
    # URI اپ (spotify:track:...) و لینک کوتاهِ اپ موبایل هم قبوله؛ از اینجا به
    # بعد همه‌جا شکلِ استانداردِ https استفاده می‌شه، وگرنه مسیرِ رشد صف اون
    # رو «جستجوی متنی» حساب می‌کرد و بقیه‌ی پلی‌لیست هیچ‌وقت لود نمی‌شد.
    link = service.canonical_link(args[0])
    if not link:
        bot.t.user_message(uid, i18n.t("invalid_service_url", service="Spotify"))
        return

    if show_info:
        _show_tracks(bot, ctx, service, link)
        return

    # همون مسیرِ ir/ap: تأیید برای درخواست‌کننده، پخش، راه‌انداختن رشد صف
    # برای آلبوم/پلی‌لیست، و یه پیام «در حال پخش» برای کانال.
    command_helpers.run_search_and_play_command(
        ctx, lambda: service.search(link), "spotify",
        announce_key="request_ack_link", announce_query=link,
        set_operation_desc=f"resolving a Spotify link (requested by {ctx['username']})",
    )
