"""
یه رپر ساده و کوچیک روی mpv.py (کتابخونه‌ی خام python-mpv که کل API لیب‌mpv
رو با ctypes بایند می‌کنه). هدف: هیچ پروژه‌ای که می‌خواد از mpv برای پخش
استفاده کنه، لازم نباشه بره مستندات کامل libmpv/python-mpv رو بخونه؛ فقط
یه شیء Player می‌سازه و با متدها/پراپرتی‌های ساده و اسم‌دار کار می‌کنه.

فلسفه‌ی طراحی (شبیه‌ ttbot.py برای TeamTalk):
  - mpv.py (فایل خام) دست‌نخورده می‌مونه؛ این فایل فقط روش لایه می‌کشه.
  - هر چیزی که این پروژه (یا پروژه‌ی بعدی) واقعاً لازم داره (پخش، صف، پاز/
    ریزیوم، سیک، ولوم، دستگاه خروجی، پروکسی، نرمال‌سازی صدا، وضعیت فعلی)
    به یه اسم واضح و ساده map می‌شه.
  - چیزی که اینجا نیست ولی لازم شد، همیشه از طریق self.raw (خودِ شیء
    python-mpv) در دسترسه؛ یعنی رپر هیچ‌وقت جلوی دسترسی کامل رو نمی‌گیره،
    فقط حالت رایج رو راحت می‌کنه.

استفاده‌ی نمونه:
    from core.mpv.player import Player

    player = Player(log_handler=my_log_handler)
    player.set_output_device("پیش‌فرض")
    player.play("https://example.com/song.mp3")
    player.enqueue("https://example.com/song2.mp3")

    player.pause()
    player.resume()
    player.toggle_pause()

    if player.has_next:
        player.next()

    print(player.now_playing_title)
"""

from .mpv import MPV


def _debug(message):
    """
    ثبت یه خطای «ریز» بدون شکستن فلسفه‌ی مستقل بودن این رپر: اگه پروژه‌ی
    میزبان core.logging_setup داشته باشه، خطا اونجا (debug.log) ثبت می‌شه؛
    اگه این رپر جای دیگه‌ای بدون اون پروژه استفاده بشه، بی‌سروصدا رد می‌شه.
    """
    try:
        from core import logging_setup
        logging_setup.log_debug(f"[player] {message}")
    except Exception:
        pass


class Player:
    """
    یه پخش‌کننده‌ی صوتی/تصویری ساده، بر پایه‌ی libmpv.

    نکته: پیش‌فرض vo="null" هست (بدون خروجی تصویری)، چون این رپر اصلش
    برای بات‌های صوتیه -- و در این حالت ترک ویدیو اصلاً باز نمی‌شه
    (vid="no")، پس هیچ CPU ای برای دیکود تصویری که کسی نمی‌بینه هدر
    نمی‌ره. اگه یه پروژه‌ی دیگه به تصویر هم نیاز داشت، با
    Player(video_output="gpu") (یا هر vo دیگه‌ای که libmpv پشتیبانی می‌کنه)
    قابل تغییره و اون‌موقع ویدیو دوباره فعال می‌شه.
    """

    # سقف حافظه‌ی بافر خودِ mpv. پیش‌فرض‌های mpv برای یه پلیر دسکتاپ تنظیم
    # شدن (ده‌ها مگابایت به‌ازای هر نمونه)؛ برای رباتی که قراره چندتاش
    # هم‌زمان روی یه سیستم ضعیف اجرا بشه، این مقدارها هم کافی‌ان هم خیلی
    # کم‌مصرف‌تر.
    DEFAULT_DEMUXER_MAX_BYTES = "20MiB"
    DEFAULT_DEMUXER_MAX_BACK_BYTES = "5MiB"
    DEFAULT_NETWORK_TIMEOUT = 30
    # روی شبکه‌های ناپایدار (پروکسی‌هایی که گاهی وسط استریم TLS/I-O قطع
    # می‌کنن)، بدون این گزینه‌ها mpv فقط یه بار خیلی سریع (۰ ثانیه) تلاش
    # می‌کنه reconnect کنه و اگه نشد کلاً استریم رو ول می‌کنه (idle می‌شه).
    # این‌ها مستقیم به لایه‌ی شبکه‌ی ffmpeg (libavformat) پاس داده می‌شن و
    # باعث می‌شن با backoff واقعی چندبار تلاش کنه، نه فقط یک‌بار آنی.
    #
    # حواست باشه: reconnect / reconnect_at_eof / reconnect_streamed *نباید*
    # باشن. پلی‌لیستِ m3u8 توی لایو (یوتیوب و بقیه) هر چند ثانیه دوباره لود
    # می‌شه و هر بار به EOF می‌رسه؛ این سه تا اون EOF عادی رو «قطعی» حساب
    # می‌کردن و لایو هیچ‌وقت شروع نمی‌شد (روی لایو واقعی تست شد). reconnect
    # فقط روی خطای واقعیِ شبکه کافیه.
    DEFAULT_RECONNECT_OPTS = "reconnect_on_network_error=1,reconnect_delay_max=5"

    # آیا mpv اجازه داره خودش yt-dlp صدا بزنه؟ پیش‌فرض: نه.
    #
    # همه‌ی لینک‌هایی که این پروژه به mpv می‌ده از قبل resolve شدن (لینک
    # مستقیم استریم یا فایل مستقیم). پس هوک ytdl خودِ mpv فقط وقتی فعال
    # می‌شه که یه جایی چیزی اشتباه رفته باشه -- و اون‌موقع بدترین کار ممکن
    # رو می‌کنه: یه پروسه‌ی yt-dlp جدا spawn می‌کنه که **پروکسی و کوکی ما
    # رو نداره**، یعنی یه درخواست لختِ اضافه به یوتیوب از همون IP. دقیقاً
    # همون الگویی که باعث «Sign in to confirm you're not a bot» می‌شه.
    #
    # با خاموش‌بودنش، اون حالت به‌جای یه درخواست مشکوکِ پنهان، یه خطای
    # واضح می‌شه. اگه روزی لینکی داشتی که واقعاً به ytdl خودِ mpv نیاز
    # داشت، توی shared_config.json بذار: "player": {"allow_mpv_ytdl": true}
    DEFAULT_ALLOW_MPV_YTDL = False

    def __init__(
        self,
        video_output="null",
        log_handler=None,
        log_level="warn",
        normalize_audio=False,
        proxy_url=None,
        demuxer_max_bytes=None,
        demuxer_max_back_bytes=None,
        network_timeout=None,
        allow_mpv_ytdl=None,
        **extra_options,
    ):
        options = {
            "vo": video_output,
            # سقف بافر (RAM). بدون این، هر نمونه‌ی mpv می‌تونه ده‌ها مگابایت
            # برای بافر جلو/عقب بگیره.
            "demuxer_max_bytes": demuxer_max_bytes or self.DEFAULT_DEMUXER_MAX_BYTES,
            "demuxer_max_back_bytes": demuxer_max_back_bytes or self.DEFAULT_DEMUXER_MAX_BACK_BYTES,
            # اگه یه استریم شبکه قطع بشه ولی TCP باز بمونه، بدون این mpv
            # می‌تونه تا ابد منتظر بمونه و ربات «هنگ‌کرده» به‌نظر برسه.
            "network_timeout": network_timeout or self.DEFAULT_NETWORK_TIMEOUT,
            # reconnect واقعی با backoff به‌جای فقط یه تلاش آنی (بالا توضیح داده شده).
            "stream_lavf_o": self.DEFAULT_RECONNECT_OPTS,
        }

        # هوک ytdl خودِ mpv (توضیح کامل بالای DEFAULT_ALLOW_MPV_YTDL).
        if allow_mpv_ytdl is None:
            allow_mpv_ytdl = self.DEFAULT_ALLOW_MPV_YTDL
        options["ytdl"] = bool(allow_mpv_ytdl)

        # vo="null" یعنی تصویر نمایش داده نمی‌شه، ولی mpv همچنان ویدیو رو
        # *دیکود* می‌کنه -- که برای استریم‌های تصویری (کانال‌های تلویزیونی،
        # m3u8، ریلز) یعنی هدر رفتن یه هسته‌ی کامل CPU بدون هیچ فایده‌ای.
        # vid="no" کلاً ترک ویدیو رو باز نمی‌کنه. فقط وقتی اعمال می‌شه که
        # واقعاً خروجی تصویری نخواسته باشیم.
        if video_output == "null":
            options["vid"] = "no"

        options.update(extra_options)

        self.raw = MPV(log_handler=log_handler, loglevel=log_level, **options)
        self.set_normalize(normalize_audio)
        if proxy_url:
            self.set_proxy(proxy_url)

    def __enter__(self):
        """Context manager entry: return self for 'with' statements."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit: ensure cleanup on exit."""
        self.terminate()
        return False

    def __del__(self):
        """Fallback cleanup if player object is garbage collected without context manager."""
        try:
            if hasattr(self, 'raw') and self.raw is not None:
                self.terminate()
        except Exception:
            pass

    def play(self, url):
        """پلی‌لیست فعلی رو کنار می‌ذاره و همین یه لینک رو فوراً پخش می‌کنه."""
        self.raw.play(url)

    def stop(self):
        """پخش رو کامل متوقف می‌کنه (پلی‌لیست هم خالی می‌شه)."""
        try:
            self.raw.stop()
        except Exception:
            _debug("stop() failed")

    def terminate(self):
        """خودِ پروسه‌ی mpv رو می‌بنده. بعد از این، شیء دیگه قابل‌استفاده نیست."""
        try:
            self.raw.terminate()
        except Exception:
            _debug("terminate() failed")

    @property
    def is_paused(self):
        return bool(self.raw.pause)

    @is_paused.setter
    def is_paused(self, value):
        self.raw.pause = bool(value)

    def pause(self):
        self.raw.pause = True

    def resume(self):
        self.raw.pause = False

    def toggle_pause(self):
        self.raw.pause = not self.raw.pause
        return self.is_paused

    def enqueue(self, url):
        """یه لینک به انتهای پلی‌لیست فعلی اضافه می‌کنه (پخش فعلی رو قطع نمی‌کنه)."""
        self.raw.playlist_append(url)

    @property
    def queue(self):
        """لیست خام آیتم‌های پلی‌لیست فعلی (هر آیتم یه dict با کلید 'filename')."""
        return list(self.raw.playlist)

    @property
    def queue_length(self):
        return len(self.queue)

    @property
    def queue_index(self):
        """ایندکس آیتم فعلی توی پلی‌لیست (0-پایه)؛ اگه چیزی در حال پخش نیست None."""
        return self.raw.playlist_pos

    @property
    def has_next(self):
        idx = self.queue_index
        return idx is not None and idx + 1 < self.queue_length

    @property
    def has_previous(self):
        idx = self.queue_index
        return idx is not None and idx > 0

    @property
    def is_at_last_item(self):
        """
        True اگه یه پلی‌لیست چندآیتمی در جریانه و همین الان روی آخرین
        آیتمشیم (برای رفتاری مثل «وقتی به آخر صف رسیدیم بازم بیشتر لود
        کن» مفیده).
        """
        return self.queue_length > 1 and self.queue_index == self.queue_length - 1

    def next(self):
        """
        می‌ره سراغ آیتم بعدی پلی‌لیست. True برمی‌گردونه اگه واقعاً جابه‌جا
        شده باشه (یعنی آیتم بعدی وجود داشته)، وگرنه False (از قبل آخرین
        آیتم بودیم، یا آیتم فعلی/بعدی لود نشده بود و خودِ mpv کامند رو رد کرد).
        """
        before = self.queue_index
        try:
            self.raw.playlist_next()
        except Exception:
            _debug("playlist_next() failed")
            return False
        return self.queue_index != before

    def previous(self):
        """مثل next() ولی برای آیتم قبلی."""
        before = self.queue_index
        try:
            self.raw.playlist_prev()
        except Exception:
            _debug("playlist_prev() failed")
            return False
        return self.queue_index != before

    def jump_to(self, index):
        """
        می‌ره سراغ آیتم شماره‌ی index (0-پایه) توی پلی‌لیست. اگه index خارج
        از محدوده باشه ValueError می‌ده. True/False برمی‌گردونه بسته به
        اینکه خودِ mpv واقعاً پرید یا کامند رو رد کرد.
        """
        if index < 0 or index >= self.queue_length:
            raise ValueError(f"Playlist index {index} out of range (0..{self.queue_length - 1}).")
        try:
            self.raw.playlist_play_index(index)
        except Exception:
            _debug(f"playlist_play_index({index}) failed")
            return False
        return True

    def clear_queue(self):
        """کل صف پلی‌لیست رو خالی می‌کنه (بدون این‌که خودِ پخش فعلی رو استاپ کنه، مگر این‌که خودت هم stop() رو صدا بزنی)."""
        try:
            self.raw.playlist_clear()
        except Exception:
            _debug("playlist_clear() failed")

    @property
    def current_url(self):
        """آدرس/مسیر فایلی که الان بارگذاری شده (یا None اگه چیزی در حال پخش نیست)."""
        return self.raw.filename

    @property
    def now_playing_title(self):
        """
        عنوان زنده‌ی همون چیزی که mpv خودش تشخیص داده (مثلاً از متادیتای
        ICY رادیوهای آنلاین). ممکنه None باشه، مخصوصاً همون اول بارگذاری.
        """
        return self.raw.media_title

    @property
    def is_buffering(self):
        """True یعنی mpv داره بافر می‌کنه/چیزی برای پخش نداره (core idle)."""
        return bool(self.raw.core_idle)

    @property
    def is_playing(self):
        """True فقط وقتی چیزی بارگذاری شده، بافر نیست، و پاز هم نیست."""
        return self.current_url is not None and not self.is_buffering and not self.is_paused

    @property
    def position_seconds(self):
        """ثانیه‌ی فعلی پخش (None اگه مشخص نیست)."""
        return self.raw.time_pos

    @property
    def duration_seconds(self):
        """طول کل فایل فعلی به ثانیه (None اگه مشخص نیست، مثلاً استریم زنده)."""
        return self.raw.duration

    def stream_info(self):
        """
        مشخصاتِ فنیِ چیزی که mpv همین الان باز کرده (کدک، بیت‌ریت، قالب،
        رزولوشن) با همون اسم‌های مدل متادیتای مشترک (core/track_meta.py).
        برای لینک مستقیم/رادیو/IPTV که هیچ سرویسی متادیتا نداده. هر
        مقداری که mpv نداره حذف می‌شه.
        """
        out = {}
        for key, prop in (("acodec", "audio_codec_name"), ("vcodec", "video_format"),
                          ("ext", "file_format"), ("abr", "audio_bitrate"),
                          ("width", "width"), ("height", "height")):
            try:
                value = getattr(self.raw, prop)
            except Exception:
                continue
            if value not in (None, "", 0):
                out[key] = value
        if isinstance(out.get("abr"), (int, float)):
            out["abr"] = round(out["abr"] / 1000.0, 1)  # mpv بیت‌بر‌ثانیه می‌ده
        return out

    def seek_relative(self, seconds):
        """seconds مثبت = جلو، منفی = عقب."""
        self.raw.seek(seconds, reference="relative")

    def seek_to(self, seconds):
        """رفتن مستقیم به ثانیه‌ی مشخص از فایل."""
        self.raw.seek(seconds, reference="absolute")

    @property
    def volume(self):
        """۰ تا ۱۰۰."""
        return self.raw.volume

    @volume.setter
    def volume(self, value):
        self.raw.volume = max(0, min(100, value))

    def list_output_devices(self):
        """[{'name':..., 'description':...}, ...] همه‌ی دستگاه‌های خروجی موجود."""
        return list(self.raw.audio_device_list)

    def set_output_device(self, name):
        """
        دستگاه خروجی رو با اسم (name) دقیقش تنظیم می‌کنه (نه description).
        برای گرفتن اسم دقیق، از list_output_devices() استفاده کن.
        """
        self.raw.audio_device = name

    def set_output_device_by_index(self, index):
        """مثل set_output_device ولی با ایندکس (0-پایه) توی خروجی list_output_devices()."""
        devices = self.list_output_devices()
        if index < 0 or index >= len(devices):
            raise ValueError(f"Output device index {index} out of range (0..{len(devices) - 1}).")
        self.set_output_device(devices[index]["name"])

    # یکسان‌سازی بلندی صدا (EBU R128). قبلاً اینجا "dynaudnorm" خام بود که
    # mpv اصلاً اعمالش نمی‌کرد (تست: خروجی با خاموش یکی بود) -- فیلترهای
    # ffmpeg باید از مسیر lavfi بدن.
    #
    # صادقانه: برای یه استریمِ زنده (لایو/لینکی که از قبل نمی‌شناسیمش)،
    # تنها ابزارِ واقعی برای «حدودِ یکسان کردنِ بلندی» loudnorm در حالتِ
    # تک‌گذر (dynamic)ه -- خودِ مستندِ ffmpeg هم می‌گه این حالت نسبت به
    # دوگذر (که نیاز به تحلیلِ کاملِ فایل از قبل داره و برای استریم ممکن
    # نیست) دقتِ کمتر و احتمالِ اثرگذاریِ شنیداریِ (gain-riding/pumping)
    # بیشتری داره -- این یه محدودیتِ ذاتیِ خودِ ابزاره، نه یه باگ اینجا.
    # dynaudnorm امتحان شد و رد شد: هدفش تراز کردنِ اوجِ سیگنال به peak
    # (پیش‌فرض 0.95)ه، نه بلندیِ ادراک‌شده -- روی دو فایل با بلندیِ خیلی
    # متفاوت، فاصله‌شون رو عملاً کم نکرد (اندازه‌گیری شد).
    #
    # I=-14 (به‌جای -16): نزدیک‌ترِ به چیزی که خیلی از پلتفرم‌ها (یوتیوب و
    # امثالش) از قبل باهاش پخش می‌کنن، پس برای محتوایی که از قبل نرمال
    # حساب می‌شه loudnorm کارِ کمتری برای انجام‌دادن داره (گینِ کمتر = اثرِ
    # شنیداریِ کمتر) و فقط موردهای واقعاً پرت (خیلی بلند/خیلی آروم) اصلاح
    # جدی می‌گیرن. LRA=11 (به‌جای پیش‌فرضِ ffmpeg=7) عمداً شل‌تره تا
    # دینامیکِ داخلیِ خودِ آهنگ کمتر فشرده بشه.
    NORMALIZE_FILTER = "lavfi=[loudnorm=I=-14:LRA=11:TP=-1.5]"

    def set_normalize(self, enabled):
        """یکسان‌سازی بلندی صدا بین آهنگ‌های مختلف رو روشن/خاموش می‌کنه."""
        try:
            self.raw.af = self.NORMALIZE_FILTER if enabled else ""
        except Exception:
            _debug("set_normalize() failed")

    def set_proxy(self, url):
        """پروکسی HTTP خودِ mpv (برای خودِ استریم، نه فقط جستجو) رو تنظیم می‌کنه. url خالی/None یعنی خاموش."""
        try:
            self.raw.http_proxy = url or ""
        except Exception:
            _debug("set_proxy() failed")

    def remove_from_queue(self, index="current"):
        """یه آیتم رو از پلی‌لیست حذف می‌کنه (پیش‌فرض: آیتم فعلی)."""
        self.raw.playlist_remove(index)

    def move_in_queue(self, from_index, to_index):
        """جابه‌جا کردن یه آیتم از یه ایندکس به ایندکس دیگه توی پلی‌لیست."""
        self.raw.playlist_move(from_index, to_index)

    def shuffle_queue(self):
        """ترتیب پلی‌لیست رو رندوم می‌کنه (خودِ ایندکس آیتم فعلی حفظ می‌شه)."""
        self.raw.playlist_shuffle()

    def unshuffle_queue(self):
        """ترتیب اصلی (قبل از shuffle) رو برمی‌گردونه."""
        try:
            self.raw.playlist_unshuffle()
        except Exception:
            _debug("playlist_unshuffle() failed")

    @property
    def is_muted(self):
        return bool(self.raw.mute)

    @is_muted.setter
    def is_muted(self, value):
        self.raw.mute = bool(value)

    def mute(self):
        self.raw.mute = True

    def unmute(self):
        self.raw.mute = False

    @property
    def speed(self):
        """سرعت پخش (۱.۰ = عادی، ۲.۰ = دو برابر، ۰.۵ = نصف)."""
        return self.raw.speed

    @speed.setter
    def speed(self, value):
        self.raw.speed = value

    @property
    def loop_current_track(self):
        """True یعنی فایل فعلی بی‌نهایت تکرار می‌شه (وقتی تموم شد از اول)."""
        return self.raw.loop_file not in (False, "no", None)

    @loop_current_track.setter
    def loop_current_track(self, value):
        self.raw.loop_file = "inf" if value else "no"

    @property
    def loop_queue(self):
        """True یعنی کل پلی‌لیست بی‌نهایت تکرار می‌شه (بعد از آخرین آیتم برمی‌گرده اول)."""
        return self.raw.loop_playlist not in (False, "no", None)

    @loop_queue.setter
    def loop_queue(self, value):
        self.raw.loop_playlist = "inf" if value else "no"

    def add_subtitle(self, url, title=None, language=None):
        """یه فایل/لینک زیرنویس اضافه می‌کنه و فعالش می‌کنه."""
        self.raw.sub_add(url, title=title, lang=language)

    def add_audio_track(self, url, title=None, language=None):
        """یه ترک صوتی جدا (مثلاً دوبله) اضافه می‌کنه و فعالش می‌کنه."""
        self.raw.audio_add(url, title=title, lang=language)

    def take_screenshot(self, path=None, include_subtitles=True):
        """
        یه فریم رو ذخیره می‌کنه. اگه path بدی، مستقیم روی همون مسیر ذخیره
        می‌شه؛ وگرنه خودِ mpv یه اسم پیش‌فرض کنار فایل ویدیو انتخاب می‌کنه.
        """
        includes = "subtitles" if include_subtitles else "video"
        if path:
            self.raw.screenshot_to_file(path, includes=includes)
        else:
            self.raw.screenshot(includes=includes)

    def wait_until_playing(self, timeout=None):
        """بلاک می‌کنه تا پخش واقعاً شروع بشه (یا فایل عوض بشه)."""
        self.raw.wait_for_playback(timeout=timeout)

    def wait_for_event(self, *event_names, timeout=None):
        """بلاک می‌کنه تا یکی از رویدادهای خام mpv (مثل 'end-file', 'idle') اتفاق بیفته."""
        return self.raw.wait_for_event(*event_names, timeout=timeout)

    def on_property_change(self, property_name, handler):
        """
        هر بار که یه پراپرتی خام mpv (مثلاً 'volume', 'pause', 'time-pos')
        تغییر کنه، handler(name, new_value) صدا زده می‌شه.
        """
        self.raw.observe_property(property_name, handler)

    def on_event(self, *event_names):
        """
        دکوریتور: تابع رو برای رویدادهای خام mpv (مثل 'end-file', 'seek')
        ثبت می‌کنه. مثال:
            @player.on_event('end-file')
            def _(event):
                ...
        """
        return self.raw.event_callback(*event_names)

    # --- فصل‌ها (chapters) ---

    @property
    def chapter_count(self):
        """تعداد فصل‌های فایل فعلی (۰ اگه فایل فصل‌بندی نشده باشه)."""
        try:
            chapters = self.raw.chapter_list
            return len(chapters) if chapters else 0
        except Exception:
            return 0

    @property
    def chapter_list(self):
        """لیست خام فصل‌ها (هر کدوم dict با 'title' و 'time")."""
        try:
            return list(self.raw.chapter_list or [])
        except Exception:
            return []

    @property
    def current_chapter(self):
        """ایندکس فصل فعلی (0-پایه)، یا None اگه فایل فصل نداره/چیزی پخش نمی‌شه."""
        try:
            value = self.raw.chapter
            return value if isinstance(value, int) and value >= 0 else None
        except Exception:
            return None

    def seek_chapter(self, index):
        """می‌ره سراغ فصل شماره‌ی index (0-پایه)."""
        try:
            self.raw.chapter = index
            return True
        except Exception:
            _debug(f"seek_chapter({index}) failed")
            return False

    def next_chapter(self):
        """فصل بعدی؛ False اگه فصل بعدی‌ای نبود."""
        try:
            self.raw.command("add", "chapter", 1)
            return True
        except Exception:
            _debug("next_chapter() failed")
            return False

    def previous_chapter(self):
        """فصل قبلی؛ False اگه فصل قبلی‌ای نبود."""
        try:
            self.raw.command("add", "chapter", -1)
            return True
        except Exception:
            _debug("previous_chapter() failed")
            return False

    # --- ترک‌های صوتی/زیرنویس (انتخاب بین ترک‌های موجود، نه اضافه‌کردن جدید) ---

    @property
    def track_list(self):
        """لیست خام تمام ترک‌های فایل فعلی (صدا/زیرنویس/ویدیو)."""
        try:
            return list(self.raw.track_list or [])
        except Exception:
            return []

    @property
    def audio_tracks(self):
        """فقط ترک‌های صوتی (برای فایل‌هایی با چند زبان/چند ترک صدا)."""
        return [t for t in self.track_list if t.get("type") == "audio"]

    @property
    def current_audio_track(self):
        """id ترک صوتی فعال (aid خام mpv)."""
        try:
            return self.raw.aid
        except Exception:
            return None

    def set_audio_track(self, track_id):
        """ترک صوتی فعال رو عوض می‌کنه (id از audio_tracks)."""
        try:
            self.raw.aid = track_id
            return True
        except Exception:
            _debug(f"set_audio_track({track_id}) failed")
            return False

    @property
    def subtitle_tracks(self):
        return [t for t in self.track_list if t.get("type") == "sub"]

    @property
    def current_subtitle_track(self):
        try:
            return self.raw.sid
        except Exception:
            return None

    def set_subtitle_track(self, track_id):
        """ترک زیرنویس فعال رو عوض می‌کنه، یا خاموش می‌کنه (track_id=False)."""
        try:
            self.raw.sid = track_id
            return True
        except Exception:
            _debug(f"set_subtitle_track({track_id}) failed")
            return False

    # --- متادیتا/تگ‌ها ---

    @property
    def metadata(self):
        """دیکشنری تگ‌های فایل فعلی (artist, album, title, icy-title برای رادیوهای زنده، ...)."""
        try:
            return dict(self.raw.metadata or {})
        except Exception:
            return {}

    # --- وضعیت بافر/کش (برای دیباگ/نمایش سلامت اتصال) ---

    @property
    def cache_buffering_percent(self):
        """درصد پر بودن بافر شبکه (۰-۱۰۰)، یا None اگه در دسترس نباشه."""
        try:
            state = self.raw.demuxer_cache_state
            if not state:
                return None
            return state.get("cache-end")
        except Exception:
            return None

    @property
    def is_paused_for_cache(self):
        """True یعنی mpv به‌خاطر خالی بودن بافر شبکه موقتاً خودش پاز کرده (نه کاربر)."""
        try:
            return bool(self.raw.paused_for_cache)
        except Exception:
            return False

    @property
    def cache_seconds(self):
        """مقدار زمانی (ثانیه) از رسانه که همین الان توی بافر جلوتره."""
        try:
            return self.raw.demuxer_cache_time
        except Exception:
            return None

    # --- اکولایزر/فیلترهای صوتی ---

    def set_equalizer(self, bands=None):
        """
        یه اکولایزر ساده‌ی ۱۰-باندی اعمال می‌کنه. bands یه dict اختیاریه
        {frequency_hz: gain_db, ...}؛ اگه None باشه، اکولایزر خاموش می‌شه.
        مثال: player.set_equalizer({60: 5, 310: 3, 6000: -2})
        """
        if not bands:
            self.raw.command("af", "remove", "@eq")
            return
        entries = ":".join(f"equalizer=f={freq}:width_type=o:width=2:g={gain}" for freq, gain in bands.items())
        try:
            self.raw.command("af", "remove", "@eq")
        except Exception:
            pass
        self.raw.command("af", "add", f"@eq:{entries}")

    def get_audio_filters(self):
        """رشته‌ی خام فیلترهای صوتی فعال (af) -- شامل نرمال‌سازی و اکولایزر."""
        try:
            return self.raw.af
        except Exception:
            return ""

    @property
    def audio_delay(self):
        """تأخیر صدا نسبت به تصویر (ثانیه، می‌تونه منفی باشه)."""
        try:
            return self.raw.audio_delay
        except Exception:
            return 0.0

    @audio_delay.setter
    def audio_delay(self, seconds):
        self.raw.audio_delay = seconds

    # --- Replaygain (نرمال‌سازی بلندای صدا بر اساس متادیتای خودِ فایل) ---

    @property
    def replaygain_mode(self):
        """یکی از 'no'/'track'/'album'/'ماکس'."""
        try:
            return self.raw.replaygain
        except Exception:
            return "no"

    @replaygain_mode.setter
    def replaygain_mode(self, mode):
        """mode: 'no', 'track', 'album', یا 'track-fallback'."""
        self.raw.replaygain = mode

    # --- AB-Loop (تکرار یه بازه‌ی مشخص) ---

    def set_ab_loop(self, a_seconds, b_seconds):
        """بین دو نقطه‌ی زمانی (ثانیه) بی‌نهایت لوپ می‌کنه."""
        self.raw.ab_loop_a = a_seconds
        self.raw.ab_loop_b = b_seconds

    def clear_ab_loop(self):
        """AB-loop رو غیرفعال می‌کنه."""
        self.raw.ab_loop_a = "no"
        self.raw.ab_loop_b = "no"

    # ==========================================================================
    # از این به بعد: پوشش کامل mpv.py (ادیت دوم رپر).
    #
    # هدف این بخش خیلی ساده‌ست: هر متد/پراپرتی عمومیِ mpv.py که بالاتر
    # لمس نشده، اینجا یه اسم واضح می‌گیره و مستقیم به self.raw پاس داده
    # می‌شه -- بدون منطق اضافه، بدون ثبت خودکارِ observer/thread جدید (اون‌ها
    # فقط وقتی ثبت می‌شن که خودِ صدازننده صریحاً بخواد). هر چیزی که واقعاً
    # نیاز به دسترسی خام‌تر داره، همیشه از self.raw در دسترسه؛ این متدها
    # فقط راحتش می‌کنن.
    # ==========================================================================

    # --- کامندهای خام و چرخه‌ی زندگی ---

    def run_command(self, name, *args, **kwargs):
        """
        هر کامند خام mpv رو مستقیم اجرا می‌کنه (مثل ``self.raw.command``).
        برای هر چیزی که این رپر هنوز اسم مشخص براش نداره.
        """
        return self.raw.command(name, *args, **kwargs)

    def run_command_string(self, name, *args):
        """نسخه‌ی ساده‌ترِ run_command که مقدار برگشتی نمی‌خواد (رشته‌ی خام کامند)."""
        self.raw.string_command(name, *args)

    def run_command_async(self, name, *args, callback=None, **kwargs):
        """
        نسخه‌ی async کامند خام؛ فوراً برمی‌گرده و یه Future می‌ده (بدون بلاک
        کردن رشته‌ی فعلی روی جواب mpv).
        """
        return self.raw.command_async(name, *args, callback=callback, **kwargs)

    def run_node_command(self, name, *args):
        """مثل run_command ولی decoder سخت‌گیرانه‌تر (strict) برای مقدار برگشتی."""
        return self.raw.node_command(name, *args)

    def run_subprocess(self, command, *args):
        """کامند خام ``run`` (اجرای یه پروسه‌ی خارجی توسط خودِ mpv)."""
        self.raw.run(command, *args)

    def quit(self, code=None):
        """پروسه‌ی mpv رو با کد خروجی اختیاری می‌بنده (شبیه terminate ولی از مسیر کامند خودِ mpv)."""
        try:
            self.raw.quit(code)
        except Exception:
            _debug("quit() failed")

    def quit_and_save_position(self, code=None):
        """مثل quit() ولی قبلش وضعیت فعلی (watch-later) رو ذخیره می‌کنه تا بشه از همون‌جا ادامه داد."""
        try:
            self.raw.quit_watch_later(code)
        except Exception:
            _debug("quit_and_save_position() failed")

    def is_core_alive(self):
        """True یعنی هسته‌ی mpv هنوز زنده‌ست (خاموش/terminate نشده)."""
        try:
            self.raw.check_core_alive()
            return True
        except Exception:
            return False

    def set_log_level(self, level):
        """سطح لاگ خروجی به log_handler رو عوض می‌کنه ('no'..'trace')."""
        self.raw.set_loglevel(level)

    # --- منتظرماندن برای شرایط/رویدادها ---

    def wait_until_paused(self, timeout=None):
        """بلاک می‌کنه تا پخش پاز/تموم بشه (core-idle بشه)."""
        self.raw.wait_until_paused(timeout=timeout)

    def wait_for_playback_start(self, timeout=None):
        """بلاک می‌کنه تا پخش واقعاً *شروع* بشه (core-idle از True به False بره)."""
        self.raw.wait_until_playing(timeout=timeout)

    def wait_for_shutdown(self, timeout=None):
        """بلاک می‌کنه تا هسته‌ی mpv کامل خاموش بشه (مثلاً بعد از quit()/terminate())."""
        self.raw.wait_for_shutdown(timeout=timeout)

    def wait_for_property(self, name, cond=None, timeout=None):
        """
        بلاک می‌کنه تا شرط cond(value) روی پراپرتی name برقرار بشه. اگه cond
        داده نشه، یعنی هر مقدار truthy کافیه.
        """
        kwargs = {"timeout": timeout}
        if cond is not None:
            kwargs["cond"] = cond
        return self.raw.wait_for_property(name, **kwargs)

    def wait_for_property_context(self, name, cond=None, timeout=None):
        """
        نسخه‌ی context-manager همون wait_for_property؛ برای وقتی که باید یه
        کار (مثل صدازدن یه کامند) بین «شروع گوش‌دادن» و «صبرکردن» انجام بشه
        (جلوگیری از race). خروجیش یه Future هست.
        """
        kwargs = {"timeout": timeout}
        if cond is not None:
            kwargs["cond"] = cond
        return self.raw.prepare_and_wait_for_property(name, **kwargs)

    def wait_for_event_context(self, *event_names, cond=None, timeout=None):
        """مثل wait_for_event ولی به‌صورت context-manager (برای جلوگیری از race؛ توضیح کامل توی مستندات mpv.py)."""
        kwargs = {"timeout": timeout}
        if cond is not None:
            kwargs["cond"] = cond
        return self.raw.prepare_and_wait_for_event(*event_names, **kwargs)

    # --- سیک دقیق‌تر و فریم‌به‌فریم ---

    def revert_seek(self):
        """آخرین seek رو برمی‌گردونه (مثل دکمه‌ی back توی پخش‌کننده‌های ویدیویی)."""
        try:
            self.raw.revert_seek()
        except Exception:
            _debug("revert_seek() failed")

    def step_frame_forward(self):
        """یه فریم دقیق جلو می‌ره (پاز می‌کنه اگه در حال پخش بود)."""
        self.raw.frame_step()

    def step_frame_backward(self):
        """یه فریم دقیق عقب می‌ره."""
        self.raw.frame_back_step()

    # --- دسترسی عمومی به پراپرتی‌های خام mpv (صدها پراپرتی؛ یه جفت متد کافیه) ---

    def get_property(self, name):
        """
        مقدار هر پراپرتی خام mpv رو با اسمش می‌گیره (مثلاً 'volume' یا
        'time-pos'). برای پراپرتی‌هایی که این رپر اسم اختصاصی براشون نداره.
        """
        return getattr(self.raw, name.replace("-", "_"))

    def set_property(self, name, value):
        """مقدار هر پراپرتی خام mpv رو با اسمش تنظیم می‌کنه."""
        setattr(self.raw, name.replace("-", "_"), value)

    def adjust_property(self, name, amount=1):
        """مقدار عددیِ یه پراپرتی رو amount واحد زیاد می‌کنه (سرریز/کمبود کلمپ می‌شه)."""
        self.raw.property_add(name, amount)

    def multiply_property(self, name, factor):
        """مقدار عددیِ یه پراپرتی رو در factor ضرب می‌کنه."""
        self.raw.property_multiply(name, factor)

    def cycle_property(self, name, direction="up"):
        """پراپرتی رو یه پله جلو/عقب می‌بره (برای پراپرتی‌های enum/bool)."""
        self.raw.cycle(name, direction)

    def get_option_info(self, name):
        """اطلاعات یه گزینه‌ی mpv (نوع، محدوده، پیش‌فرض، ...) رو برمی‌گردونه."""
        try:
            return self.raw.option_info(name)
        except Exception:
            return None

    # --- بارگذاری مستقیم فایل/پلی‌لیست (معادل خام play/enqueue با گزینه‌های بیشتر) ---

    def load_file(self, path, mode="replace", index=None, **options):
        """
        مثل play/enqueue ولی با گزینه‌های per-file دلخواه mpv (مثلاً
        sub-file, start). mode: 'replace' (مثل play)، 'append' (مثل enqueue)، یا 'append-play'.
        """
        self.raw.loadfile(path, mode, index, **options)

    def load_playlist_file(self, path, mode="replace"):
        """یه فایل پلی‌لیست (m3u/pls/...) رو بارگذاری می‌کنه."""
        self.raw.loadlist(path, mode)

    # --- افزودن/حذف/ری‌لود ترک‌های ویدیو (برای پروژه‌های غیرصوتی) ---

    def add_video_track(self, url, title=None, language=None, albumart=None):
        """یه ترک ویدیویی/کاور آرت جدا اضافه می‌کنه و فعالش می‌کنه."""
        self.raw.video_add(url, title=title, lang=language, albumart=albumart)

    def remove_video_track(self, track_id=None):
        """یه ترک ویدیو رو حذف می‌کنه (پیش‌فرض: ترک فعال فعلی)."""
        self.raw.video_remove(track_id)

    def reload_video_track(self, track_id=None):
        """یه ترک ویدیو رو دوباره بارگذاری می‌کنه."""
        self.raw.video_reload(track_id)

    # --- حذف/ری‌لود ترک صوتی، و پرش دقیق‌تر روی زیرنویس ---

    def remove_audio_track(self, track_id=None):
        """یه ترک صوتی رو از فایل فعلی حذف می‌کنه (پیش‌فرض: ترک فعال فعلی)."""
        self.raw.audio_remove(track_id)

    def reload_audio_track(self, track_id=None):
        """یه ترک صوتی رو دوباره بارگذاری می‌کنه."""
        self.raw.audio_reload(track_id)

    def remove_subtitle(self, track_id=None):
        """یه زیرنویس رو حذف می‌کنه (پیش‌فرض: زیرنویس فعال فعلی)."""
        self.raw.sub_remove(track_id)

    def reload_subtitle(self, track_id=None):
        """یه زیرنویس رو دوباره بارگذاری می‌کنه."""
        self.raw.sub_reload(track_id)

    def step_subtitle(self, skip):
        """چند زیرنویس جلو/عقب می‌ره (skip منفی = عقب)، بدون تغییر زمان پخش."""
        self.raw.sub_step(skip)

    def seek_subtitle(self, skip):
        """پخش رو به شروع زیرنویسِ skip-امین بعدی/قبلی می‌بره."""
        self.raw.sub_seek(skip)

    # --- OSD و پیام‌های متنی روی صفحه ---

    def toggle_osd(self):
        """نمایش OSD (وضعیت پخش روی صفحه) رو روشن/خاموش می‌کنه."""
        self.raw.toggle_osd()

    def print_text(self, text):
        """یه متن رو توی ترمینال/stdout mpv چاپ می‌کنه (نه روی OSD)."""
        self.raw.print_text(text)

    def show_text(self, text, duration="-1", level=0):
        """یه متن رو روی OSD نشون می‌ده (duration بر حسب میلی‌ثانیه، '-1' یعنی پیش‌فرض)."""
        self.raw.show_text(text, duration, level)

    def expand_text(self, text):
        """رشته‌ی حاوی property-expansion های mpv (مثل ``${time-pos}``) رو باز می‌کنه."""
        return self.raw.expand_text(text)

    def expand_path(self, path):
        """مسیر حاوی متغیرهای mpv (مثل ``~~/``) رو باز می‌کنه."""
        return self.raw.expand_path(path)

    def show_progress(self):
        """نوار پیشرفت پخش رو روی OSD نشون می‌ده."""
        self.raw.show_progress()

    def rescan_external_files(self, mode="reselect"):
        """فایل‌های زیرنویس/صوتی کنار فایل فعلی رو دوباره اسکن می‌کنه."""
        self.raw.rescan_external_files(mode)

    def write_watch_later_config(self):
        """وضعیت فعلی (زمان، ترک‌ها، ...) رو دستی توی watch-later ذخیره می‌کنه."""
        try:
            self.raw.write_watch_later_config()
        except Exception:
            _debug("write_watch_later_config() failed")

    # --- شبیه‌سازی ورودی خام (کیبورد/موس/DVD؛ فقط وقتی خروجی تصویری واقعی هست معنی داره) ---

    def send_discnav_command(self, command):
        """یه کامند ناوبری DVD/Blu-ray رو می‌فرسته."""
        self.raw.discnav(command)

    def send_mouse_event(self, x, y, button=None, mode="single"):
        """یه رویداد موس (روی پنجره‌ی ویدیو) شبیه‌سازی می‌کنه."""
        self.raw.mouse(x, y, button, mode)

    def send_keypress(self, name):
        """یه فشردنِ کامل کلید (down+up) رو شبیه‌سازی می‌کنه (name طبق ``mpv --input-keylist``)."""
        self.raw.keypress(name)

    def send_keydown(self, name):
        """فقط قسمت «پایین رفتن» یه کلید رو شبیه‌سازی می‌کنه."""
        self.raw.keydown(name)

    def send_keyup(self, name=None):
        """فقط قسمت «بالا اومدن» یه کلید رو شبیه‌سازی می‌کنه (name=None یعنی همه‌ی کلیدها)."""
        self.raw.keyup(name)

    def bind_key_to_command(self, name, command):
        """یه کلید رو مستقیم به یه رشته‌کامند mpv (نه تابع پایتون) بایند می‌کنه."""
        self.raw.keybind(name, command)

    # --- Overlay های ویدیویی (فقط وقتی video_output != "null" واقعاً روی صفحه دیده می‌شن) ---

    def allocate_overlay_id(self):
        """یه شماره‌ی overlay آزاد می‌گیره (۰ تا ۶۳)."""
        return self.raw.allocate_overlay_id()

    def free_overlay_id(self, overlay_id):
        """یه شماره‌ی overlay رو آزاد می‌کنه تا دوباره قابل تخصیص باشه."""
        self.raw.free_overlay_id(overlay_id)

    def create_file_overlay(self, filename=None, size=None, stride=None, pos=(0, 0)):
        """یه overlay از یه فایل تصویری خام روی ویدیو می‌سازه."""
        return self.raw.create_file_overlay(filename, size, stride, pos)

    def create_image_overlay(self, img=None, pos=(0, 0)):
        """یه overlay از یه شیء تصویر (مثلاً PIL.Image) روی ویدیو می‌سازه."""
        return self.raw.create_image_overlay(img, pos)

    def remove_overlay(self, overlay_id):
        """یه overlay رو کامل حذف و شماره‌شو آزاد می‌کنه."""
        self.raw.remove_overlay(overlay_id)

    def add_raw_overlay(self, overlay_id, x, y, file_or_fd, offset, fmt, w, h, stride):
        """نسخه‌ی خیلی سطح‌پایینِ کامند overlay-add (بدون کمکِ FileOverlay/ImageOverlay)."""
        self.raw.overlay_add(overlay_id, x, y, file_or_fd, offset, fmt, w, h, stride)

    def remove_raw_overlay(self, overlay_id):
        """معادل خام overlay-remove (بدون آزادکردن شماره‌ی overlay در سطح پایتون)."""
        self.raw.overlay_remove(overlay_id)

    def set_osd_overlay(self, overlay_id, data, res_x=0, res_y=720, z=0, hidden=False):
        """یه overlay متنی/ASS روی OSD می‌سازه (برای زیرنویس/گرافیک سفارشی)."""
        self.raw.osd_overlay(overlay_id, data, res_x=res_x, res_y=res_y, z=z, hidden=hidden)

    def clear_osd_overlay(self, overlay_id):
        """یه OSD overlay رو خاموش می‌کنه."""
        self.raw.osd_overlay_remove(overlay_id)

    def take_screenshot_image(self, include_subtitles=True):
        """
        مثل take_screenshot ولی به‌جای ذخیره روی دیسک، یه شیء PIL.Image
        برمی‌گردونه (نیاز به پکیج Pillow داره).
        """
        includes = "subtitles" if include_subtitles else "video"
        return self.raw.screenshot_raw(includes=includes)

    # --- پیام‌های اسکریپت (ارتباط با اسکریپت‌های lua/js داخل mpv) و فیلترها ---

    def send_script_message(self, *args):
        """یه پیام broadcast برای همه‌ی اسکریپت‌های داخل mpv می‌فرسته."""
        self.raw.script_message(*args)

    def send_script_message_to(self, target, *args):
        """یه پیام مستقیم برای یه اسکریپت خاص (با اسم target) می‌فرسته."""
        self.raw.script_message_to(target, *args)

    def drop_buffers(self):
        """کل بافرهای demuxer/decoder رو خالی می‌کنه (مثلاً بعد از یه seek بزرگ)."""
        try:
            self.raw.drop_buffers()
        except Exception:
            _debug("drop_buffers() failed")

    def run_video_filter_command(self, label, command, argument):
        """یه دستور runtime به یه فیلتر ویدیوی لیبل‌دار (``@label``) می‌فرسته."""
        self.raw.vf_command(label, command, argument)

    def run_audio_filter_command(self, label, command, argument):
        """یه دستور runtime به یه فیلتر صوتی لیبل‌دار (``@label``) می‌فرسته (مثلاً کنترل زنده‌ی equalizer)."""
        self.raw.af_command(label, command, argument)

    # --- observerهای سطح‌پایین‌تر، پیام‌های اسکریپت، و رویدادهای خام (ثبت فقط با درخواست صریح صدازننده) ---

    def property_observer(self, name):
        """
        دکوریتور: تابع رو observer یه پراپرتی خاص می‌کنه (معادل decorator
        خودِ mpv.py). برای ثبت ساده‌تر از on_property_change استفاده کن.
        """
        return self.raw.property_observer(name)

    def remove_property_observer(self, name, handler):
        """یه observer رو فقط از یه پراپرتی خاص حذف می‌کنه."""
        self.raw.unobserve_property(name, handler)

    def remove_all_property_observers(self, handler):
        """یه observer رو از تمام پراپرتی‌هایی که روشون ثبت شده حذف می‌کنه."""
        self.raw.unobserve_all_properties(handler)

    def register_script_message_handler(self, target, handler=None):
        """یه handler برای پیام‌های اسکریپتِ mpv با اسم target ثبت می‌کنه."""
        self.raw.register_message_handler(target, handler)

    def unregister_script_message_handler(self, target_or_handler):
        """handler پیام اسکریپت رو حذف می‌کنه (با اسم target یا خودِ تابع handler)."""
        self.raw.unregister_message_handler(target_or_handler)

    def script_message_handler(self, target):
        """دکوریتور: تابع رو handler پیام‌های اسکریپت با اسم target می‌کنه."""
        return self.raw.message_handler(target)

    def add_event_callback(self, callback):
        """یه callback عمومی برای *همه‌ی* رویدادهای خام mpv ثبت می‌کنه (بدون فیلتر نوع)."""
        self.raw.register_event_callback(callback)

    def remove_event_callback(self, callback):
        """یه callback عمومیِ ثبت‌شده با add_event_callback رو حذف می‌کنه."""
        self.raw.unregister_event_callback(callback)

    # --- کلیدبایندینگ‌های سطح‌پایین (on_event/on_property_change برای اکثر کاربردها کافیه) ---

    def bind_key_press(self, keydef, mode="force", repetition=False):
        """
        دکوریتور ساده: تابع رو هر بار که keydef فشرده بشه صدا می‌زنه (بدون
        آرگومان). برای جزئیات بیشتر (state/char/scale) از bind_key استفاده کن.
        """
        return self.raw.on_key_press(keydef, mode, repetition)

    def bind_key(self, keydef, mode="force"):
        """دکوریتور سطح‌پایین‌تر: تابع رو با امضای (state, name, char) به keydef بایند می‌کنه."""
        return self.raw.key_binding(keydef, mode)

    def register_key_callback(self, keydef, callback_or_cmd, mode="force"):
        """معادل غیر-دکوریتورِ bind_key؛ callback_or_cmd می‌تونه تابع پایتون یا رشته‌کامند mpv باشه."""
        self.raw.register_key_binding(keydef, callback_or_cmd, mode)

    def unbind_key(self, keydef):
        """بایند یه کلید (ثبت‌شده با bind_key/bind_key_press/register_key_callback) رو حذف می‌کنه."""
        try:
            self.raw.unregister_key_binding(keydef)
        except Exception:
            _debug(f"unbind_key({keydef!r}) failed")

    # --- پروتکل‌های استریم سفارشی و پخش مستقیم از bytes (پیشرفته) ---

    def register_stream_protocol(self, proto, open_fn=None):
        """
        یه پروتکل استریم سفارشی (مثل ``foo://``) به mpv معرفی می‌کنه. جزئیات
        کامل امضای open_fn توی docstring خودِ mpv.py هست.
        """
        return self.raw.register_stream_protocol(proto, open_fn)

    def register_python_stream(self, name=None, size=None):
        """دکوریتور: یه generator رو به‌عنوان منبع یه ``python://`` URI ثبت می‌کنه."""
        return self.raw.python_stream(name, size)

    def set_stream_catchall(self, callback):
        """دکوریتور: یه catch-all برای هر ``python://`` URI که نامش از قبل ثبت نشده ثبت می‌کنه."""
        return self.raw.python_stream_catchall(callback)

    def stream_writer(self):
        """
        context manager که یه تابع write(chunk) می‌ده؛ برای stream کردن
        داده‌ی خام (مثلاً از شبکه) مستقیم به mpv بدون فایل واسط.
        """
        return self.raw.play_context()

    def play_bytes(self, data):
        """یه bytes object رو به‌عنوان یه فایل کامل پخش می‌کنه (بدون فایل واسط روی دیسک)."""
        self.raw.play_bytes(data)

    # --- پراپرتی‌های متفرقه‌ی باقی‌مونده ---

    @property
    def is_core_shutdown(self):
        """True یعنی هسته‌ی mpv خاموش شده (مثلاً بعد از quit() یا یه خطای مرگبار)."""
        return bool(self.raw.core_shutdown)

    @property
    def queue_filenames(self):
        """فقط اسم/مسیر فایل‌های پلی‌لیست فعلی (بدون بقیه‌ی متادیتای هر آیتم)."""
        return list(self.raw.playlist_filenames)
