"""Migrated from bot.py's built-in commands."""

from core import i18n

NAME = 'j'
ADMIN_ONLY = False
USAGE = 'j <min> | j <min> <sec> | j <h> <m> <s>  (no number = restart from 0)'


def _target_seconds(parts):
    """
    ورودی رو دقیقاً همون‌طوری که USAGE می‌گه تفسیر می‌کنه:
        یک عدد   -> دقیقه
        دو عدد   -> دقیقه و ثانیه
        سه عدد   -> ساعت و دقیقه و ثانیه
    """
    if not parts:
        return 0
    if len(parts) == 1:
        return parts[0] * 60
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def run(ctx):
    bot = ctx["bot"]
    if bot.player.current_url is None:
        bot.t.user_message(ctx['uid'], i18n.t('nothing_playing'))
        return

    parts = [int(x) for x in ctx['args'] if x.isdigit()][:3]
    target = _target_seconds(parts)

    duration = bot.player.duration_seconds
    # duration=None یعنی استریم زنده (طولش معلوم نیست)؛ اون‌جا نباید جلوی
    # پرش رو بگیریم، چون هیچ‌وقت هیچ عددی از "طول" کمتر نیست.
    if duration is not None and target > duration:
        bot.t.user_message(ctx['uid'], i18n.t('time_exceeds'))
        return

    bot.player.seek_to(target)
    bot.channel_broadcast(i18n.t('jumped', nickname=ctx['nickname'], time=bot.format_time(target)))
