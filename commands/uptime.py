"""
Example plugin command, showing how to add a new command without touching
bot.py at all. Drop a file like this in commands/ and send 'rs commands'
(no full restart needed) to pick it up.
"""

import time

from core import i18n

NAME = "uptime"
ADMIN_ONLY = False
USAGE = "uptime"

def run(ctx):
    bot = ctx["bot"]
    elapsed = time.time() - bot.start_time
    bot.t.user_message(ctx["uid"], i18n.t("uptime_info", time=bot.format_time(elapsed)))
