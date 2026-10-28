"""نمایش صف پخش فعلی (شماره‌ها همون شماره‌هایی هستن که با فرستادن یه عدد تنها می‌شه بهشون پرید)."""

from core import command_helpers, i18n

NAME = ('q', 'queue')
ADMIN_ONLY = False
USAGE = 'q  (show current playlist)'


def run(ctx):
    bot = ctx["bot"]
    tracks = bot.queue.items()
    if not tracks:
        bot.t.user_message(ctx['uid'], i18n.t('nothing_playing'))
        return

    pos = bot.queue.index
    lines = [i18n.t('queue_header', count=len(tracks))]
    for i, track in enumerate(tracks):
        marker = '▶' if i == pos else ' '
        # آیتم‌هایی که هنوز resolve نشدن عنوان دارن (از stub) ولی لینک ندارن؛
        # اگه عنوان هم نداشتن یه نشونه می‌ذاریم تا کاربر بفهمه در راهه، نه خراب.
        label = command_helpers.display_title(track.as_meta())
        if not label:
            label = '...' if not track.failed else i18n.t('queue_item_unavailable')
        lines.append(f"{marker} {i + 1}. {label}")

    # اگه منبع می‌دونه کل چندتاست (پلی‌لیست بزرگ)، بگو چقدرش لود شده.
    if bot.queue.expected_total > len(tracks):
        lines.append(i18n.t('queue_partial', loaded=len(tracks), total=bot.queue.expected_total))

    bot.send_long_text(lambda text: bot.t.user_message(ctx['uid'], text), '\n'.join(lines))
