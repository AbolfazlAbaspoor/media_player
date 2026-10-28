"""
تنظیمات خطِ استاتوس ربات روی سرور، از داخل خود تیم‌تاک.

    sts                          وضعیت فعلی
    sts gender male|female|neutral
    sts away on|off              وقتی مکث شده، حالت «away» بگیره یا نه
    sts idle <متن>               متنی که وقتی چیزی پخش نمی‌شه نشون داده می‌شه

نمایش/مخفی‌کردن کل استاتوس با دستور h است.
"""

from core import i18n, status_line

NAME = "sts"
REQUIRED_ROLE = "admin_server"
USAGE = "sts [gender male|female|neutral | away on|off | idle <text>]"


def _status_cfg(bot):
    return bot.cfg.setdefault("status", {})


def _show(bot, uid):
    cfg = _status_cfg(bot)
    bot.t.user_message(uid, i18n.t(
        "status_settings",
        visible=i18n.t("state_enabled") if bot.status_visible else i18n.t("state_disabled"),
        gender=cfg.get("gender", "neutral"),
        away=i18n.t("state_enabled") if cfg.get("away_when_paused") else i18n.t("state_disabled"),
        idle=cfg.get("idle_text", "Idle"),
    ))


def run(ctx):
    bot = ctx["bot"]
    uid = ctx["uid"]
    args = ctx["args"]
    if not args:
        _show(bot, uid)
        return

    key = args[0].lower()
    value = " ".join(args[1:]).strip()
    cfg = _status_cfg(bot)

    if key == "gender" and value.lower() in status_line.GENDER_FLAGS:
        cfg["gender"] = value.lower()
    elif key == "away" and value.lower() in ("on", "off"):
        cfg["away_when_paused"] = value.lower() == "on"
    elif key == "idle" and value:
        cfg["idle_text"] = status_line.fit(value)
    else:
        bot.t.user_message(uid, i18n.t("usage_generic", usage=USAGE))
        return

    bot.save_config()
    # تیک بعدی حلقه‌ی اصلی با تنظیمات جدید دوباره می‌فرستتش.
    status_line.invalidate()
    _show(bot, uid)
