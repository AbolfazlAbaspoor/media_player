# commands/dl.py
"""dl: local-cache-aware download + upload, with separate cleanup timers
for the channel copy (shared or per-bot) and the local downloads folder
(always per-bot)."""

import os
import time

from core import command_helpers, i18n
from core import logging_setup
from core import scheduler

NAME = 'dl'
ADMIN_ONLY = False
USAGE = 'dl [format] [bitrate]  (e.g. "dl mp3 320"; either/both optional, any order)'


def _format_eta(seconds):
    if not seconds or seconds <= 0:
        return '?'
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}" if minutes else f"{secs}s"


def _parse_format_args(bot, args):
    """
    آرگومان‌های 'dl' رو (به هر ترتیبی) به (audio_format, audio_quality)
    تشخیص می‌ده -- هرکدوم که ندی، پیش‌فرض خودِ ربات جاش می‌شینه.
    برمی‌گردونه: (audio_format, audio_quality, error_message یا None)
    """
    audio_format = None
    audio_quality = None
    for arg in args:
        low = arg.lower()
        if low in bot.download_allowed_formats:
            if audio_format is not None:
                return None, None, i18n.t('download_format_ambiguous', arg=arg)
            audio_format = low
        elif arg.isdigit():
            if audio_quality is not None:
                return None, None, i18n.t('download_format_ambiguous', arg=arg)
            audio_quality = arg
        else:
            return None, None, i18n.t('download_format_unknown', arg=arg, formats=', '.join(bot.download_allowed_formats))
    return audio_format or bot.download_default_format, audio_quality or bot.download_default_quality, None


def _schedule_channel_removal(bot, channel_id, filename, key):
    """
    حذف نسخه‌ی آپلودشده از کانال، بعد از مدت تنظیم‌شده.

    از زمان‌بند مشترک استفاده می‌شه نه threading.Timer: هر Timer یه ترد
    کامل سیستم‌عامله که تا ساعت‌ها فقط می‌خوابه (توضیح توی
    core/scheduler.py).
    """
    minutes = bot.dl_auto_remove_minutes_effective()
    if not minutes or minutes <= 0:
        return

    def _remove():
        try:
            bot.t.delete_file(channel_id, filename)
        except Exception:
            logging_setup.log_debug(f"auto-removing uploaded file {filename!r} from channel failed")
        with bot.download_lock:
            bot.uploaded_tracks.pop(key, None)

    scheduler.schedule(minutes * 60, _remove)


def run(ctx):
    bot = ctx["bot"]
    meta = command_helpers.current_track_meta(bot, ctx)
    if meta is None:
        return
    if not command_helpers.is_downloadable(meta):
        bot.t.user_message(ctx['uid'], i18n.t('download_paid_refused'))
        return
    source_url = meta.get('public_url')
    if not source_url:
        bot.t.user_message(ctx['uid'], i18n.t('download_no_source'))
        return

    audio_format, audio_quality, error = _parse_format_args(bot, ctx['args'])
    if error:
        bot.t.user_message(ctx['uid'], error)
        return

    channel_id = bot.t.get_user_info()["channel_id"]
    # فرمت/کیفیت هم بخشی از کلید یکتاست: دانلود همون لینک با فرمت دیگه
    # باید یه فایل/آپلود جدا حساب بشه، نه اینکه به‌اشتباه "قبلاً آپلود
    # شده" اعلام بشه.
    key = (channel_id, source_url, audio_format, audio_quality)

    with bot.download_lock:
        existing = bot.uploaded_tracks.get(key)
        active = bot.download_state['active']
        stage = bot.download_state['stage']
        percent = bot.download_state.get('percent')
        eta = bot.download_state.get('eta_seconds')

    if existing:
        try:
            files = bot.t.list_channel_files(channel_id)
        except Exception:
            logging_setup.log_debug(f"listing channel files for channel {channel_id} failed")
            files = []
        if any(f['filename'] == existing['filename'] for f in files):
            bot.t.user_message(ctx['uid'], i18n.t('download_already_uploaded', filename=existing['filename']))
            return
        with bot.download_lock:
            bot.uploaded_tracks.pop(key, None)

    if active:
        stage_key = 'download_stage_uploading' if stage == 'uploading' else 'download_stage_downloading'
        if percent is not None:
            bot.t.user_message(ctx['uid'], i18n.t(
                'download_busy_progress', stage=i18n.t(stage_key), percent=percent, eta=_format_eta(eta),
            ))
        else:
            bot.t.user_message(ctx['uid'], i18n.t('download_busy', stage=i18n.t(stage_key)))
        return

    with bot.download_lock:
        bot.download_state = {
            'active': True, 'stage': 'downloading', 'source_url': source_url,
            'channel_id': channel_id, 'requested_by': ctx['username'], 'started_at': time.time(),
            'percent': None, 'eta_seconds': None, 'transfer_id': None,
        }

    filepath = None
    try:
        # ۱: اول چک کن این لینک با همین فرمت/کیفیت از قبل توی پوشه‌ی
        # downloads خودِ همین ربات هست یا نه
        filepath = bot.find_cached_download(source_url, audio_format, audio_quality)
        if filepath:
            bot.channel_broadcast(i18n.t('download_using_cached', nickname=ctx['nickname']))
        else:
            bot.channel_broadcast(i18n.t(
                'download_started_format', nickname=ctx['nickname'], format=audio_format, quality=audio_quality,
            ))
            logging_setup.set_operation(
                f"downloading '{source_url}' as {audio_format}/{audio_quality} for upload (requested by {ctx['username']})"
            )
            filepath = bot.download_track(source_url, audio_format, audio_quality)

        with bot.download_lock:
            bot.download_state['stage'] = 'uploading'
            bot.download_state['percent'] = None
            bot.download_state['eta_seconds'] = None

        transfer_id = bot.t.upload_file(filepath, chanid=channel_id)
        with bot.download_lock:
            bot.download_state['transfer_id'] = transfer_id
        filename = os.path.basename(filepath)

        with bot.download_lock:
            bot.uploaded_tracks[key] = {'filename': filename, 'uploaded_at': time.time()}

        _schedule_channel_removal(bot, channel_id, filename, key)
        # پاک‌سازی پوشه‌ی downloads اینجا زمان‌بندی نمی‌شه: یه جاروکش
        # دوره‌ای توی bot.py بر اساس *تاریخ فایل* کار می‌کنه، که برخلاف
        # تایمر، با ری‌استارت ربات هم از بین نمی‌ره (قبلاً هر ری‌استارت
        # یعنی فایل‌های قبلی برای همیشه روی دیسک می‌موندن).

        bot.channel_broadcast(i18n.t('download_uploaded', nickname=ctx['nickname']))
    except Exception:
        logging_setup.log_exception(f"dl command failed for '{source_url}'")
        bot.t.user_message(ctx['uid'], i18n.t('download_failed'))
        # اگه دانلود خودش fail شده باشه (نه آپلود)، فایل ناقص/نامعتبر رو نگه نداریم
        try:
            if filepath and os.path.exists(filepath) and os.path.getsize(filepath) == 0:
                os.remove(filepath)
        except Exception:
            logging_setup.log_debug("removing empty/failed download file failed")
    finally:
        logging_setup.set_operation('idle')
        with bot.download_lock:
            bot.download_state = {
                'active': False, 'stage': None, 'source_url': None,
                'channel_id': None, 'requested_by': None, 'started_at': None,
                'percent': None, 'eta_seconds': None, 'transfer_id': None,
            }
