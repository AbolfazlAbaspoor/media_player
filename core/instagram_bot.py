"""
چسبِ بین ربات و اینستاگرام: دستورهای ig/rl/iu/... همه از اینجا رد می‌شن.

  * کدوم اکانتِ اینستاگرام مالِ کدوم کاربرِ تیم‌تاکه (bot.cfg["_ig_sessions"])
  * ساختنِ client از سشنِ ذخیره‌شده (از طریق پروکسی -- instagram_api.new_client)
  * ترجمه‌ی هر شکستِ instagrapi به یه پیامِ واقعی (بدون متنِ خامِ استثنا)
  * مرور -> صف: آیتم‌های پیدا‌شده یک‌جا وارد صفِ پخش می‌شن، پس n/b همون
    n/b معمولیِ صف‌ان.

importهای instagrapi تنبل‌اند (instagram_api)، پس import این فایل سبکه.
"""

from core import command_helpers
from core import i18n
from core import instagram_api
from core import instagram_user
from core import logging_setup

# دلیلِ شکست (instagram_user.login_failure_status) -> کلیدِ پیام.
# هم لاگین هم دستورهای مرور ازش استفاده می‌کنن.
FAILURE_KEYS = {
    "two_factor_required": "ig_two_factor_required",
    "challenge_required": "ig_challenge_required",
    "instagram_rate_limited": "ig_instagram_rate_limited",
    "network_error": "ig_network_error",
    "ip_blocked": "ig_ip_blocked",
    "bad_response": "ig_bad_response",
    "action_blocked": "ig_action_blocked",
    "session_rejected": "ig_session_rejected",
    "age_restricted": "ig_age_restricted",
    "login_failed": "ig_login_failed",
}


def init_bot(bot):
    """پوشه‌ی سشن‌ها و وضعیتِ ریل‌ها رو (یک بار برای هر ربات) آماده می‌کنه."""
    if hasattr(bot, "_instagram_sessions_init"):
        return
    instagram_user.set_bot_dir(bot.server_dir)
    bot._instagram_sessions_init = True
    bot._ig_reels = {}  # {username: [ریل‌های لودشده]}
    bot._ig_current_index = {}  # {username: اندیسِ جاری (وقتی صف نشونش نمی‌ده)}


def linked_username(bot, tt_username):
    """اکانتِ اینستاگرامِ وصل‌شده به این کاربرِ تیم‌تاک، یا None."""
    for info in bot.cfg.get("_ig_sessions", {}).values():
        if info.get("tt_username") == tt_username:
            return info.get("ig_username")
    return None


def link(bot, tt_username, ig_username):
    """این کاربر فقط یه اکانت داره: اتصالِ قبلی‌ش با جدید عوض می‌شه."""
    sessions = bot.cfg.setdefault("_ig_sessions", {})
    for key in [k for k, v in sessions.items() if v.get("tt_username") == tt_username]:
        del sessions[key]
    sessions[f"ig_{ig_username}"] = {
        "ig_username": ig_username, "tt_username": tt_username, "loaded_at": None,
    }
    bot.save_config()


def unlink(bot, tt_username):
    """(ig_username یا None). سشنِ ذخیره‌شده هم پاک می‌شه."""
    ig_username = linked_username(bot, tt_username)
    sessions = bot.cfg.get("_ig_sessions", {})
    for key in [k for k, v in sessions.items() if v.get("tt_username") == tt_username]:
        del sessions[key]
    if ig_username:
        instagram_user.delete_session(ig_username)
        bot.save_config()
    return ig_username


def failure_text(status, username="", error_class=""):
    """متنِ پیامِ یه دلیلِ شکست. error_class فقط نامِ کلاسِ استثناست."""
    return i18n.t(FAILURE_KEYS.get(status, "ig_login_failed"),
                  username=username, error_class=error_class or "Error")


def exception_text(exc, username=""):
    """پیامِ کاربرپسند برای استثنای instagrapi (هرگز متنِ خامِ استثنا)."""
    return failure_text(instagram_user.login_failure_status(exc), username,
                        instagram_user.safe_class_name(exc))


def reply_failure(bot, ctx, exc):
    """پیامِ دلیلِ واقعیِ شکستِ instagrapi رو خصوصی به کاربر می‌فرسته."""
    bot.t.user_message(ctx["uid"], exception_text(exc, linked_username(bot, ctx["username"]) or ""))


def client_for(bot, tt_username):
    """
    (client, None) یا (None, پیامِ خطا برای کاربر). سشن با کلیدِ ربات باز
    می‌شه (instagram_user.load_saved_session) -- رمز لازم نیست.
    """
    try:
        init_bot(bot)  # بعد از ری‌استارت هم لازمه (فقط دستور ig صداش نمی‌زنه)
    except Exception as e:
        return None, i18n.t("command_error", error=logging_setup.safe_error_text(e))
    ig_username = linked_username(bot, tt_username)
    if not ig_username:
        return None, i18n.t("ig_not_logged_in")
    session_data, cookie_str = instagram_user.load_saved_session(ig_username)
    if not session_data:
        return None, i18n.t("ig_session_expired", username=ig_username)
    client = instagram_api.load_client_from_session(session_data, cookie_str)
    if not client:
        return None, i18n.t("ig_instagrapi_unavailable")
    return client, None


def current_reel_index(bot, tt_username, reels):
    """
    اندیسِ ریلی که الان پخش می‌شه. صف (n/b) موقعیت رو نگه می‌داره، پس از روی
    لینکِ عمومیِ آیتمِ جاری پیداش می‌کنیم؛ اگه پیدا نشد آخرین اندیسِ ثبت‌شده.
    """
    queue = getattr(bot, "queue", None)
    track = queue.current() if queue is not None else None
    url = getattr(track, "public_url", None)
    if isinstance(url, str):
        for index, reel in enumerate(reels):
            code = getattr(reel, "code", None)
            if isinstance(code, str) and code and f"/{code}/" in url:
                return index
    return getattr(bot, "_ig_current_index", {}).get(tt_username, 0)


def run_browse(ctx, fetch, what):
    """
    الگوی مشترکِ مرورِ اینستاگرام (rl/rr/iu/ist/ihl/iht/isv/ilk): client
    بساز، fetch(client) رو صدا بزن، ویدیوهای نتیجه رو وارد صف کن و پخش.

    what: توضیحِ کوتاهِ محتوا برای پیام ("@user reels"). خطاها به پیامِ
    واقعیشون ترجمه می‌شن (بلاک، چلنج، محدودیت، قطعیِ شبکه...) و هرگز متنِ
    خامِ استثنا به کاربر نمی‌رسه.
    """
    bot, uid, username = ctx["bot"], ctx["uid"], ctx["username"]
    client, error = client_for(bot, username)
    if error:
        bot.t.user_message(uid, error)
        return
    logging_setup.set_operation(f"loading Instagram {what} (requested by {username})")
    try:
        medias = instagram_api.playable_medias(fetch(client))
        if not medias:
            bot.t.user_message(uid, i18n.t("ig_nothing_playable", what=what))
            return
        bot._ig_reels[username] = medias
        bot._ig_current_index[username] = 0
        count = bot.load_and_play(instagram_api.to_play_items(medias), private=True,
                                  service_name="instagram")
        command_helpers.notify(bot, ctx, "ig_feed_playing", nickname=ctx["nickname"],
                               what=what, count=count)
        command_helpers.broadcast_now_playing(bot)
    except Exception as e:
        logging_setup.log_debug(f"instagram browse '{what}' failed: {type(e).__name__}")
        reply_failure(bot, ctx, e)
    finally:
        logging_setup.set_operation("idle")


def username_arg(ctx, usage):
    """اولین آرگومان به‌عنوان یوزرنیم اینستاگرام (@ و / حذف می‌شه)، یا None بعد
    از فرستادنِ راهنما."""
    args = ctx.get("args") or []
    name = args[0].lstrip("@").strip("/") if args else ""
    if not instagram_user.valid_username(name):
        ctx["bot"].t.user_message(ctx["uid"], i18n.t("usage_generic", usage=usage))
        return None
    return name
