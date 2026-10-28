"""
قفل/بازکردن یه دستور عمومی برای کاربرهای عادی (فقط admin_bot به بالا
می‌تونه قفل/باز کنه؛ خودِ دستورِ قفل‌شده هم بعدش فقط برای admin_bot به
بالا اجرا می‌شه، صرف‌نظر از REQUIRED_ROLE اصلیش).

Usage:
    lock <command>     -> قفل می‌کنه (کاربران عادی دیگه نمی‌تونن اجراش کنن)
    unlock <command>   -> باز می‌کنه
    lock / unlock       -> بدون آرگومان: لیست دستورات قفل‌شده رو نشون می‌ده
"""

from core import i18n

NAME = ('lock', 'lck', 'unlock', 'unlck')
REQUIRED_ROLE = 'admin_bot'
USAGE = 'lock/unlock <command>  (block/allow a command for non-admins; no arg = list locked)'

# دستورهایی که هیچ‌وقت نباید قفل بشن (خودشون رو یا اتفاقی همه‌ی دسترسی رو نمی‌بندن).
_NEVER_LOCK = {'lock', 'lck', 'unlock', 'unlck', 'help', 'h'}


def run(ctx):
    bot = ctx['bot']
    args = ctx['args']
    is_lock = ctx['cmd'] in ('lock', 'lck')
    locked = bot.cfg.setdefault('locked_commands', [])

    if not args:
        if not locked:
            bot.t.user_message(ctx['uid'], i18n.t('no_locked_commands'))
        else:
            bot.t.user_message(ctx['uid'], i18n.t('locked_commands_header', commands=', '.join(sorted(locked))))
        return

    target = args[0].lower().lstrip('/')
    target = bot.aliases.get(target, target)

    if target not in bot.commands:
        bot.t.user_message(ctx['uid'], i18n.t('unknown_command'))
        return

    if target in _NEVER_LOCK:
        bot.t.user_message(ctx['uid'], i18n.t('cannot_lock_command', command=target))
        return

    if is_lock:
        if target in locked:
            bot.t.user_message(ctx['uid'], i18n.t('command_already_locked', command=target))
            return
        locked.append(target)
        bot.save_config()
        bot.channel_broadcast(i18n.t('command_locked', nickname=ctx['nickname'], command=target))
    else:
        if target not in locked:
            bot.t.user_message(ctx['uid'], i18n.t('command_already_unlocked', command=target))
            return
        locked.remove(target)
        bot.save_config()
        bot.channel_broadcast(i18n.t('command_unlocked', nickname=ctx['nickname'], command=target))
