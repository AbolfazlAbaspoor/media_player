"""Toggle whether the youtube service uses cookies.txt (mirrors 'up' for proxy)."""

from core import command_helpers, i18n

NAME = "ck"
REQUIRED_ROLE = "admin_server"
USAGE = "ck [true|false]"

def run(ctx):
    bot = ctx["bot"]
    args = ctx["args"]

    if not args:
        enabled = not bot.cfg.get("cookies", {}).get("enabled", True)
    elif args[0].lower() in ("true", "false"):
        enabled = args[0].lower() == "true"
    else:
        bot.t.user_message(ctx["uid"], i18n.t("usage_generic", usage=bot.commands["ck"]["usage"]))
        return

    bot.cfg.setdefault("cookies", {})["enabled"] = enabled
    bot.save_config()

    state = i18n.t("state_enabled") if enabled else i18n.t("state_disabled")
    command_helpers.notify(bot, ctx, "cookies_toggled", state=state, nickname=ctx["nickname"])
