"""
حالتِ «آهنگ تموم شد» -- نه این‌که سرچ/پلی‌لیست چندتا نتیجه بگیره یا نه
(اون همیشه رشد می‌کنه، صرف‌نظر از این مُد -- core/trackqueue.py، core/
command_helpers.py). فقط تعیین می‌کنه بعد از پایانِ طبیعیِ یه آهنگ چی بشه:

    1 single           -> پخش متوقف می‌شه (n/b دستی هنوز کار می‌کنه)
    2 playlist         -> آیتم بعدیِ صف پخش می‌شه (پیش‌فرض)
    3 repeat_track     -> همون آهنگ از اول تکرار می‌شه
    4 repeat_playlist  -> بعد از آخرین آیتم، از اول صف شروع می‌شه
"""

from core import i18n

NAME = 'm'
ADMIN_ONLY = False
USAGE = ('m [mode name or number]  (what happens when a track ends: '
         '1 single, 2 playlist, 3 repeat_track, 4 repeat_playlist -- no arg = show current mode)')

def run(ctx):
    bot = ctx["bot"]
    args = ctx['args']
    if not args:
        bot.t.user_message(ctx['uid'], i18n.t('current_mode', mode=bot.playback_modes[bot.playback_mode], number=bot.playback_mode))
        return
    query = ' '.join(args)
    mode_num = bot.resolve_mode(query)
    if mode_num is None:
        options = ', '.join((f'{n} ({name})' for n, name in bot.playback_modes.items()))
        bot.t.user_message(ctx['uid'], i18n.t('mode_not_found', options=options))
        return
    bot.playback_mode = mode_num
    # صفِ فعلی هم همین الان به‌روز بشه، نه فقط دفعه‌ی بعدی‌ای که یه
    # سرچ/لینک/پلی‌لیستِ تازه bot.queue.mode رو از bot.playback_mode
    # می‌خونه (bot.py::load_and_play). بدون این، تغییرِ m وسطِ پخش هیچ
    # اثری نداشت تا یه پخشِ تازه شروع بشه -- دقیقاً باگی که کاربر گزارش داد.
    if getattr(bot, "queue", None) is not None:
        bot.queue.mode = mode_num
    bot.channel_broadcast(i18n.t('mode_changed', nickname=ctx['nickname'], mode=bot.playback_modes[mode_num]))
