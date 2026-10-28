"""Migrated from bot.py's built-in commands."""

from core import i18n, status_line

NAME = 'h'
REQUIRED_ROLE = "admin_server"
USAGE = 'h'

def run(ctx):
    bot = ctx["bot"]
    bot.status_visible = not bot.status_visible
    bot.cfg.setdefault('status', {})['visible'] = bot.status_visible
    bot.save_config()
    # تیک بعدیِ حلقه‌ی اصلی یا متن رو برمی‌داره (خاموش) یا دوباره می‌فرستتش
    # (روشن). بدون invalidate، روشن‌کردنِ دوباره هیچی نمی‌فرستاد چون متن
    # همونی بود که آخرین بار کش شده بود.
    status_line.invalidate()
    state = i18n.t('state_enabled') if bot.status_visible else i18n.t('state_disabled')
    bot.channel_broadcast(i18n.t('status_broadcast_toggled', state=state, nickname=ctx['nickname']))
