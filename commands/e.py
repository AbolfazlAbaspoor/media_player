from core import i18n

NAME = 'e'
ADMIN_ONLY = False
USAGE = 'e [0.25-3.0]  (no arg = show current speed)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('speed_current', speed=bot.player.speed))
        return
    try:
        speed = float(args[0])
    except ValueError:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands['e']['usage']))
        return
    speed = max(0.25, min(3.0, speed))
    bot.player.speed = speed
    bot.channel_broadcast(i18n.t('speed_set', nickname=ctx['nickname'], speed=speed))
