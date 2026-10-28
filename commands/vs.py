"""
جستجوی صوتی (roadmap C3، امکانِ لایسنسیِ cap_voice_search).

    vs              صدای فرستنده رو ضبط می‌کنه و باهاش دقیقاً مثلِ «p <متن>» جستجو می‌کنه
    vs <lang>       همون کار، ولی فقط همین یه بار با این زبون (مثلاً vs en یا vs fa-IR)
    vs cancel       جستجوی صوتیِ درحال‌اجرا (هرکی شروعش کرده) رو متوقف می‌کنه

تنظیمات (زبانِ پیش‌فرض، موتور، مهلت‌ها، ...) با دستورِ «vss». منطقِ کامل
توی core/voice_search.py؛ این فایل فقط پارسِ آرگومان‌هاست.
"""

from core import i18n
from core import voice_search

NAME = 'vs'
REQUIRED_ROLE = "normal"
USAGE = voice_search.USAGE_VS


def run(ctx):
    bot = ctx["bot"]
    args = ctx.get('args') or []

    if args and args[0].lower() == 'cancel':
        voice_search.cancel(bot, ctx)
        return

    if len(args) > 1:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['vs']['usage']))
        return

    language_override = args[0] if args else None
    voice_search.start(bot, ctx, language_override=language_override)
