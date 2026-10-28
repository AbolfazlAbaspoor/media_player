"""
نمایش وضعیت لایسنس همین ربات، از داخل خود تیم‌تاک.

چرا لازمه: وقتی یه دستور کار نمی‌کنه، اولین سؤال کاربر اینه «خریدمش یا
نه؟». بدون این دستور، جواب فقط از ربات تلگرام یا از ادمین در می‌آمد.

روی نصب‌های شخصی (بدون فایل لایسنس) هم کار می‌کنه و می‌گه محدودیتی نیست.
"""

from core import i18n

NAME = ("lic", "license")
USAGE = "lic  (وضعیت لایسنس و امکانات فعال این ربات)"


def run(ctx):
    bot = ctx["bot"]
    uid = ctx["uid"]
    state = getattr(bot, "license", None)

    if state is None:
        bot.t.user_message(uid, i18n.t("lic_unavailable"))
        return

    lines = [state.status_text()]

    if state.unlicensed and not state.managed:
        lines.append(i18n.t("lic_unrestricted"))
        bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))
        return

    if state.key:
        lines.append(i18n.t("lic_key", licence_key=state.key))

    services = sorted(bot.services)
    lines.append(i18n.t("lic_services", count=len(services), services=", ".join(services) or "—"))

    commands = sorted(bot.commands)
    lines.append(i18n.t("lic_command_count", count=len(commands)))

    operators = set(bot.cfg.get("admins", []) or []) | set(bot.cfg.get("bot_admins", []) or [])
    if operators:
        lines.append(i18n.t("lic_operators", count=len(operators)))

    if state.in_grace():
        lines.append(i18n.t("lic_grace"))

    bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))
