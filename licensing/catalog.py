"""
کاتالوگ فروش: امکانات، قیمت‌ها، و پنل‌های آماده.

قیمت‌ها همه به **دلار** تعریف می‌شن (چون پایدارترن) و موقع نشون دادن به
کاربر با نرخ روز به تومان هم تبدیل می‌شن (licensing/pricing.py).

## همه‌چیز قابل تغییر بدون دست‌زدن به کد

مقدارهای این فایل فقط «پیش‌فرض»ن. اگه فایل
data/licensing/catalog.json وجود داشته باشه، هر کلیدی که توش باشه روی
پیش‌فرض سوار می‌شه. یعنی تغییر قیمت‌ها یه ویرایش JSON ساده‌ست، نه دیپلوی
مجدد. با دستور `/reload` توی ربات هم بدون ری‌استارت خونده می‌شه.

## مدل قیمت

    قیمت ماهانه = (پایه + رباتِ اضافه×m + امکانات) × ضریب مدت

«پایه» شامل یه ربات و **فقط یوتیوب** است -- همون چیزی که هر لایسنس
به‌صورت پیش‌فرض داره. بقیه‌ی سرویس‌ها و امکانات دونه‌دونه اضافه می‌شن.

## کاربرهای مدیر (اپراتورها) قیمت ندارن

اپراتورهای هر ربات (تصمیم ۲۰۲۶-۰۹-۱۶) دیگه بعدِ قیمت‌گذاری/محدودیت نیستن؛
هر ربات هر چقدر اپراتور که لازم داره می‌تونه داشته باشه، فقط یه سقفِ فنیِ
۵۰ تایی داره (setup_wizard.MAX_OPERATORS) که هیچ ربطی به قیمت یا لایسنس
نداره. ستون‌های قدیمیِ دیتابیس (`licenses.max_users`، `orders.users`،
`promo_codes.max_users`) و کلید `max_users` توی `license.json` فقط برای
سازگاری با کلاینت‌ها/سوابق قدیمی نگه داشته شدن -- جایی خونده نمی‌شن.
"""

import copy
import json
import os
import threading

from core.paths import get_base_dir

OVERRIDE_FILE = os.path.join(get_base_dir(), "data", "licensing", "catalog.json")

# ---------------------------------------------------------------------------
# امکانات
# ---------------------------------------------------------------------------
# هر امکان می‌گه کدوم **سرویس‌ها** رو باز می‌کنه. لایسنس فقط روی سرویس‌ها
# قفل می‌کنه، نه روی دستورها: `p music` همیشه اجرا می‌شه، فقط ممکنه
# سرویسش توی لایسنس نباشه.
#
# قابلیت‌هایی مثل مستند یا دانلود هم «سرویس»ن (CAPABILITY_SERVICES). لیست
# `commands` هر امکان یعنی «این دستورها به سرویسِ این امکان نیاز دارن» --
# دستور همیشه وجود داره، و اگه سرویسش نباشه می‌گه «توی لایسنست نیست».
#
# «base» یه امکان نیست؛ همیشه فعاله و لیست پایه‌ی دستورهای پخش/مدیریت رو
# مشخص می‌کنه.

BASE_SERVICES = ["youtube"]

#: سرویس‌هایی که یه قابلیتن، نه یه منبع پخش روی دیسک (core/services/).
#: sync.py این‌ها رو «کهنه» حساب نمی‌کنه چون فایلی براشون نیست.
CAPABILITY_SERVICES = ["channel_live", "documentary", "download", "accounts",
                       "roaming", "proxy", "aliases", "voice_search", "iptv",
                       "live_dvr", "schedule"]

#: کدِ امکان -> سرویسی که بازش می‌کنه. این نگاشت *ساختاریه*، نه یه جزئیات
#: قیمت‌گذاری، پس فایل override نمی‌تونه پاکش کنه (_ensure_capability_services).
#: دلیلش واقعیه: sync._persist کل تعریف امکانات رو توی catalog.json
#: می‌نویسه، و اون فایل هنوز cap_documentary رو با services خالی داره؛ بدون
#: این تضمین، بعد از آپدیت هر مشتری‌ای که md خریده بود ازش محروم می‌شد.
CAPABILITY_OF_FEATURE = {
    "cap_channel_live": "channel_live",
    "cap_documentary": "documentary",
    "cap_download": "download",
    "cap_accounts": "accounts",
    "cap_roaming": "roaming",
    "cap_proxy": "proxy",
    "cap_aliases": "aliases",
    "cap_iptv": "iptv",
    "cap_voice_search": "voice_search",
    "cap_live_dvr": "live_dvr",
    "cap_schedule": "schedule",
}

BASE_COMMANDS = [
    # پخش و کنترل
    "p", "s", "k", "n", "b", "q", "queue", "m", "sh", "e", "j", "sd",
    "+", "-", "pause_toggle", "t", "v", "vu", "vd", "ss", "ns",
    # پلی‌لیست کانال و لیست‌های آماده
    "c", "cv", "cs", "cp", "cpl", "pl", "nn", "bb",
    # لینک و سرچ
    "u", "w", "wh",
    # اطلاعات
    "i", "di", "ln", "lr", "hi", "history", "hip", "uptime", "help", "ah", "res",
    # وضعیت لایسنس -- همیشه باید در دسترس باشه، وگرنه کاربری که امکاناتش
    # قفل شده هیچ راهی برای فهمیدن دلیلش از داخل ربات نداره.
    "lic", "license",
    # تست سلامت -- ابزار تشخیصه، نه یه قابلیت فروشی. اگه قفل می‌شد، اولین
    # چیزی که موقع عیب‌یابی لازمه در دسترس نبود.
    "dg", "diag",
    # تعامل ساده
    "cr", "fb", "st",
    # مدیریت ربات و سرور (مالک لایسنس همیشه باید داشته باشه)
    "aa", "aab", "ra", "ac", "ck", "cm", "cn", "h", "ic", "l", "lock", "lck",
    "unlock", "unlck", "pp", "rs", "rw", "sp",
    # زیرنویس و رأی برای رد کردن آهنگ -- رایگانِ همه
    "sub", "vn",
]

FEATURES = {
    "svc_instagram": {
        "title_fa": "سرویس اینستاگرام",
        "title_en": "Instagram",
        "price_usd": 2.0,
        "services": ["instagram"],
        "commands": ["ir", "ird", "iru", "ig", "rl", "rr", "iu", "ist", "ihl", "iht", "isv", "ilk", "iss"],
        "note_fa": "پخش ریلز با لینک مستقیم، فید پروفایل و هشتگ؛ با اکانت خودت: ریلز و استوری و هایلایت و ذخیره‌شده‌ها",
        "note_en": "Reels by direct link, profile and hashtag feeds; with your own account: reels, stories, highlights and saved videos",
    },
    "svc_tiktok": {
        "title_fa": "سرویس تیک‌تاک",
        "title_en": "TikTok",
        "price_usd": 1.0,
        "services": ["tiktok"],
        "commands": ["tk"],
        "note_fa": "پخش صدای ویدیوهای تیک‌تاک با لینک",
        "note_en": "Play the audio of TikTok videos by link",
    },
    "svc_soundcloud": {
        "title_fa": "سرویس ساندکلاد",
        "title_en": "SoundCloud",
        "price_usd": 1.0,
        "services": ["soundcloud"],
        "commands": ["sc"],
        "note_fa": "پخش آهنگ و پلی‌لیست ساندکلاد",
        "note_en": "SoundCloud search, tracks and playlists",
    },
    "svc_spotify": {
        "title_fa": "سرویس اسپاتیفای",
        "title_en": "Spotify",
        "price_usd": 1.5,
        "services": ["spotify"],
        "commands": ["spt"],
        "note_fa": "تبدیل لینک اسپاتیفای و پخشش",
        "note_en": "Resolve a Spotify link and play it",
    },
    "svc_aparat": {
        "title_fa": "سرویس آپارات",
        "title_en": "Aparat",
        "price_usd": 1.5,
        "services": ["aparat"],
        "commands": ["ap"],
        "note_fa": "جستجوی فارسی و پخش از آپارات — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback from Aparat — works without a proxy",
    },
    "svc_namasha": {
        "title_fa": "سرویس نماشا",
        "title_en": "Namasha",
        "price_usd": 1.5,
        "services": ["namasha"],
        "commands": [],
        "note_fa": "جستجوی فارسی و پخش از نماشا — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback from Namasha — works without a proxy",
    },
    "svc_tamasha": {
        "title_fa": "سرویس تماشا",
        "title_en": "Tamasha",
        "price_usd": 1.5,
        "services": ["tamasha"],
        "commands": [],
        "note_fa": "جستجوی فارسی و پخش از تماشا — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback from Tamasha — works without a proxy",
    },
    "svc_radiojavan": {
        "title_fa": "سرویس رادیو جوان",
        "title_en": "Radio Javan",
        "price_usd": 1.5,
        "services": ["radiojavan"],
        "commands": [],
        "note_fa": "جستجوی فارسی و انگلیسی و پخش آهنگ و موزیک‌ویدیو از رادیو جوان",
        "note_en": "Persian and English search and playback of songs and music videos from Radio Javan",
    },
    "svc_upmusics": {
        "title_fa": "سرویس آپ‌میوزیک",
        "title_en": "UpMusics",
        "price_usd": 1.5,
        "services": ["upmusics"],
        "commands": [],
        "note_fa": "جستجوی فارسی و پخش آهنگ ایرانی از آپ‌میوزیک — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback of Iranian music from UpMusics — works without a proxy",
    },
    "svc_nex1music": {
        "title_fa": "سرویس نکس‌وان‌میوزیک",
        "title_en": "Nex1Music",
        "price_usd": 1.5,
        "services": ["nex1music"],
        "commands": [],
        "note_fa": "جستجوی فارسی و پخش آهنگ ایرانی از نکس‌وان‌میوزیک — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback of Iranian music from Nex1Music — works without a proxy",
    },
    "svc_rozmusic": {
        "title_fa": "سرویس رزموزیک",
        "title_en": "RozMusic",
        "price_usd": 1.5,
        "services": ["rozmusic"],
        "commands": [],
        "note_fa": "جستجوی فارسی و پخش آهنگ ایرانی از رزموزیک — بدون نیاز به پروکسی",
        "note_en": "Persian search and playback of Iranian music from RozMusic — works without a proxy",
    },
    "svc_telewebion": {
        "title_fa": "سرویس تلوبیون",
        "title_en": "Telewebion",
        "price_usd": 1.5,
        "services": ["telewebion"],
        "commands": [],
        "note_fa": "آرشیو شبکه‌های تلویزیون ایران",
        "note_en": "Archive of Iranian TV channels",
    },
    "svc_youtubemusic": {
        "title_fa": "سرویس یوتیوب موزیک",
        "title_en": "YouTube Music",
        "price_usd": 2.0,
        "services": ["youtubemusic"],
        "commands": [],
        "note_fa": "جستجوی آهنگ توی کتابخانه‌ی موسیقی یوتیوب (نتیجه‌ی تمیزتر از جستجوی معمولی)",
        "note_en": "Search YouTube's music library — cleaner results than plain video search",
    },
    "svc_music_extra": {
        "title_fa": "سرویس‌های موسیقی (میکس‌کلاد، آدیومک، جامندو)",
        "title_en": "More music services (Mixcloud, Audiomack, Jamendo)",
        "price_usd": 2.0,
        "services": ["mixcloud", "audiomack", "jamendo"],
        "commands": [],
        "note_fa": "ست‌های دی‌جی، هیپ‌هاپ، و موسیقی رایگانِ بدون کپی‌رایت",
        "note_en": "DJ sets, hip-hop, and copyright-free music",
    },
    "svc_video_extra": {
        "title_fa": "سرویس‌های ویدیو (دیلی‌موشن، ویمیو، آرشیو)",
        "title_en": "More video services (Dailymotion, Vimeo, archive.org)",
        "price_usd": 2.0,
        "services": ["dailymotion", "vimeo", "archive"],
        "commands": [],
        "note_fa": "فیلم و مستند، شامل آرشیو عمومی و بدون کپی‌رایت archive.org",
        "note_en": "Films and documentaries, including the public-domain archive.org library",
    },
    "cap_channel_live": {
        "title_fa": "پخش زنده‌ی کانال (cl / lp)",
        "title_en": "Channel live streams (cl / lp)",
        "price_usd": 1.5,
        "services": ["channel_live"],
        "commands": ["cl", "lp", "cpd", "crl"],
        "note_fa": "با cl لایوِ همین‌الانِ کانال، با lp آرشیو لایوها، و تب‌های پادکست و ریلیز",
        "note_en": "cl plays the channel's current live stream, lp its past live streams, plus podcast and release tabs",
    },
    "cap_documentary": {
        "title_fa": "پخش مستند (md)",
        "title_en": "Documentaries",
        "price_usd": 1.5,
        "services": ["documentary"],
        "commands": ["md", "mostanad"],
        "note_fa": "با md مستندها رو شماره‌ای پخش کن؛ بعدش فقط عدد بفرست",
        "note_en": "Play documentaries by number with md, then just send a number",
    },
    "cap_download": {
        "title_fa": "دانلود و آپلود فایل در کانال",
        "title_en": "Download & upload",
        "price_usd": 2.0,
        "services": ["download"],
        "commands": ["dl", "dlr", "dlt", "dltc", "dltl", "dlts"],
        "note_fa": "با dl آهنگ فعلی به mp3 تبدیل و توی کانال آپلود می‌شه",
        "note_en": "dl converts the current track to mp3 and uploads it to the channel",
    },
    "cap_accounts": {
        "title_fa": "حساب شخصی و علاقه‌مندی‌های کاربرها",
        "title_en": "Personal accounts & favorites",
        "price_usd": 1.5,
        "services": ["accounts"],
        "commands": ["sf", "sfl", "af", "aff", "rf", "of", "fr", "ufr"],
        "note_fa": "هر کاربر کانال حساب و لیست علاقه‌مندی خودش رو داره",
        "note_en": "Every channel user gets their own account and favourites",
    },
    "cap_roaming": {
        "title_fa": "رومینگ بین کانال‌ها",
        "title_en": "Channel roaming",
        "price_usd": 1.0,
        "services": ["roaming"],
        "commands": ["come", "back"],
        "note_fa": "ربات با come به کانال تو می‌آد و با back برمی‌گرده",
        "note_en": "The bot joins your channel with come and returns with back",
    },
    "cap_proxy": {
        "title_fa": "پروکسی اختصاصی",
        "title_en": "Proxy",
        "price_usd": 1.0,
        "services": ["proxy"],
        "commands": ["proxy", "up"],
        "note_fa": "برای سرورهایی که دسترسی مستقیم به یوتیوب ندارن",
        "note_en": "For servers with no direct route to YouTube",
    },
    "cap_aliases": {
        "title_fa": "دستورهای دلخواه (alias)",
        "title_en": "Custom aliases",
        "price_usd": 1.0,
        "services": ["aliases"],
        "commands": ["al", "ral"],
        "note_fa": "ساخت میان‌بر برای دستورها، مثلاً «آهنگ» به‌جای p",
        "note_en": "Shortcuts for commands, e.g. “music” instead of p",
    },
    "cap_iptv": {
        "title_fa": "پخش تلویزیون/رادیوی اینترنتی (IPTV)",
        "title_en": "IPTV (live TV/radio)",
        "price_usd": 2.0,
        "services": ["iptv"],
        "commands": ["tv", "tvs"],
        "note_fa": "با tv کانال‌های زنده رو سرچ و پخش کن؛ بعدش عدد یا n/b برای گشتن بین کانال‌ها",
        "note_en": "Search and play live channels with tv; then a number or n/b to browse channels",
    },
    "cap_voice_search": {
        "title_fa": "جستجوی صوتی (vs)",
        "title_en": "Voice search (vs)",
        "price_usd": 2.0,
        "services": ["voice_search"],
        "commands": ["vs", "vss"],
        "note_fa": "با vs حرف بزن، ربات صدات رو به متن تبدیل می‌کنه و باهاش سرچ می‌کنه؛ هر زبانی، قابل‌تنظیم با vss. توجه: توی کانالی که «No recording» روش تنظیم شده، تیم‌تاک صدا رو به هیچ رباتی نمی‌ده مگر حسابش دسترسیِ «Record voice» (یا ادمینِ سرور) باشه؛ بدونش این قابلیت توی همچین کانالی کار نمی‌کنه.",
        "note_en": "Speak with vs and the bot turns it into a search; any language, configurable with vss. Note: in a channel set to “No recording”, TeamTalk won't give any bot audio unless its account has the “Record voice” right (or is a server admin) — without that, this feature won't work in such a channel.",
    },
    "cap_live_dvr": {
        "title_fa": "بازگشت به عقب توی لایو (DVR)",
        "title_en": "Live DVR (seek backward in a live stream)",
        # عمداً حدود ۱.۷ برابرِ cap_channel_live (۱.۵): برخلاف cl که فقط یه
        # لینکِ HLS رو resolve و به mpv می‌ده، این قابلیت تا وقتی فعاله یه
        # دانلودِ پس‌زمینه‌ی پیوسته (yt-dlp) روی سروِر ربات باز نگه می‌داره --
        # هم CPU/شبکه‌ی بیشتر هم فضای دیسکِ موقت، پس جدا و گران‌تر قیمت‌گذاری شده.
        "price_usd": 2.5,
        "services": ["live_dvr"],
        "commands": ["cld"],
        "note_fa": "با cld لایوِ همین‌الانِ کانال از یه‌جای عقب‌تر شروع می‌شه و می‌تونی با +/- به عقب/جلو بری؛ چون تا وقتی فعاله یه دانلودِ پس‌زمینه‌ی پیوسته روی سرور باز می‌مونه، مصرف منابعش از cl بیشتره و جدا قیمت‌گذاری شده",
        "note_en": "cld lets you scrub backward into the channel's current live stream with the usual +/- seek; because it keeps a continuous background download running on the server while active, it costs more server resources than cl and is priced separately",
    },
    "cap_schedule": {
        "title_fa": "پخش زمان‌بندی‌شده (sch)",
        "title_en": "Scheduled playback (sch)",
        "price_usd": 1.5,
        "services": ["schedule"],
        "commands": ["sch"],
        "note_fa": "ادمین با sch یه جستجو یا لینک رو برای ساعت (و روزهای) مشخص تنظیم می‌کنه و ربات همون موقع خودش پخشش می‌کنه؛ با ساعتِ محلیِ سرور، و با ری‌استارت هم می‌مونه",
        "note_en": "Admins schedule a search or link for a set time (and weekdays) with sch and the bot plays it by itself at that moment; uses the server's local time and survives restarts",
    },
}

# بسته‌ها: مجموعه‌ای از امکانات با تخفیف. قیمت بسته جای جمعِ تک‌تک اعضاش
# حساب می‌شه (اگه همه‌شون انتخاب شده باشن).
BUNDLES = {
    "bundle_services": {
        "title_fa": "بسته‌ی همه‌ی سرویس‌ها",
        "title_en": "All services bundle",
        "price_usd": 4.0,
        "features": ["svc_instagram", "svc_tiktok", "svc_soundcloud", "svc_spotify"],
    },
    "bundle_all": {
        "title_fa": "بسته‌ی کامل (همه‌ی سرویس‌ها و امکانات)",
        "title_en": "Everything bundle (all services and features)",
        "price_usd": 9.0,
        "features": list(FEATURES.keys()),
    },
}

# ---------------------------------------------------------------------------
# قیمت پایه و ضریب‌ها
# ---------------------------------------------------------------------------

PRICING = {
    # --- هزینه‌ی زیرساخت ---
    # هر ربات یه پروسه، یه نمونه‌ی mpv و یه لاین صدا روی سرور مصرف می‌کنه.
    # به‌جای این‌که این هزینه رو حدسی توی قیمت پایه قایم کنیم، صریح حسابش
    # می‌کنیم: سهم هر ربات از اجاره‌ی سرور = monthly_usd / capacity_bots.
    #
    # مزیتش: وقتی سرور رو عوض/بزرگ کردی، فقط همین دو عدد رو به‌روز می‌کنی و
    # همه‌ی قیمت‌ها خودشون درست می‌شن -- و توی فاکتور هم به‌عنوان یه ردیف
    # جدا دیده می‌شه، پس می‌دونی حاشیه‌ی سودت واقعاً چقدره.
    #
    # اعداد پیش‌فرض از روی یه VPS معمولی (۴ گیگ رم، ۲ هسته) حساب شدن که
    # حدود ۲۵ ربات جا می‌ده -- محاسبه‌ی کاملش توی docs/SERVER.md.
    "server": {
        "monthly_usd": 12.0,
        "capacity_bots": 25,
        # ضریب اطمینان روی هزینه‌ی زیرساخت: ۱.۵ یعنی برای پهنای‌باند اضافه،
        # بکاپ و روزهای شلوغ هم کنار گذاشته می‌شه.
        "overhead_multiplier": 1.5,
    },

    # --- قیمت پایه (بدون هزینه‌ی سرور؛ اون خودکار اضافه می‌شه) ---
    # یک ربات، فقط یوتیوب، یک ماه -- تعداد کاربر مدیر روی قیمت اثر نداره
    "base_monthly_usd": 5.0,
    # هر ربات اضافه (بیشتر از ۱) -- یه لاین صدای جدا و یه پروسه‌ی جدا روی
    # سرور مصرف می‌کنه.
    "extra_bot_usd": 4.0,
    # ضریب کل برای چند ماه. کلید = تعداد ماه.
    # عدد از «ماه × ۱» کمتره، یعنی تخفیف مدت بلند.
    # فقط یک ماه: صاحب کسب‌وکار تصمیم گرفت هیچ خرید/تمدید/پنلی بیش از یک
    # ماه در یه تراکنش نباشه (نه فروشِ چندماهه با تخفیف). خریدار برای مدتِ
    # بیشتر چندبار یک‌ماهه تمدید می‌کنه. duration_multiplier() برای هر
    # عددی بیرون از این جدول خطی (بدون تخفیف) حساب می‌کنه، پس یه سفارشِ
    # قدیمی/override که هنوز چندماهه‌ست کرش نمی‌کنه.
    "duration_multipliers": {
        "1": 1.0,
    },
    # سقف، تا کسی سفارشی نسازه که سرور رو بخوابونه (کاربر مدیر سقف
    # قیمتی نداره؛ فقط سقفِ فنیِ setup_wizard.MAX_OPERATORS رو داره)
    "max_bots": 10,
    # رند کردن مبلغ تومانی به نزدیک‌ترین مضربِ این عدد (برای کارت‌به‌کارت
    # عدد رند خیلی راحت‌تره)
    "irr_rounding": 1000,
}

# ---------------------------------------------------------------------------
# پنل‌های آماده (همون «پنل ۱، پنل ۲» که کاربر می‌بینه)
# ---------------------------------------------------------------------------
# این‌ها فقط میان‌برن: هر کدوم یه ترکیب از (ماه، ربات، امکانات) که قیمتش
# با همون فرمول بالا حساب می‌شه. کاربر می‌تونه از «سفارشی» هم شروع کنه و
# خودش همه‌چیز رو تنظیم کنه.
#
# کدها (p1/p3/p4/p5) عمداً پیوسته نیستن: پنل قدیمیِ p2 فقط با تعداد کاربر
# مدیر از p1 فرق داشت و با حذفِ اون بُعد از قیمت‌گذاری معنی نداشت، ولی
# کدش حذف نشد چون سفارش‌های قدیمی به همین کد اشاره می‌کنن. عنوان‌های
# نمایشی (پنل ۱..۴) پیوسته و تازه‌ان.

PANELS = [
    {
        "code": "p1",
        "title_fa": "پنل ۱ — یک ماه",
        "title_en": "Plan 1 — one month",
        "months": 1, "bots": 1, "features": [],
    },
    {
        "code": "p3",
        "title_fa": "پنل ۲ — یک ماه، دو ربات",
        "title_en": "Plan 2 — one month, two bots",
        "months": 1, "bots": 2, "features": [],
    },
    {
        "code": "p4",
        "title_fa": "پنل ۳ — یک ماه، همه‌ی سرویس‌ها",
        "title_en": "Plan 3 — one month, all services",
        "months": 1, "bots": 1,
        "features": ["svc_instagram", "svc_tiktok", "svc_soundcloud", "svc_spotify"],
    },
    {
        "code": "p5",
        "title_fa": "پنل ۴ — یک ماه، بسته‌ی کامل، دو ربات",
        "title_en": "Plan 4 — one month, everything, two bots",
        "months": 1, "bots": 2,
        "features": list(FEATURES.keys()),
    },
]

_lock = threading.RLock()
_loaded = None


def _deep_merge(base, override):
    """
    override رو روی base سوار می‌کنه.

    لیست‌هایی که از dict های شناسه‌دار ساخته شدن (مثل panels با کلید code)
    عضو‌به‌عضو ادغام می‌شن، نه اینکه کل لیست جایگزین بشه.

    چرا مهمه: یه کاربر که قیمت‌ها رو سفارشی کرده، یه catalog.json داره که
    کل لیست panels رو نگه می‌داره. با جایگزینیِ کامل، هر فیلد *جدیدی* که
    آپدیت‌های بعدی به پنل‌ها اضافه کنن (مثل title_en) بی‌سروصدا گم می‌شد --
    و رابط انگلیسی نیمه‌فارسی می‌موند. حالا سفارشی‌سازی کاربر برنده‌ست ولی
    فیلدهای تازه هم می‌رسن.
    """
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            base[key] = _merge_keyed_lists(base[key], value)
        else:
            base[key] = value
    return base


def _merge_keyed_lists(base_list, override_list, id_field="code"):
    """
    دو لیست از dict رو بر اساس یه فیلد شناسه ادغام می‌کنه.

    اگه لیست‌ها این شکل رو نداشته باشن (مثلاً لیست رشته)، رفتار قبلی حفظ
    می‌شه: لیست override کامل جایگزین می‌شه.
    """
    def keyed(items):
        return all(isinstance(item, dict) and id_field in item for item in items)

    if not override_list or not keyed(override_list) or not keyed(base_list):
        return list(override_list)

    defaults = {item[id_field]: item for item in base_list}
    merged = []
    for item in override_list:
        default = defaults.get(item[id_field])
        if default is None:
            merged.append(copy.deepcopy(item))
            continue
        combined = copy.deepcopy(default)
        _deep_merge(combined, item)
        merged.append(combined)
    return merged


def _defaults():
    return {
        "features": copy.deepcopy(FEATURES),
        "bundles": copy.deepcopy(BUNDLES),
        "pricing": copy.deepcopy(PRICING),
        "panels": copy.deepcopy(PANELS),
        "base_services": list(BASE_SERVICES),
        "base_commands": list(BASE_COMMANDS),
    }


def load(force=False):
    """کاتالوگ نهایی (پیش‌فرض + override فایل JSON)."""
    global _loaded
    with _lock:
        if _loaded is not None and not force:
            return _loaded
        catalog = _defaults()
        try:
            with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
                _deep_merge(catalog, json.load(f))
        except FileNotFoundError:
            pass
        except ValueError as e:
            # کاتالوگ خراب نباید کل ربات فروش رو بخوابونه؛ با پیش‌فرض ادامه
            # می‌دیم ولی صریحاً اعلام می‌کنیم.
            print(f"[Catalog] {OVERRIDE_FILE} is malformed and was ignored: {e}")
        _ensure_capability_services(catalog)
        _enforce_max_one_month(catalog)
        _loaded = catalog
        return catalog


# صاحبِ کسب‌وکار: هیچ خرید/تمدید/پنلی نباید بیش از یه ماه در یه تراکنش
# باشه. این‌جا (نه فقط توی PANELS/PRICING پیش‌فرض بالا) اعمال می‌شه چون
# یه فایلِ override قدیمی -- روی این ماشین یا سرورِ واقعی -- ممکنه هنوز
# پنل/ضریبِ چندماهه‌ی از قبل ذخیره‌شده داشته باشه؛ بدونِ این قفل، تغییرِ
# پیش‌فرض‌های بالا روی همچین override ای هیچ اثری نداشت.
MAX_PANEL_MONTHS = 1


def _enforce_max_one_month(catalog):
    for panel in catalog.get("panels") or []:
        if int(panel.get("months") or 1) > MAX_PANEL_MONTHS:
            panel["months"] = MAX_PANEL_MONTHS
    multipliers = catalog.get("pricing", {}).get("duration_multipliers") or {}
    catalog["pricing"]["duration_multipliers"] = {
        k: v for k, v in multipliers.items() if int(k) <= MAX_PANEL_MONTHS
    } or {"1": 1.0}


def _ensure_capability_services(catalog):
    """هر امکانِ قابلیتی حتماً سرویسِ خودش رو داشته باشه، هر چی override گفته."""
    all_features = catalog.get("features") or {}
    for code, service in CAPABILITY_OF_FEATURE.items():
        entry = all_features.get(code)
        if entry is None:
            continue
        services = list(entry.get("services") or [])
        if service not in services:
            services.append(service)
        entry["services"] = services


def reload():
    return load(force=True)


def write_override_template():
    """
    یه کپی از کاتالوگ فعلی رو به‌عنوان نقطه‌ی شروع ویرایش می‌نویسه (فقط اگه
    از قبل نباشه، تا تغییرات دستی پاک نشن).
    """
    if os.path.isfile(OVERRIDE_FILE):
        return False
    os.makedirs(os.path.dirname(OVERRIDE_FILE), exist_ok=True)
    with open(OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(_defaults(), f, ensure_ascii=False, indent=2)
    return True


# ---------------------------------------------------------------------------
# پرس‌وجو
# ---------------------------------------------------------------------------

def features():
    return load()["features"]


def bundles():
    return load()["bundles"]


def pricing():
    return load()["pricing"]


def panels():
    return load()["panels"]


def save_panels(panels_list):
    """
    پنل‌ها رو توی فایلِ override می‌نویسه -- فقط کلیدِ panels رو دست
    می‌زنه، بقیه‌ی سفارشی‌سازی‌های احتمالیِ فایل (امکانات/قیمت) دست‌نخورده
    می‌مونه. panels_list جایگزینِ کاملِ لیستِ فعلیه (افزودن/ویرایش/حذف هر
    سه از همین یه مسیر رد می‌شن -- کد caller قبلش panels() رو خونده،
    توش تغییر داده، و همینو صدا می‌زنه).
    """
    try:
        with open(OVERRIDE_FILE, "r", encoding="utf-8") as f:
            override = json.load(f)
    except (FileNotFoundError, ValueError):
        override = {}
    if not isinstance(override, dict):
        override = {}
    override["panels"] = panels_list
    os.makedirs(os.path.dirname(OVERRIDE_FILE), exist_ok=True)
    with open(OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(override, f, ensure_ascii=False, indent=2)
    reload()


def feature_title(code):
    """
    اسم یه امکان به زبان فعلی.

    کاتالوگ هر دو عنوان رو داره (title_fa و title_en)، پس ترجمه‌ی اسم
    امکانات جای دیگه‌ای لازم نیست -- همون‌جایی که قیمتش تعریف می‌شه.
    """
    from licensing import i18n

    entry = features().get(code) or bundles().get(code)
    if not entry:
        return code
    if i18n.get_language() == "fa":
        return entry.get("title_fa") or entry.get("title_en") or code
    return entry.get("title_en") or entry.get("title_fa") or code


def feature_note(code):
    """توضیح کوتاه یه امکان، به زبان فعلی."""
    from licensing import i18n

    entry = features().get(code) or {}
    if i18n.get_language() == "fa":
        return entry.get("note_fa") or entry.get("note_en") or ""
    return entry.get("note_en") or entry.get("note_fa") or ""


def expand_features(codes):
    """
    لیست کدها رو به مجموعه‌ی امکاناتِ *واقعی* باز می‌کنه (بسته‌ها به
    اعضاشون تبدیل می‌شن) و کدهای ناشناس رو دور می‌ریزه.
    """
    known = features()
    all_bundles = bundles()
    result = []
    for code in codes or []:
        if code in all_bundles:
            for member in all_bundles[code].get("features", []):
                if member in known and member not in result:
                    result.append(member)
        elif code in known and code not in result:
            result.append(code)
    return result


def _allowed(license_features, base_key, field):
    allowed = list(load()[base_key])
    catalog_features = features()
    for code in expand_features(license_features):
        for name in catalog_features.get(code, {}).get(field, []):
            if name not in allowed:
                allowed.append(name)
    return allowed


def allowed_services(license_features):
    """اسم سرویس‌هایی که این لایسنس اجازه داره لود کنه."""
    return _allowed(license_features, "base_services", "services")


def allowed_commands(license_features):
    """اسم دستورهایی که این لایسنس اجازه داره داشته باشه."""
    return _allowed(license_features, "base_commands", "commands")


def _feature_owning(field, name):
    for code, feature in features().items():
        if name in feature.get(field, []):
            return code
    return None


def feature_for_command(command_name):
    """
    این دستور مالِ کدوم امکانه؟ None یعنی جزو پایه‌ست یا ناشناسه. برای
    پیام «این قابلیت توی لایسنس شما نیست» استفاده می‌شه.
    """
    return _feature_owning("commands", command_name)


def feature_for_service(service_name):
    return _feature_owning("services", service_name)


def service_for_command(name):
    """
    دستور به کدوم سرویس نیاز داره؟ None یعنی آزاده (همه دارن).

    اولین امکانی که این دستور رو توی `commands` خودش داره تعیینش می‌کنه.
    """
    for feature in features().values():
        if name in (feature.get("commands") or []):
            services = feature.get("services") or []
            if services:
                return services[0]
    return None


def service_title(service):
    """اسم قابل‌نمایشِ یه سرویس، از روی امکانی که بازش می‌کنه."""
    for code, feature in features().items():
        if service in (feature.get("services") or []):
            return feature_title(code)
    return service


def services_implied_by_commands(commands):
    """
    سرویس‌هایی که یه لیست دستورِ قدیمی بهشون اشاره داره.

    فقط برای سازگاری: license.json هایی که قبل از مدل «فقط سرویس» نوشته
    شدن `commands` دارن ولی قابلیت‌ها (مستند، دانلود...) توی `services`شون
    نیست. بدون این، مشتری‌ای که md خریده بود بعد از آپدیت ازش محروم می‌شد.
    """
    commands = set(commands or [])
    implied = []
    for feature in features().values():
        wanted = feature.get("commands") or []
        if wanted and commands.issuperset(wanted):
            for service in feature.get("services") or []:
                if service not in implied:
                    implied.append(service)
    return implied
