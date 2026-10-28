"""
سیستم چهارسطحی دسترسیِ دستورات.

    admin_server > admin_bot > channel_operator > normal

هرکسی سطح بالاتر داشته باشه، خودکار همه‌ی سطوح پایین‌تر رو هم داره (یه
admin_server می‌تونه هر دستور admin_bot/channel_operator/normal رو هم
اجرا کنه).

  admin_server:      یوزرنیم توی admins (shared_config.json) -- روی همه‌ی
                      ربات‌های این سرور اثر داره؛ برای تنظیمات مشترک/حساس
                      (پروکسی، زبان، ری‌استارت، لیست ادمین‌ها، دسترسی، ...).
  admin_bot:          یوزرنیم توی bot_admins (identity.json) -- فقط همین
                      نمونه‌ی ربات؛ برای تنظیمات مخصوص همین ربات (نیک‌نیم،
                      alias ها، تایمرهای دانلود، ...).
  channel_operator:   وضعیتِ زنده‌ی SDK (TT_IsChannelOperator) توی کانالِ
                      فعلیِ ربات -- هیچ‌جا ذخیره نمی‌شه، همیشه لحظه‌ای
                      مستقیم از TeamTalk چک می‌شه (نه از کانفیگ ما).
  normal:             هرکس دیگه؛ پیش‌فرض هر دستوری که REQUIRED_ROLE نداره.
"""

ROLE_ORDER = ("normal", "channel_operator", "admin_bot", "admin_server")


def _rank(role):
    try:
        return ROLE_ORDER.index(role)
    except ValueError:
        return 0  # نقشِ نامعتبر/ناشناس -> normal


def user_role(bot, uid, username):
    """بالاترین سطحی که این کاربر همین الان داره."""
    if username in bot.cfg.get("admins", []):
        return "admin_server"
    if username in bot.cfg.get("bot_admins", []):
        return "admin_bot"
    try:
        if bot.t.is_channel_operator(uid):
            return "channel_operator"
    except Exception:
        pass
    return "normal"


def has_role(bot, uid, username, required_role):
    """True یعنی این کاربر حداقل سطح required_role رو داره."""
    return _rank(user_role(bot, uid, username)) >= _rank(required_role)
