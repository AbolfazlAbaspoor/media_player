"""
تنظیماتِ جستجوی صوتی (فقط admin_bot).

    vss                     نمایشِ همه‌ی تنظیمات (کلیدهای حساس نیمه‌پنهان)
    vss <key> <value>       تغییرِ یه کلید

کلیدها و اعتبارسنجی‌شون توی core/voice_search.py (validate/DEFAULTS)؛
این فایل فقط نمایش و پیام‌هاست. توضیحِ کاملِ هر کلید توی docs/VOICE_SEARCH.md.
"""

from core import i18n
from core import voice_search

NAME = 'vss'
REQUIRED_ROLE = "admin_bot"
USAGE = voice_search.USAGE_VSS


def _show(bot, uid):
    lines = [i18n.t('vss_header')]
    for key, value in voice_search.display_settings(bot):
        lines.append(f"{key} = {value}")
    bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))


def _describe_error(error):
    if error == 'unknown_key':
        return i18n.t('vss_unknown_key')
    if error == 'bool':
        return i18n.t('vss_invalid_bool')
    if error == 'number':
        return i18n.t('vss_invalid_number')
    if error.startswith('range:'):
        _, lo, hi = error.split(':')
        return i18n.t('vss_invalid_range', min=lo, max=hi)
    if error.startswith('choice:'):
        choices = error.split(':', 1)[1]
        return i18n.t('vss_invalid_choice', choices=choices)
    return i18n.t('vss_invalid_value')


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = ctx.get('args') or []

    if not args:
        _show(bot, uid)
        return

    if len(args) < 2:
        bot.t.user_message(uid, i18n.t('usage_generic', usage=bot.commands['vss']['usage']))
        return

    key = args[0].strip().lower()
    raw_value = " ".join(args[1:])
    ok, error, value = voice_search.set_setting(bot, key, raw_value)
    if not ok:
        bot.t.user_message(uid, _describe_error(error))
        return
    bot.t.user_message(uid, i18n.t('vss_set', setting=key, value=voice_search.mask_value(key, value)))
