"""
رأی‌گیری برای رد کردن آهنگ (دستور vn).

قاعده: آهنگ وقتی رد می‌شه که تعداد رأی‌ها از (ratio × تعداد کاربرهای کانال)
*بیشتر* بشه. کاربرها = همه‌ی آدم‌های کانالِ فعلیِ ربات به‌جز خودِ ربات
(bot.t.get_channel_users(exclude_self=True)). پیش‌فرض ratio = 0.5، یعنی
«بیشتر از نصف»، و توی shared_config زیرِ کلیدِ vote_skip قابل‌تنظیمه
(config_defaults.VOTE_SKIP_DEFAULTS). یه نفرِ تنها همین‌جوری فوراً رد می‌کنه.

رأی‌ها به «همین آهنگ» می‌چسبن: کلیدِ آهنگ (epoch صف، ایندکس، لینکِ mpv)
هر بار که عوض بشه -- با n، b، پایانِ طبیعی، سرچِ تازه -- رأی‌ها از نو
شروع می‌شن. برای همین هیچ hook یا تایمری لازم نیست و هزینه‌ی این قابلیت
بیرون از لحظه‌ی رأی دادن صفره. رأیِ کسی که از کانال رفته حساب نمی‌شه.

رد کردن دقیقاً از همون مسیرِ دستورِ n می‌ره (handlerِ خودِ n، که حالت
مستند/IPTV/آخر صف رو هم درست مدیریت می‌کنه و TrackQueue.advance(force=True)
رو صدا می‌زنه)، نه یه کپیِ جدا از اون منطق.
"""

import math
import threading

from core import command_helpers
from core import config_defaults
from core import i18n
from core import logging_setup

_lock = threading.Lock()


def settings(bot):
    return config_defaults.feature_settings(bot, "vote_skip", config_defaults.VOTE_SKIP_DEFAULTS)


def ratio(bot):
    """کسرِ لازم، همیشه توی [0, 1): مقدارِ خراب -> پیش‌فرض."""
    default = config_defaults.VOTE_SKIP_DEFAULTS["ratio"]
    try:
        value = float(settings(bot).get("ratio", default))
    except (TypeError, ValueError):
        return default
    if math.isnan(value):
        return default
    return min(max(value, 0.0), 0.99)


def needed_votes(total_users, vote_ratio):
    """
    کمترین تعداد رأیی که از vote_ratio × total_users *بیشتر* باشه، با سقفِ
    خودِ کاربرها (وگرنه با ratio بالا هیچ‌وقت رد نمی‌شد) و کفِ ۱.
    """
    total_users = max(1, int(total_users))
    return max(1, min(total_users, math.floor(total_users * vote_ratio) + 1))


def _identity(user, fallback_uid=None):
    return user.get("username") or f"#{user.get('user_id', fallback_uid)}"


def _track_key(bot):
    return (bot.queue.epoch, bot.queue.index, bot.player.current_url)


def _state(bot):
    st = getattr(bot, "_vote_skip", None)
    if st is None:
        st = bot._vote_skip = {"key": None, "voters": set()}
    return st


def cast(bot, ctx):
    """
    رأیِ ctx["username"] رو ثبت می‌کنه. خروجی (وضعیت، رأی‌ها، لازم):
      "no_track" | "not_in_channel" | "already" | "voted" | "passed"
    """
    if bot.player.current_url is None:
        return "no_track", 0, 0
    channel_users = bot.t.get_channel_users(exclude_self=True)
    present = {_identity(user) for user in channel_users}
    me = ctx.get("username") or f"#{ctx['uid']}"
    if me not in present:
        return "not_in_channel", 0, 0

    with _lock:
        st = _state(bot)
        key = _track_key(bot)
        if st["key"] != key:
            st["key"] = key
            st["voters"] = set()
        already = me in st["voters"]
        st["voters"].add(me)
        votes = len(st["voters"] & present)
        needed = needed_votes(len(present), ratio(bot))
        if already:
            return "already", votes, needed
        if votes >= needed:
            st["voters"] = set()
            return "passed", votes, needed
        return "voted", votes, needed


def run_vote(bot, ctx):
    """منطقِ دستورِ vn: رأی، اعلامِ کانال، و در صورتِ رسیدن به حد، رد کردن."""
    uid = ctx["uid"]
    status, votes, needed = cast(bot, ctx)
    if status == "no_track":
        bot.t.user_message(uid, i18n.t("nothing_playing"))
    elif status == "not_in_channel":
        bot.t.user_message(uid, i18n.t("vn_not_in_channel"))
    elif status == "already":
        bot.t.user_message(uid, i18n.t("vn_already", votes=votes, needed=needed))
    else:
        command_helpers.notify(bot, ctx, "vn_voted", nickname=ctx["nickname"], votes=votes, needed=needed)
        if status == "passed":
            _skip(bot, ctx)


def _skip(bot, ctx):
    """همان مسیرِ n: handlerِ ثبت‌شده‌ی خودِ دستور n با ctxِ رأی‌دهنده."""
    try:
        bot.commands["n"]["handler"](ctx)
    except Exception as e:
        logging_setup.log_exception("vote skip")
        bot.t.user_message(ctx["uid"], i18n.t(
            "command_error", error=logging_setup.safe_error_text(e, context="vn: skip")))
