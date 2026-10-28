"""
Instagram login/session management.

    ig <username> <password>   -> لاگین با رمز (اول بار) یا refresh
    ig session <sessionid>     -> لاگین با کوکیِ sessionid (مطمئن‌تر)
    ig out                     -> خروج و پاک‌کردنِ سشنِ ذخیره‌شده
    ig                         -> وضعیت

Session به صورت شخصی ذخیره می‌شه و رمزگذاری شده است (با کلیدِ مخصوصِ
هر ربات -- توضیحِ معامله‌ش توی core/instagram_user.py).

چرا sessionid: اینستاگرام لاگینِ با رمز رو از IPِ سرور/پروکسی اغلب رد
می‌کنه (challenge، بلاک، پاسخِ خراب). کوکیِ sessionid رو از مرورگری
برمی‌داری که قبلاً اونجا لاگینی؛ رمزت هم هیچ‌وقت به ربات نمی‌رسه.
"""

from core import i18n
from core import instagram_bot
from core import instagram_user
from core import logging_setup

NAME = 'ig'
ADMIN_ONLY = False
USAGE = 'ig <username> <password> | ig session <sessionid> | ig out | ig'


def _report_failure(bot, ctx, result, username=""):
    """پیامِ دلیلِ شکستِ لاگین. True اگه پیام فرستاده شد (یعنی شکست بود)."""
    status = result["status"]
    uid = ctx['uid']
    if status == "rate_limited":
        bot.t.user_message(uid, i18n.t('ig_rate_limited', wait_seconds=result.get("wait_seconds", 0)))
    elif status == "wrong_password":
        bot.t.user_message(uid, i18n.t('ig_wrong_password', username=username))
    elif status == "session_expired":
        bot.t.user_message(uid, i18n.t('ig_session_expired', username=username))
    elif status == "bad_sessionid":
        bot.t.user_message(uid, i18n.t('ig_bad_sessionid'))
    elif status == "instagrapi_unavailable":
        bot.t.user_message(uid, i18n.t('ig_instagrapi_unavailable'))
    elif status in instagram_bot.FAILURE_KEYS:
        bot.t.user_message(uid, instagram_bot.failure_text(status, username, result.get("error_class", "")))
    else:
        return False
    return True


def _login_with_password(bot, ctx, username, password):
    if not instagram_user.valid_username(username):
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=USAGE))
        return
    result = instagram_user.login_or_create(username, password)
    if _report_failure(bot, ctx, result, username):
        return
    if result["status"] == "logged_in":
        bot.t.user_message(ctx['uid'], i18n.t('ig_logged_in', username=username))
    elif result["status"] == "created":
        bot.t.user_message(ctx['uid'], i18n.t('ig_created', username=username))
    else:
        bot.t.user_message(ctx['uid'], i18n.t('command_error', error=result["status"]))
        return
    instagram_bot.link(bot, ctx['username'], username)


def _login_with_sessionid(bot, ctx, sessionid):
    result = instagram_user.login_with_sessionid(sessionid, who=ctx['username'])
    if _report_failure(bot, ctx, result, '(sessionid)'):
        return
    username = result["username"]
    bot.t.user_message(ctx['uid'], i18n.t('ig_created', username=username))
    instagram_bot.link(bot, ctx['username'], username)


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    uid = ctx['uid']

    try:
        instagram_bot.init_bot(bot)
    except Exception as e:
        bot.t.user_message(uid, i18n.t('command_error', error=logging_setup.safe_error_text(e)))
        return

    if len(args) == 2 and args[0].lower() == 'session':
        _login_with_sessionid(bot, ctx, args[1])
    elif len(args) == 1 and args[0].lower() == 'session':
        bot.t.user_message(uid, i18n.t('ig_session_help'))
    elif len(args) == 1 and args[0].lower() == 'out':
        ig_username = instagram_bot.unlink(bot, ctx['username'])
        bot.t.user_message(uid, i18n.t('ig_logged_out', username=ig_username) if ig_username
                           else i18n.t('ig_not_logged_in'))
    elif len(args) >= 2:
        _login_with_password(bot, ctx, args[0], args[1])
    else:
        ig_username = instagram_bot.linked_username(bot, ctx['username'])
        if ig_username:
            bot.t.user_message(uid, i18n.t('ig_session_loaded', username=ig_username))
        else:
            bot.t.user_message(uid, i18n.t('ig_not_logged_in'))
