"""ادمین: مصرف منابع خودِ ربات (رم، CPU، thread، مدت اجرا)."""

from core import i18n
from core import resource_stats

NAME = "res"
REQUIRED_ROLE = "admin_bot"
USAGE = "res"


def run(ctx):
    bot = ctx["bot"]
    s = resource_stats.snapshot(start_time=bot.start_time or None)
    na = i18n.t("res_na")
    bot.t.user_message(ctx["uid"], i18n.t(
        "res_info",
        rss="%.1f" % s["rss_mb"] if s["rss_mb"] is not None else na,
        cpu="%.2f" % s["cpu_percent"] if s["cpu_percent"] is not None else na,
        cpu_seconds="%.1f" % s["cpu_seconds"],
        threads=s["threads"],
        time=bot.format_time(s["uptime"]) if s["uptime"] is not None else na,
    ))
