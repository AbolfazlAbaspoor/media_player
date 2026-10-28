"""
مدیریت منبع‌های IPTV (فقط admin_server).

    tvs                    نمایش منبع‌ها (میزبانِ نیمه‌پنهان)
    tvs add <آدرس> [اسم]   افزودن منبع تازه
    tvs del <شماره>        حذف منبع با شماره‌ی همینی که tvs نشون می‌ده
    tvs reload             خالی‌کردن کش و لود دوباره‌ی همه‌ی منبع‌ها

آدرس منبع‌ها (و کانال‌های داخلشون) هیچ‌جا کامل چاپ نمی‌شه -- فقط اسم و
میزبانِ نیمه‌پنهانِ core.iptv.mask_host، چون این آدرس‌ها معمولاً یوزر/پسورد
اشتراک IPTV رو هم توی خودشون دارن.
"""

from core import i18n
from core import iptv
from core import logging_setup

NAME = "tvs"
REQUIRED_ROLE = "admin_server"
USAGE = "tvs [add <url> [name] | del <index> | reload]"


def _show(bot, uid):
    srcs = iptv.sources(bot)
    if not srcs:
        bot.t.user_message(uid, i18n.t("tvs_no_sources"))
        return
    lines = [i18n.t("tvs_sources_header", count=len(srcs))]
    for i, src in enumerate(srcs, start=1):
        lines.append(f"{i}. {src.get('name') or '?'} — {iptv.mask_host(src.get('url', ''))}")
    bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))


def _save_sources(bot, srcs):
    bot.cfg.setdefault("iptv", {})["sources"] = srcs
    bot.save_config()
    iptv.invalidate_cache(bot)


def _add(bot, uid, args):
    if len(args) < 2 or not iptv.looks_like_source_url(args[1]):
        bot.t.user_message(uid, i18n.t("tvs_add_invalid"))
        return
    url = args[1]
    srcs = iptv.sources(bot)
    name = " ".join(args[2:]).strip() or i18n.t("tvs_unnamed_source", index=len(srcs) + 1)
    srcs.append({"name": name, "url": url})
    _save_sources(bot, srcs)
    bot.t.user_message(uid, i18n.t("tvs_added", name=name, host=iptv.mask_host(url)))


def _del(bot, uid, args):
    srcs = iptv.sources(bot)
    index = args[1] if len(args) > 1 else ""
    if not index.isdigit() or not (1 <= int(index) <= len(srcs)):
        bot.t.user_message(uid, i18n.t("tvs_invalid_index"))
        return
    removed = srcs.pop(int(index) - 1)
    _save_sources(bot, srcs)
    bot.t.user_message(uid, i18n.t("tvs_deleted", name=removed.get("name") or "?"))


def _reload(bot, uid):
    iptv.invalidate_cache(bot)
    try:
        channels = iptv.fetch_channels(bot, force=True)
    except iptv.IPTVError as e:
        bot.t.user_message(uid, str(e))
        return
    except Exception as e:
        bot.t.user_message(uid, i18n.t("generic_error", error=logging_setup.safe_error_text(e)))
        return
    bot.t.user_message(uid, i18n.t("tvs_reloaded", count=len(channels)))


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = ctx.get("args") or []

    if not args or args[0].lower() == "show":
        _show(bot, uid)
        return

    action = args[0].lower()
    if action == "add":
        _add(bot, uid, args)
    elif action == "del":
        _del(bot, uid, args)
    elif action == "reload":
        _reload(bot, uid)
    else:
        bot.t.user_message(uid, i18n.t("usage_generic", usage=USAGE))
