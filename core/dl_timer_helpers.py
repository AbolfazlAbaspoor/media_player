"""
منطق مشترک تایمرهای حذف فایل دانلودی (کانال/لوکال/scope)، به اشتراک
گذاشته‌شده بین dlt.py (دستور همه‌کاره‌ی قدیمی) و دستورات جدا/اختصاصی
dltc/dltl/dlts -- تا هر بخش هم از طریق dlt و هم مستقل قابل‌تنظیم باشه،
بدون تکرار کد.
"""

from core import i18n


def status_text(bot):
    scope = bot.cfg.get('dl_auto_remove_scope', 'shared')
    effective = bot.dl_auto_remove_minutes_effective()
    shared_val = bot.cfg.get('dl_auto_remove_minutes', 0)
    own_val = bot.cfg.get('dl_auto_remove_minutes_own', 0)
    local_val = bot.cfg.get('downloads_cleanup_minutes', 1440)
    return i18n.t(
        'dl_timers_status', scope=scope, effective=effective, shared=shared_val, own=own_val, local=local_val,
    )


def set_channel_timer(bot, minutes):
    """تایمر حذف از کانال رو تنظیم می‌کنه (طبق scope فعلی: shared یا per_bot)."""
    if bot.cfg.get('dl_auto_remove_scope', 'shared') == 'per_bot':
        bot.cfg['dl_auto_remove_minutes_own'] = minutes
    else:
        bot.cfg['dl_auto_remove_minutes'] = minutes
    bot.save_config()


def set_local_timer(bot, minutes):
    """تایمر پاک‌سازی پوشه‌ی downloads محلی (همیشه مخصوص همین ربات)."""
    bot.cfg['downloads_cleanup_minutes'] = minutes
    bot.save_config()


def set_scope(bot, scope, minutes=None):
    """scope رو 'shared' یا 'per_bot' می‌کنه؛ اگه minutes بدی و per_bot باشه، همون‌موقع هم ثبتش می‌کنه."""
    bot.cfg['dl_auto_remove_scope'] = scope
    if scope == 'per_bot' and minutes is not None:
        bot.cfg['dl_auto_remove_minutes_own'] = minutes
    bot.save_config()


# --- بدنه‌ی مشترکِ dlt و دستورهای جداشده‌ی dltc/dltl/dlts ---------------

def apply_channel_timer(bot, ctx, minutes):
    set_channel_timer(bot, minutes)
    bot.channel_broadcast(i18n.t('dl_auto_remove_set', nickname=ctx['nickname'], minutes=minutes))


def apply_local_timer(bot, ctx, minutes):
    set_local_timer(bot, minutes)
    bot.t.user_message(ctx['uid'], i18n.t('dl_local_cleanup_set', minutes=minutes))


def apply_scope_shared(bot, ctx):
    set_scope(bot, 'shared')
    bot.t.user_message(ctx['uid'], i18n.t('dl_scope_set', scope='shared'))


def apply_scope_mine(bot, ctx, minutes=None):
    set_scope(bot, 'per_bot', minutes)
    bot.t.user_message(ctx['uid'], i18n.t('dl_scope_set', scope='per_bot'))
