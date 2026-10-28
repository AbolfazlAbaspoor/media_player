"""
حساب شخصی و فروریت (لیست دوست‌داشتنی‌های شخصیِ کاربر، مستقل از TeamTalk).

    sf <username> <password>   -> لاگین (اگه حساب هست) یا ساخت حساب جدید
                                   (اگه نیست). این پسورد کاملاً جداست از
                                   پسورد اکانت TeamTalk -- هیچ ربطی بهش نداره.
    sf <number>                -> پخش مستقیم آیتم شماره‌ی N فروریت
    sf                         -> پخش کل فروریت به‌عنوان یه پلی‌لیست (از
                                   آیتم اول)، هرکدوم از همون نقطه‌ای که قبلاً
                                   ذخیره شده (af) ادامه پیدا می‌کنه.

بقیه‌ی دستورهای همین خانواده: sfl (لیست)، af/aff (اضافه/به‌روزرسانی)،
rf (حذف)، of (عمومی/خصوصی).
"""

import threading

from core import i18n
from core import accounts
from core import command_helpers
from core import link_resolver
from core import logging_setup

NAME = 'sf'
ADMIN_ONLY = False
USAGE = 'sf <username> <password> | sf <number> | sf  (personal favorites account)'


def _play_entries(bot, ctx, entries, start_index=0):
    """
    entries: لیست dict های {url, title, public_url, time}. از start_index
    شروع می‌کنه، به‌عنوان یه پلی‌لیست لود می‌شه، و بعد به زمان ذخیره‌شده‌ی
    آیتم اول seek می‌کنه.
    """
    def _resolved(e):
        # فروریت فقط لینکِ صفحه رو ذخیره کرده (نه استریمِ منقضی‌شونده)؛ باید
        # همین الان دوباره resolve بشه، دقیقاً مثلِ یه لینکِ تازه‌پیست‌شده
        # (core.command_helpers.resolve_playable -- توضیح کامل اونجا).
        item, service_name = command_helpers.resolve_playable(bot, e.get("public_url") or e["url"])
        built = {
            "url": item.get("url"),
            "title": item.get("title") or e.get("title"),
            "public_url": item.get("public_url") or e.get("public_url") or e["url"],
            "info": item.get("info"),
        }
        return built, service_name, e.get("time") or 0

    def _play():
        ordered = entries[start_index:] + entries[:start_index]
        resolved = [_resolved(e) for e in ordered]
        # آیتم‌هایی که واقعاً resolve نشدن (سرویس دیگه در دسترس نیست، لینک
        # از بین رفته) رد می‌شن -- نه این‌که کلِ فروریت رو fail کنن.
        playable = [(item, service_name, resume) for item, service_name, resume in resolved if item.get("url")]
        if not playable:
            command_helpers.notify(bot, ctx, 'no_stream_found')
            logging_setup.set_operation('idle')
            return
        items = [item for item, _, _ in playable]
        # سرویس/زمانِ ادامه‌ی آیتمِ اولِ *واقعاً قابل‌پخش* -- ممکنه با
        # entries[start_index] فرق کنه اگه اون یکی resolve نشده باشه.
        service_name = playable[0][1]
        logging_setup.set_operation(f"playing personal favorites (requested by {ctx['username']})")
        try:
            bot.load_and_play(items, private=False, service_name=service_name)
        except Exception as e:
            command_helpers.notify(bot, ctx, 'link_play_failed', error=logging_setup.safe_error_text(e))
            logging_setup.set_operation('idle')
            return

        resume_at = playable[0][2]
        if resume_at:
            try:
                # mpv فوراً بعد از play() فایل رو "باز" اعلام نمی‌کنه؛ seek
                # زودتر از موعد با SystemError (-12) fail می‌شه. صبر می‌کنیم
                # تا واقعاً پخش شروع بشه، بعد seek می‌کنیم.
                bot.player.wait_until_playing(timeout=5)
                bot.player.seek_to(resume_at)
            except Exception:
                # پخش خودش موفق بوده -- فقط ادامه از نقطه‌ی ذخیره‌شده ممکنه
                # جواب نده (مثلاً استریم زنده/کوتاه بوده). این نباید کل
                # دستور رو fail نشون بده چون آهنگ داره درست پخش می‌شه.
                logging_setup.log_debug("sf: resume seek failed, playing from start instead")

        bot.channel_broadcast(i18n.t('sf_playing', nickname=ctx['nickname'], count=len(items)))
        logging_setup.set_operation('idle')

    threading.Thread(target=_play, daemon=True).start()


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']

    # --- sf <username> <password> : login / register ------------------
    if len(args) >= 2:
        username, password = args[0].lower(), args[1]
        result = accounts.login_or_register(bot, username, password)

        if result["status"] == "invalid_username":
            bot.t.user_message(ctx['uid'], i18n.t('sf_invalid_username'))
            return
        if result["status"] == "wrong_password":
            bot.t.user_message(ctx['uid'], i18n.t('sf_wrong_password', username=username))
            return

        accounts.session_login(bot, ctx['username'], username)
        if result["status"] == "created":
            bot.t.user_message(ctx['uid'], i18n.t('sf_created', username=username))
        else:
            bot.t.user_message(ctx['uid'], i18n.t('sf_logged_in', username=username))
        return

    # --- sf  /  sf <number> : بقیه‌ی حالت‌ها نیاز به لاگین دارن ---------
    found = command_helpers.session_favorites(bot, ctx)
    if found is None:
        return
    (account_username, path, data, is_public), favorites = found

    if args:
        if not args[0].isdigit():
            bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['sf']['usage']))
            return
        idx = int(args[0]) - 1
        if not (0 <= idx < len(favorites)):
            bot.t.user_message(ctx['uid'], i18n.t('invalid_playlist_number'))
            return
        _play_entries(bot, ctx, favorites, start_index=idx)
        return

    _play_entries(bot, ctx, favorites, start_index=0)
