"""تغییر نسبی صدا (پایین). برای تنظیم مطلق از v استفاده کن."""

from core import i18n

NAME = 'vd'
ADMIN_ONLY = False
USAGE = 'vd [step]  (default step = 5)'


def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    step = int(args[0]) if args and args[0].lstrip('-').isdigit() else 5
    vol = max(0, min(100, bot.player.volume - step))
    bot.player.volume = vol
    bot.cfg.setdefault('last_state', {})['volume'] = vol
    bot.save_config()
    bot.channel_broadcast(i18n.t('volume_set', nickname=ctx['nickname'], volume=vol))
