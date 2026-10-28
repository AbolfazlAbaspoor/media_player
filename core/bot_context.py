"""
یه namespace ساده و مشترک که bot.py بعد از راه‌اندازی کامل، رفرنس‌های
اصلی خودش (t, player, cfg, ...) رو توش می‌ذاره. فایل‌های commands/ به‌جای
import مستقیم از bot.py (که چون bot.py یه اسکریپت در حال اجراست و
خودش موقع import شدن وصل می‌شه، امکان‌پذیر نیست)، از همین‌جا بهشون
دسترسی پیدا می‌کنن.

نکته‌ی مهم: همه‌ی وضعیت‌های قابل‌تغییر ربات (پلی‌لیست فعلی، سشن سرچ، مُد
پخش، وضعیت روم و ...) باید فقط از طریق attribute های همین شیء (bot.X)
خونده/نوشته بشن، نه متغیر جداگانه‌ی ماژول. چون attribute یه شیء، برخلاف
یه اسم global توی یه ماژول دیگه، وقتی از یه فایل دیگه (مثل یه دستور پلاگین
توی commands/) بهش دسترسی پیدا می‌کنی هم زنده و sync می‌مونه.

استفاده در یه فایل توی commands/:
    def run(ctx):
        bot = ctx["bot"]
        bot.t.channel_message("hello")
        bot.track_meta.append(...)
"""

class BotContext:
    """
    نگه‌دارنده‌ی همه‌ی وضعیت زنده‌ی ربات. مقداردهی اولیه توی bot.py انجام
    می‌شه؛ بعدش هم bot.py هم فایل‌های commands/ فقط از طریق attribute های
    همین شیء باهاش کار می‌کنن.
    """

    def __init__(self):
        self.t = None
        self.player = None
        self.cfg = None
        self.i18n = None
        self.services = {}
        self.manager = None

        self.load_and_play = None
        self.channel_broadcast = None
        self.save_config = None
        self.save_aliases = None
        self.is_admin = None
        self.format_time = None
        self.send_long_text = None
        self.do_join = None
        self.return_home = None
        self.stop_player = None
        self.active_service = None
        self.require_channel_service = None
        self.load_channel_playlist_by_index = None
        self.grow_search_playlist = None
        self.resolve_mode = None
        self.download_track = None

        self.start_time = 0
        self.current_service_index = 0
        self.reconnecting = False
        self.track_meta = []
        self.status_visible = True
        self.normalize_enabled = False
        self.channel_messages_enabled = True
        self.last_channel_url = None
        self.channel_playlist_index = None
        # شماره‌ی مستندی که الان پخش می‌شه (None = توی حالت مستند نیستیم).
        # تا وقتی پر باشه، یه عدد خام از کاربر یعنی «اون مستند رو پخش کن»
        # -- توضیح کامل توی core/documentary.py.
        self.documentary_number = None
        # آخرین لیستِ شماره‌گذاری‌شده‌ی کانال‌های IPTV (نتیجه‌ی tv <متن> یا
        # tv list) و ایندکسِ کانالی که همین الان ازش پخش می‌شه (None = چیزی
        # از IPTV در حال پخش نیست، فقط لیست هست) -- توضیح کامل توی core/iptv.py.
        self.iptv_channels = []
        self.iptv_playing_index = None
        # هدرهای پیش‌فرضِ mpv قبل از اینکه IPTV عوضشون کنه (None = دست نخورده).
        self.iptv_player_defaults = None
        self.last_started = None
        self.playback_mode = 2
        self.self_initiated_join = False
        self.last_join_time = 0
        self.empty_channel_since = None
        self.auto_paused_for_empty = False
        self.aliases = {}

        # تایمر خواب (دستور st) -- state پیش‌فرضش اینجاست تا همه‌جا با
        # getattr/hasattr حدس زده نشه.
        self._sleep_timer_task_id = None
        self._sleep_timer_deadline = None

        # نشست لاگینِ حساب شخصی (دستور sf) -- {teamtalk_username: account_username}.
        # فقط توی حافظه‌ست؛ با ری‌استارت ربات پاک می‌شه.
        self.sf_sessions = {}

        import threading
        self.playback_lock = threading.Lock()
        self.search_lock = threading.Lock()
        self.roam_lock = threading.Lock()

        self.search_session = {"service": None, "query": None, "stubs": [], "resolved_upto": 0, "loading": False}
        # مثل search_session ولی برای پلی‌لیست‌های بزرگ (لینک مستقیم، نه
        # سرچ متنی): فقط PLAYLIST_PAGE_SIZE آیتم اول resolve می‌شه، بقیه با
        # هر بار رسیدن به آخرین آیتم لودشده (توسط n) به‌تدریج اضافه می‌شن.
        self.playlist_growth_session = {"service": None, "url": None, "total": 0, "loaded": 0, "loading": False}
        self.grow_playlist_queue_async = None
        # آخرین عنوانی که broadcast "Now playing" براش فرستاده شده (برای
        # جلوگیری از پیام تکراری وقتی n/b خودشون یه پیام کامل‌تر می‌فرستن).
        self.last_track_info = ""
        self.roam_state = {
            "active": False,
            "requester_uid": None,
            "requester_username": None,
            "origin_channel_id": None,
            "origin_channel_password": None,
            "deadline": None,
        }

        self.playback_modes = {1: "single", 2: "playlist", 3: "repeat_track", 4: "repeat_playlist"}
        self.search_batch_size = 5
        self.roam_timeout_seconds = 300
        self.download_dir = None

        self.download_lock = threading.Lock()
        self.download_state = {
            "active": False, "stage": None, "source_url": None,
            "channel_id": None, "requested_by": None, "started_at": None,
            "percent": None, "eta_seconds": None, "transfer_id": None,
        }
        self.uploaded_tracks = {}

        self.commands = {}
        self.reloaders = {}

bot = BotContext()

