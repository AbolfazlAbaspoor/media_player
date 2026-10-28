"""
زیرنویسِ زنده‌ی آهنگِ در حال پخش، به‌صورت پیام خصوصی (برای هر کاربر جدا).

    sub            روشن/خاموش (پیش‌فرض خاموش)
    sub <lang>     زبان رو ست می‌کنه و روشن می‌کنه (sub fa، sub en، ...)
    sub on / off   صریحاً روشن/خاموش

منطق و توضیح کامل توی core/subtitles.py؛ این فایل فقط پوسته‌ی دستوره.
"""

from core import i18n
from core import subtitles

NAME = 'sub'
ADMIN_ONLY = False
USAGE = 'sub [language]  (toggle live subtitles, sent to you privately; e.g. sub fa, sub en)'


def run(ctx):
    bot, uid, username = ctx["bot"], ctx["uid"], ctx["username"]
    args = ctx.get("args") or []

    if not args:
        enabled, lang = subtitles.toggle(bot, uid, username)
    else:
        word = args[0].strip().lower()
        if word == "off":
            subtitles.disable(bot, username)
            enabled, lang = False, None
        elif word == "on":
            enabled, lang = True, subtitles.enable(bot, uid, username)
        else:
            lang = subtitles.normalize_language(word)
            if lang is None:
                bot.t.user_message(uid, i18n.t("sub_bad_lang"))
                return
            enabled = True
            subtitles.enable(bot, uid, username, lang)

    if enabled:
        bot.t.user_message(uid, i18n.t("sub_on", lang=lang))
    else:
        bot.t.user_message(uid, i18n.t("sub_off"))
