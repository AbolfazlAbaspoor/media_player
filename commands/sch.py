"""
پخشِ زمان‌بندی‌شده -- فقط ادمین (admin_bot یا بالاتر).

    sch add HH:MM [mon,wed,fri | weekdays | weekends | daily] <جستجو | لینک | sf N>
    sch list
    sch del <n>

ساعت، ساعتِ محلیِ سیستمِ ربات است. منطق و توضیح کامل توی
core/scheduled_play.py؛ این فایل فقط پوسته‌ی دستوره. لایسنس: قابلیتِ
cap_schedule (licensing/catalog.py).
"""

from core import i18n
from core import scheduled_play

NAME = 'sch'
REQUIRED_ROLE = "admin_bot"
USAGE = 'sch add HH:MM [mon,wed,..|weekdays|weekends|daily] <search | link | sf N>  |  sch list  |  sch del <n>  (scheduled playback, server local time)'


def _reply(bot, ctx, key, **kwargs):
    bot.t.user_message(ctx["uid"], i18n.t(key, **kwargs))


def run(ctx):
    bot = ctx["bot"]
    args = ctx.get("args") or []
    action = args[0].lower() if args else ""

    if action == "add":
        try:
            hour, minute, days, target = scheduled_play.parse_add(args[1:])
            number, entry = scheduled_play.add(bot, ctx, hour, minute, days, target)
        except scheduled_play.ScheduleError as e:
            _reply(bot, ctx, e.key, **e.kwargs)
            return
        _reply(bot, ctx, "sch_added", number=number, when=scheduled_play.describe_when(entry),
               target=scheduled_play.describe_target(entry))
        return

    if action == "list":
        lines = scheduled_play.list_lines(bot)
        if not lines:
            _reply(bot, ctx, "sch_list_empty")
            return
        bot.send_long_text(lambda text: bot.t.user_message(ctx["uid"], text),
                           i18n.t("sch_list_header") + "\n" + "\n".join(lines))
        return

    if action in ("del", "rm", "remove") and len(args) == 2 and args[1].isdigit():
        if scheduled_play.delete(bot, int(args[1])):
            _reply(bot, ctx, "sch_deleted", number=int(args[1]))
        else:
            _reply(bot, ctx, "sch_bad_number")
        return

    _reply(bot, ctx, "sch_usage")
