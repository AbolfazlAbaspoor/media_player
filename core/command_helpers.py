"""
کمک‌توابع مشترک بین کمان‌هایی که الگوی یکسانی دارن: گرفتن سرویس کانال
فعلی، صدا زدن یه متد روش، پخش نتیجه، و broadcast کردن پیام شروع/پایان.

قبلاً c.py/cv.py/cs.py هرکدوم همین ~۲۵ خط رو جدا کپی کرده بودن (فقط اسم
متد سرویس و کلیدهای i18n فرق داشت)؛ الان فقط پارامترهای فرق‌دار رو
می‌دن.
"""

import re
import time

from core import i18n
from core import link_resolver
from core import logging_setup
from core import status_line

# پیستِ خامِ بدونِ http:// هم باید مثلِ لینکِ کامل رفتار کنه (مثلاً
# "instagram.com/reel/xyz" یا "youtu.be/xyz" که خیلی جاها بدونِ اسکیم
# کپی می‌شن). قبلاً bot.py فقط raw_msg.startswith("http") رو لینک حساب
# می‌کرد، پس این‌جور پیست‌ها به‌عنوانِ دستورِ ناشناخته رد می‌شدن و کاربر
# مجبور بود صریحاً از u/iru استفاده کنه -- یعنی این دو دستور دیگه واقعاً
# لازم نبودن، فقط این تشخیص جا افتاده بود.
BARE_LINK_RE = re.compile(
    r"^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}(?:[/?#]\S*)?$",
    re.IGNORECASE,
)


def looks_like_bare_link(text):
    """یه تکه‌متنِ تک‌کلمه‌ای که شکلِ یه دامنه/لینک رو داره، بدونِ اسکیم؟"""
    if not text or any(ch.isspace() for ch in text):
        return False
    return bool(BARE_LINK_RE.match(text))


def normalize_pasted_link(text):
    """لینکِ پیست‌شده رو برای run_link_command آماده می‌کنه (اسکیم گمشده رو اضافه می‌کنه)."""
    if text.startswith(("http://", "https://")):
        return text
    return f"https://{text}"

# mpv بعد از جابه‌جایی توی صف، فایل جدید رو غیرهمزمان باز می‌کنه؛ تا اون
# لحظه duration_seconds هنوز None ـه. چند لحظه صبر می‌کنیم تا طول واقعی
# معلوم بشه (وگرنه پیام همیشه «0 seconds» نشون می‌داد).
_DURATION_WAIT_TIMEOUT = 3.0
_DURATION_WAIT_POLL = 0.15


def _wait_for_duration(bot):
    """
    طول فایل فعلی رو برمی‌گردونه، و اگه mpv تا سقف مهلت هم نفهمیدش (استریم
    زنده یا طول‌نامعلوم) None -- تا توی پیام اصلاً نیاد، نه این‌که عدد غلط
    (۰ ثانیه) نشون داده بشه.
    """
    deadline = time.time() + _DURATION_WAIT_TIMEOUT
    while time.time() < deadline:
        try:
            duration = bot.player.duration_seconds
        except Exception:
            duration = None
        if duration:
            return duration
        time.sleep(_DURATION_WAIT_POLL)
    return None


def notify(bot, ctx, key, **kwargs):
    """
    یه خبر که *همه‌ی* کانال باید ببینه -- مثل «چیزی پیدا نشد».

    چرا کانال و نه پیام خصوصی: وقتی یه نفر چیزی رو سرچ می‌کنه و نتیجه‌ای
    نیست، بقیه‌ی کانال هم منتظرن. با پیام خصوصی، برای بقیه فقط «هیچ
    اتفاقی نیفتاد» دیده می‌شه و یکی دیگه همون سرچ رو تکرار می‌کنه.

    اگه ادمین پیام‌های کانال رو با cm خاموش کرده باشه، به پیام خصوصی
    برمی‌گرده -- خبر نباید کلاً گم بشه، فقط جاش عوض می‌شه.
    """
    text = i18n.t(key, **kwargs)
    if getattr(bot, "channel_messages_enabled", True):
        bot.channel_broadcast(text)
        return
    bot.t.user_message(ctx["uid"], text)


def start_growth_session(bot, service, service_name, query, first, is_url, count):
    """
    صفِ رشد رو برای n/b راه می‌ندازه و تعداد واقعیِ آیتم‌ها رو برمی‌گردونه.

    موتور رشد (core/trackqueue.py + _grow_queue) از اول سرویس‌محور نبود --
    هر سرویسی که search_batch یا grow_playlist داشته باشه کار می‌کنه. چیزی
    که کم بود، *راه‌انداختن session* بود: فقط p.py این کار رو می‌کرد، پس
    بعد از sc/tk/spt/ap و بقیه‌ی دستورهای اختصاصی، n هیچی برای رشد نداشت
    و به «آخر صف» می‌خورد درحالی‌که سرویس هنوز کلی نتیجه داشت.

    قبلاً یه early-return هم بود که توی مُدهای «تک‌آهنگ»/«تکرار آهنگ»
    (bot.single_track_modes) کلاً از رشد صرف‌نظر می‌کرد -- یعنی m (که قراره
    فقط رفتارِ «آهنگ تموم شد» رو تعیین کنه) هر جستجویی رو هم به یه‌دونه
    نتیجه محدود می‌کرد. m دیگه اینجا خونده نمی‌شه (E5): جستجو/پلی‌لیست
    همیشه رشد می‌کنه.

    خروجی: تعداد آیتم‌ها (برای پلی‌لیست ناقص، تعداد *کل* نه فقط لودشده‌ها).
    """
    if not is_url and hasattr(service, "search_batch"):
        first_id = first.get("id") if isinstance(first, dict) else None
        with bot.search_lock:
            bot.search_session["service"] = service_name
            bot.search_session["query"] = query
            bot.search_session["stubs"] = []
            bot.search_session["resolved_upto"] = 1
            bot.search_session["loading"] = False
            # داخل قفل شروع می‌شه تا search_session نصفه‌کاره دیده نشه.
            bot.grow_search_playlist_async(service_name, query, skip_id=first_id,
                                           target_count=bot.search_batch_size)
        return count

    return apply_playlist_growth(bot, service, service_name, count)


def apply_playlist_growth(bot, service, service_name, count):
    """
    اگه سرویس برای آخرین لینک/کانالی که resolve کرده فقط آیتم اول رو
    برگردونده (شروع سریع پخش) و بقیه‌ی پلی‌لیست قراره با n به‌تدریج لود
    بشه، session رشدش رو راه می‌ندازه و تعداد *کل* رو برمی‌گردونه.

    قبلاً همین ~۱۰ خط توی start_growth_session، run_channel_content_command
    و pl.py هرکدوم جدا کپی شده بود.
    """
    if not hasattr(service, "get_playlist_growth_info"):
        return count
    growth_info = service.get_playlist_growth_info()
    if not growth_info:
        return count
    g_url, total, loaded = growth_info
    with bot.search_lock:
        bot.playlist_growth_session["service"] = service_name
        bot.playlist_growth_session["url"] = g_url
        bot.playlist_growth_session["total"] = total
        bot.playlist_growth_session["loaded"] = loaded
        bot.playlist_growth_session["loading"] = False
    return total


def acknowledge_request(bot, ctx, query=None, service=None):
    """
    پیامِ اول از دو پیامِ E12: «فلانی دنبال این می‌گرده» -- به کل کانال،
    چون بقیه هم منتظرن و اگه فقط درخواست‌کننده بدونه، یکی دیگه همون سرچِ
    کند رو دوباره می‌زنه. پیامِ دوم (broadcast_now_playing) وقتی واقعاً
    چیزی پخش شد میاد؛ اینجا فقط می‌گیم چی داره جستجو می‌شه.

    اگه ادمین پیام‌های کانال رو با cm خاموش کرده باشه، به پیام خصوصیِ
    درخواست‌کننده برمی‌گرده -- خبر نباید کلاً گم بشه، فقط جاش عوض می‌شه.

    لینک هیچ‌وقت توی متن نمیاد، حتی برای خودِ درخواست‌کننده.
    """
    nickname = ctx.get("nickname", "")
    if query is not None and not is_link(query):
        text = i18n.t("request_ack_search", query=query, service=service or "", nickname=nickname)
    else:
        text = i18n.t("request_ack_link", nickname=nickname)
    if getattr(bot, "channel_messages_enabled", True):
        bot.channel_broadcast(text)
        return
    try:
        bot.t.user_message(ctx["uid"], text)
    except Exception:
        logging_setup.log_debug("request acknowledgement failed")


def current_display_title(bot):
    """
    عنوانِ قابل‌نمایشِ آیتمِ فعلیِ صف (یا mpv اگه صف هنوز چیزی نداره).
    broadcast_now_playing و حلقه‌ی housekeeping (بعد از پیشروی خودکار به
    آیتم بعدی) هر دو از همینِ یکی استفاده می‌کنن.
    """
    idx = bot.queue.index
    meta = bot.track_meta[idx] if idx is not None and 0 <= idx < len(bot.track_meta) else {}
    return display_title(meta, bot.player.now_playing_title) or "..."


def broadcast_now_playing(bot):
    """
    تنها پیام «Now playing» -- بعد از هر پخشی: n/b، انتخاب با عدد، یه
    سرچ/لینک تازه، یا پیشروی خودکار به آیتم بعدی وقتی آهنگ تموم می‌شه.
    عنوان + ایندکسِ فعلی/کل + مدت فایل (یا LIVE)، یه خط جمع‌وجور -- کی
    خواسته بود و از کدوم سرویس توی پیامِ اول (acknowledge_request) گفته
    شده، اینجا تکرار نمی‌شه.

    bot.last_track_info قبل از صبرکردن برای duration ست می‌شه: حلقه‌ی
    housekeeping هر نیم‌ثانیه تغییر ترک رو چک می‌کنه و اگه زودتر ستش
    نکنیم، همون وسط پیام تکراری خودش رو می‌فرسته.
    """
    idx = bot.queue.index
    epoch = getattr(bot.queue, "epoch", None)
    # کل پلی‌لیست، نه فقط آیتم‌های لودشده -- وگرنه برای یه پلی‌لیستِ ۴۳۸تایی
    # که تدریجی لود می‌شه «۱ از ۱» نوشته می‌شد و این تنها جایی بود که تعداد
    # کل گفته می‌شد.
    total = max(bot.queue.length, getattr(bot.queue, "expected_total", 0) or 0)
    current = (idx + 1) if idx is not None else 1
    title = current_display_title(bot)

    bot.last_track_info = title

    duration = _wait_for_duration(bot)
    # وسطِ همین انتظار (تا چند ثانیه) ممکنه یه سرچ/آیتمِ تازه شروع شده باشه؛
    # اون‌وقت این پیام مالِ آهنگِ قبلیه و نباید فرستاده بشه -- اعلامِ آهنگِ
    # جدید کارِ فراخوانِ خودشه. قبلاً آهنگِ قبلی هم (گاهی بعد از جدید) توی
    # چت می‌اومد.
    if getattr(bot.queue, "epoch", None) != epoch or bot.queue.index != idx:
        return
    # تا اینجا mpv معمولاً عنوان واقعی رو خونده؛ اگه عوض شد همون رو بفرست و
    # حلقه‌ی اصلی رو هم هم‌تراز کن، وگرنه یه «در حال پخش» دوم می‌فرستاد.
    refreshed = current_display_title(bot)
    if refreshed and refreshed != title:
        title = refreshed
        bot.last_track_info = title
    if duration:
        bot.channel_broadcast(i18n.t(
            "now_playing_full", title=title, current=current, total=total,
            duration=bot.format_time(duration),
        ))
    else:
        bot.channel_broadcast(i18n.t(
            "now_playing_full_live", title=title, current=current, total=total,
        ))


def current_track_meta(bot, ctx):
    """
    متادیتای آهنگ در حال پخش، یا None (بعد از فرستادن «nothing_playing» به
    درخواست‌کننده) اگه چیزی پخش نمی‌شه. فراخوان فقط return می‌کنه.
    """
    if bot.player.current_url is None or not bot.track_meta:
        bot.t.user_message(ctx["uid"], i18n.t("nothing_playing"))
        return None
    idx = bot.queue.index or 0
    if idx >= len(bot.track_meta):
        bot.t.user_message(ctx["uid"], i18n.t("nothing_playing"))
        return None
    return bot.track_meta[idx]


def current_shareable_meta(bot, ctx):
    """مثل current_track_meta، ولی آهنگِ خصوصی هم «link_private» می‌گیره."""
    meta = current_track_meta(bot, ctx)
    if meta is None:
        return None
    if not is_shareable(meta):
        bot.t.user_message(ctx["uid"], i18n.t("link_private"))
        return None
    return meta


def session_account(bot, ctx):
    """
    (نام حساب، مسیر، داده، عمومی؟) برای حسابِ شخصیِ لاگین‌شده‌ی درخواست‌کننده،
    یا None بعد از فرستادنِ «sf_not_logged_in». (sf/sfl/of)
    """
    from core import accounts

    account = accounts.get_session_account(bot, ctx['username'])
    if account[2] is None:
        bot.t.user_message(ctx['uid'], i18n.t('sf_not_logged_in'))
        return None
    return account


def session_favorites(bot, ctx):
    """(حساب، فروریت‌ها) یا None اگه لاگین نیست یا فروریت خالیه (با پیام)."""
    account = session_account(bot, ctx)
    if account is None:
        return None
    favorites = account[2].get('favorites', [])
    if not favorites:
        bot.t.user_message(ctx['uid'], i18n.t('sf_playlist_empty'))
        return None
    return account, favorites


def active_search_service(bot, ctx):
    """
    (اسم، سرویس) برای سرویسِ فعالِ سرچِ متنی (همون که w می‌چرخونه)، یا None
    بعد از فرستادنِ «سرویسی نیست». فقط سرویس‌های قابل‌سرچ (نه instagram/tiktok/...
    که لینک‌محضن و current_service_index هیچ‌وقت روشون نمی‌ایسته).
    """
    from core import manager

    srv_list = manager.searchable_service_names(bot.services)
    if not srv_list:
        bot.t.user_message(ctx['uid'], no_services_message(bot))
        return None
    active_name = srv_list[bot.current_service_index]
    return active_name, bot.services[active_name]


def add_admin_command(ctx, name, cfg_key, already_key, confirm_key):
    """aa/aab: یوزرنیم رو به لیستِ cfg_key (admins یا bot_admins) اضافه می‌کنه."""
    bot = ctx["bot"]
    if not ctx['args']:
        bot.t.user_message(ctx['uid'], i18n.t('usage_generic', usage=bot.commands[name]['usage']))
        return
    username = ctx['args'][0]
    if username in bot.cfg.get(cfg_key, []):
        bot.t.user_message(ctx['uid'], i18n.t(already_key, username=username))
        return
    bot.cfg.setdefault(cfg_key, []).append(username)
    bot.save_config()
    bot.t.user_message(ctx['uid'], i18n.t(confirm_key, username=username))


def toggle_pause(bot, ctx):
    """
    پاز/ادامه‌ی پخش -- تنها نقطه‌ی مشترک برای هر ورودی‌ای که این کار رو
    انجام می‌ده (الان فقط پیام خالی -> commands/pause_toggle.py؛ هر دستور
    دیگه‌ای هم که بعداً همین کار رو بخواد باید همینِ یکی رو صدا بزنه).

    طبق E6: فقط استاتوس عوض می‌شه (فوراً، نه با تأخیرِ تیکِ بعدیِ
    housekeeping که حداکثر نیم‌ثانیه طول می‌کشه) و کانال یه خط کوتاه
    می‌گیره -- نه جزئیات بیشتر.
    """
    if bot.player.current_url is None:
        bot.t.user_message(ctx["uid"], i18n.t("nothing_playing"))
        return
    is_paused = bot.player.toggle_pause()

    title = bot.last_track_info
    if title:
        status_text = i18n.t("status_paused" if is_paused else "status_playing", title=title)
        try:
            status_line.apply(bot.t, bot.cfg, status_text, paused=is_paused, visible=bot.status_visible)
        except Exception:
            logging_setup.log_debug("status refresh after pause/resume failed")

    key = "paused_by" if is_paused else "resumed_by"
    bot.channel_broadcast(i18n.t(key, nickname=ctx["nickname"]))


def run_channel_content_command(ctx, method_name, loading_key, capability_check=True,
                                empty_key="nothing_found"):
    """
    الگوی مشترک کمان‌های کانال (c/cv/cs/cl/lp): سرویس کانال فعلی رو
    می‌گیره، method_name رو روش صدا می‌زنه (با bot.last_channel_url)،
    نتیجه رو پخش می‌کنه، و دقیقاً دو پیام می‌فرسته: «دارم لود می‌کنم» و
    (broadcast_now_playing) «الان این پخش می‌شه» -- به‌جای یه پیامِ سومِ
    جدا که فقط تعداد صف رو می‌گفت.

    `empty_key` برای وقتیه که «خالی بودن» خودش یه جوابِ معنی‌داره، نه یه
    شکست -- مثل cl که خالی بودنش یعنی «کانال الان لایو نیست»، و پیام
    عمومیِ «چیزی پیدا نشد» اونجا گیج‌کننده‌ست.
    """
    bot = ctx["bot"]
    name, service = bot.require_channel_service(ctx)
    if not service:
        return
    if capability_check and not hasattr(service, method_name):
        bot.t.user_message(ctx["uid"], i18n.t("channel_not_supported", service=name))
        return

    bot.channel_broadcast(i18n.t(loading_key, nickname=ctx["nickname"]))
    try:
        results = getattr(service, method_name)(bot.last_channel_url)
        if not results:
            notify(bot, ctx, empty_key)
            return
        count = bot.load_and_play(results, private=False, service_name=name)

        # لینکِ کانال، نه یه عبارتِ سرچ -- مسیرِ رشدش همون مسیرِ پلی‌لیسته
        # (is_url=True رد می‌شه تا شاخه‌ی search_batch امتحان نشه).
        first = results[0] if isinstance(results, list) else results
        count = start_growth_session(bot, service, name, bot.last_channel_url, first, True, count)

        broadcast_now_playing(bot)
    except Exception as e:
        notify(bot, ctx, "generic_error", error=logging_setup.safe_error_text(e))


def run_search_and_play_command(ctx, search_fn, service_name, *, announce_key=None, announce_query=None,
                                 set_operation_desc=None):
    """
    الگوی مشترک کمان‌های «یه چیزی پیدا کن و پخشش کن» (ir/ird و مشابه):
    broadcast اختیاری قبل از شروع (پیامِ اول -- acknowledge_request)، صدا
    زدن search_fn() (بدون آرگومان -- معمولاً lambda: service.search(query)
    یا lambda: service.get_x(arg))، پخش نتیجه، broadcast «در حال پخش»
    (پیامِ دوم -- broadcast_now_playing)، و مدیریت خطا/set_operation.

    خطا هم به کانال می‌ره (notify)، نه فقط به درخواست‌کننده: بقیه هم
    منتظرِ همون درخواستی بودن که پیامِ اول اعلامش کرده بود.
    """
    bot = ctx["bot"]
    is_url = is_link(announce_query)
    if announce_key:
        acknowledge_request(bot, ctx, announce_query, service_name)
    if set_operation_desc:
        logging_setup.set_operation(set_operation_desc)
    try:
        result = search_fn()
        if not result:
            notify(bot, ctx, "nothing_found")
            return
        # لینکی که کاربر داده (مثلاً `ap <لینک>`، `ir <پروفایل>`) خصوصیه.
        count = bot.load_and_play(result, private=is_url, service_name=service_name)

        # n/b باید بعد از *هر* دستوری کار کنه، نه فقط بعد از p.
        service = bot.services.get(service_name)
        if service is not None:
            first = result[0] if isinstance(result, list) else result
            count = start_growth_session(bot, service, service_name, announce_query,
                                         first, is_url, count)

        broadcast_now_playing(bot)
        return count
    except Exception as e:
        notify(bot, ctx, "service_error", service=service_name, error=logging_setup.safe_error_text(e))
    finally:
        if set_operation_desc:
            logging_setup.set_operation("idle")

def run_instagram_command(ctx, name, action, *, target=None, needs_reels=True,
                          ok_key=None, fail_error=None):
    """
    الگوی مشترک دستورهای اینستاگرامِ ریلز (lr/dlr/fr/ufr/cr/rr/rl): چک
    ریل‌های لود‌شده، پیدا کردن pk هدف، پیدا کردن سشن اینستاگرامِ کاربر،
    ساختن client و مدیریت خطا (بدون لو دادن متنِ خامِ exception).

    target: None، "reel" (pk خودِ ریل) یا "user" (pk صاحبِ ریل).
    action(client, reels, pk): داخل try صدا زده می‌شه. اگه ok_key داده شده
    باشه، خروجی‌ش (truthy/falsy) با پیامِ ok_key یا command_error(fail_error)
    گزارش می‌شه؛ وگرنه خودِ action پیام رو می‌فرسته.

    importهای instagram_* تنبل‌اند تا استارتِ هزاران ربات سنگین‌تر نشه.
    """
    from core import instagram_bot
    bot, username, uid = ctx["bot"], ctx["username"], ctx["uid"]
    reels = getattr(bot, "_ig_reels", {}).get(username, [])
    if needs_reels and not reels:
        bot.t.user_message(uid, i18n.t("ig_no_reels"))
        return
    pk = None
    if target:
        # ریلِ جاری = همونی که صف الان پخش می‌کنه (n/b صف رو جلو می‌برن).
        item = reels[instagram_bot.current_reel_index(bot, username, reels)]
        if target == "reel":
            pk, missing = (item.pk if hasattr(item, "pk") else None), "reel_pk"
        else:
            pk = item.user.pk if hasattr(item, "user") and hasattr(item.user, "pk") else None
            missing = "user_pk"
        if not pk:
            bot.t.user_message(uid, i18n.t("command_error", error=missing))
            return
    client, error = instagram_bot.client_for(bot, username)
    if error:
        bot.t.user_message(uid, error)
        return
    try:
        result = action(client, reels, pk)
        if ok_key is not None:
            if result:
                bot.t.user_message(uid, i18n.t(ok_key))
            else:
                bot.t.user_message(uid, i18n.t("command_error", error=fail_error))
    except Exception as e:
        logging_setup.log_debug(f"{name}: {e}")
        bot.t.user_message(uid, i18n.t("command_error", error=logging_setup.safe_error_text(e)))


def channel_playlists(ctx):
    """
    (سرویس، لیست پلی‌لیست‌های کانال) برای cp/cpl/nn/bb، یا None بعد از
    فرستادن پیامِ خطای مناسب (سرویس نیست، پلی‌لیست پشتیبانی نمی‌شه، خطا، خالی).
    """
    bot = ctx["bot"]
    name, service = bot.require_channel_service(ctx)
    if not service:
        return None
    if not hasattr(service, 'get_channel_playlists'):
        bot.t.user_message(ctx['uid'], i18n.t('channel_playlists_not_supported', service=name))
        return None
    try:
        playlists = service.get_channel_playlists(bot.last_channel_url)
    except Exception as e:
        bot.t.user_message(ctx['uid'], i18n.t('generic_error', error=logging_setup.safe_error_text(e)))
        return None
    if not playlists:
        bot.t.user_message(ctx['uid'], i18n.t('no_channel_playlists'))
        return None
    return service, playlists


def run_service_url_command(ctx, usage, service_name, label, domain):
    """
    الگوی مشترک sc/tk: «<دستور> <لینک>» با چک دامنه، اضافه‌کردن https اگه
    لینک بدون پروتکل بود (لازمه تا «لینکِ کاربر = خصوصی» و مسیرِ رشد
    پلی‌لیست درست تشخیص داده بشن)، و پخش با رشد صف.
    """
    bot = ctx["bot"]
    args = ctx["args"]

    if not args:
        bot.t.user_message(ctx["uid"], i18n.t("usage_generic", usage=usage))
        return

    url = args[0].strip()
    if domain not in url.lower():
        bot.t.user_message(ctx["uid"], i18n.t("invalid_service_url", service=label))
        return
    if not is_link(url):
        url = "https://" + url

    service = bot.services.get(service_name)
    if not service:
        bot.t.user_message(ctx["uid"], i18n.t("service_not_loaded", service=label))
        return

    run_search_and_play_command(
        ctx, lambda: service.search(url), service_name,
        announce_key="request_ack_link", announce_query=url,
        set_operation_desc=f"Resolving {label}...",
    )


def _owning_service_for_url(bot, url):
    """
    دقیق‌ترین سرویسِ لودشده‌ای که owns_url(url) بگه «این لینک مالِ منه»،
    به‌همراه اسمش. اگه چند سرویس ادعا کنن (مثلاً youtube هم youtube.com
    رو می‌شناسه هم music.youtube.com زیرمجموعه‌شه)، اونی که طولانی‌ترین
    URL_MARKER رو داره (خاص‌ترین) برنده می‌شه -- وگرنه music.youtube.com
    همیشه به‌جای youtubemusic می‌رفت سراغ youtube (چون فایل‌ها به ترتیب
    الفبا لود می‌شن و youtube قبل از youtubemusic میاد).

    خروجی: (service, service_name) یا (None, None).
    """
    low = (url or "").lower()
    best = None  # (marker_len, name, service)
    for name, service in (getattr(bot, "services", None) or {}).items():
        owns = getattr(service, "owns_url", None)
        if not callable(owns):
            continue
        try:
            if not owns(url):
                continue
        except Exception:
            continue
        markers = getattr(service, "URL_MARKERS", None) or ()
        marker_len = max((len(m) for m in markers if m and m.lower() in low), default=0)
        if best is None or marker_len > best[0]:
            best = (marker_len, name, service)
    if best is None:
        return None, None
    _, name, service = best
    return service, name


def _confirm_playback(bot, timeout=8.0):
    """
    بعد از دادنِ لینکِ *خام* به mpv: آیا mpv واقعاً بازش کرد؟ mpv فایل رو
    غیرهمزمان باز می‌کنه و اگه نتونه، current_url دوباره None می‌شه. تا
    مهلت صبر می‌کنیم؛ طول/بافر-نبودن یعنی موفق، رها‌شدنِ فایل یعنی شکست.
    استریم زنده‌ی کند (هنوز بافر، ولی فایل هنوز لود) موفق حساب می‌شه.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            current = bot.player.current_url
            if bot.player.duration_seconds or (current and not bot.player.is_buffering):
                return True
            if current is None and time.time() - start > 1.0:
                return False
        except Exception:
            return True  # نمی‌تونیم بفهمیم؛ ادعای شکست نمی‌کنیم.
        time.sleep(0.25)
    try:
        return bot.player.current_url is not None
    except Exception:
        return True


def _generic_item(url):
    """لوله‌ی عمومی (بدون سرویس): dict آیتم یا None."""
    # لینکِ اشتراک (Dropbox ...mp3?dl=0) پسوندِ رسانه داره ولی صفحه‌ی HTML
    # می‌ده؛ اول به لینکِ دانلودِ مستقیم بازنویسی می‌شه.
    direct = link_resolver.rewrite_share_link(url)
    if link_resolver.looks_like_direct_media(direct):
        return {"url": direct, "title": None}
    return link_resolver.resolve(url)


def resolve_playable(bot, url):
    """
    یه لینکِ صفحه (مثلاً چیزی که af/aff ذخیره کرده) رو به آیتمِ واقعاً
    قابل‌پخش تبدیل می‌کنه -- (item, public_url) یا (None, None).

    چرا لازم بود: فروریت (core/accounts.py) فقط public_url (لینکِ صفحه،
    نه لینکِ استریم) رو ذخیره می‌کنه، چون لینکِ استریمِ واقعیِ سرویس‌هایی
    مثل یوتیوب چند ساعت بعد منقضی می‌شه -- ذخیره‌ی همون لینکِ منقضی‌شونده
    یعنی فروریتی که امروز ساخته شد، فردا پخش نمی‌شد. قبلاً sf.py همون
    public_url رو مستقیم به‌عنوانِ لینکِ پخش به mpv می‌داد (که hook خودِ
    yt-dlp mpv عمداً خاموشه -- core/mpv/player.py)، یعنی فروریتِ هیچ
    سرویسی (یوتیوب/ساندکلاد/...) اصلاً پخش نمی‌شد؛ فقط لینکِ مستقیمِ خامی
    که از اول هم قابل‌پخش بود کار می‌کرد. همون منطقِ سه‌مرحله‌ایِ
    run_link_command اینجا هم اجرا می‌شه، بدونِ پیامِ کانال (فراخوان‌ها
    ساکتن، چون این تابع برای هر آیتمِ یه پلی‌لیست صدا زده می‌شه).
    """
    service, service_name = _owning_service_for_url(bot, url)
    if service is not None:
        try:
            result = service.search(url)
        except Exception:
            result = None
        if result:
            first = result[0] if isinstance(result, list) else result
            return first, service_name
    item = _generic_item(url)
    if item and item.get("url"):
        return item, None
    return {"url": url}, None


def run_link_command(bot, ctx, url):
    """
    نقطه‌ی مشترکِ پردازشِ یک لینکِ تکی که خودِ کاربر فرستاده -- چه به‌شکلِ
    پیستِ خام (bot.py::on_user_msg، بدون هیچ دستوری) چه با دستورِ `u <لینک>`
    (commands/u.py، فقط یه alias). هدف: هر لینکی *پخش بشه* و پلی‌لیست‌ها
    کامل لود بشن.

    ترتیب (هیچ مرحله‌ای بدونِ امتحانِ بعدی «پیدا نشد» نمی‌ده):
      1) سرویسِ لودشده‌ای که owns_url بگه مالِ منه (نتیجه‌ی غنی: عنوان،
         channel_url، رشدِ پلی‌لیست با n؛ لینکِ list= = کلِ پلی‌لیست)
      2) اگه سرویس چیزی نداد، لوله‌ی عمومی (core.link_resolver): مدیای
         مستقیم/probe -> yt-dlp -> اسکن HTML (+iframe) -> مرورگر headless
      3) آخرین راه: لینکِ خام به mpv. mpv خیلی از لینک‌های بی‌پسوند
         (http://host:port/name) رو پخش می‌کنه. فقط اگه mpv هم بازش نکرد،
         یه پیامِ کوتاه (بدون لینک و بدون stack trace) به کانال.

    همیشه private=True: لینکی که خودِ کاربر فرستاده هیچ‌وقت نباید با k به
    کسی داده بشه یا وارد تاریخچه‌ی عمومی بشه.
    """
    acknowledge_request(bot, ctx, url)
    username = ctx.get("username") or ctx.get("nickname", "")
    logging_setup.set_operation(f"resolving link '{url}' (requested by {username})")
    try:
        service, service_name = _owning_service_for_url(bot, url)
        if service is not None:
            try:
                result = service.search(url)
            except Exception:
                logging_setup.log_debug(f"[link] service '{service_name}' claimed url but search failed")
                result = None
            if result:
                first = result[0] if isinstance(result, list) else result
                if isinstance(first, dict) and first.get("channel_url"):
                    bot.last_channel_url = first["channel_url"]
                count = bot.load_and_play(result, private=True, service_name=service_name)
                count = start_growth_session(bot, service, service_name, url, first, True, count)
                broadcast_now_playing(bot)
                return
            logging_setup.log_debug(f"[link] service '{service_name}' found nothing; trying generic pipeline")

        item = _generic_item(url)
        raw = not item or not item.get("url")
        if raw:
            item = {"url": url, "title": None}
        bot.load_and_play(item.get("items") or item, private=True)
        if raw and not _confirm_playback(bot):
            notify(bot, ctx, "link_unplayable")
            return
        broadcast_now_playing(bot)
    except Exception as e:
        notify(bot, ctx, "link_play_failed", error=logging_setup.safe_error_text(e))
    finally:
        logging_setup.set_operation("idle")


def no_services_message(bot):
    """
    چرا هیچ سرویسی نیست؟

    لایسنسِ منقضی ولی داخل مهلت، ربات رو بالا می‌آره ولی
    license_gate همه‌ی سرویس‌ها رو حذف می‌کنه. اون‌وقت پیام
    «هیچ سرویسی لود نشده» کاربر رو دنبال باگی می‌فرسته که
    وجود نداره -- درحالی که یه تمدید ساده حلش می‌کنه.
    """
    state = getattr(bot, "license", None)
    try:
        expired = state is not None and state.is_expired()
    except Exception:
        expired = False
    return i18n.t("license_expired_no_services" if expired else "no_services")


# ---------------------------------------------------------------- حریم لینک

#: سرویس‌هایی که محتواشون رو صاحب ربات خریده (مستند، IPTV). لینکشون به هیچ
#: کس داده نمی‌شه و فایلشون هم با dl توی کانال آپلود نمی‌شه -- آپلود یعنی
#: هر کسی توی کانال کل فایلِ پولی رو برمی‌داره.
PAID_PRIVATE_SERVICES = frozenset({"documentary", "iptv"})


def is_link(text):
    value = (text or "").strip().lower()
    return value.startswith("http://") or value.startswith("https://")


def _looks_like_url_tail(text):
    """
    mpv's media-title for a stream with no metadata is the last path segment
    of the URL, e.g. "webm&rqh=1&gir=yes&sig=..." for a googlevideo link.
    That is not a title: no spaces, query-string shaped.
    """
    value = (text or "").strip()
    return bool(value) and not any(c.isspace() for c in value) \
        and "&" in value and "=" in value


def is_shareable(meta):
    """
    لینکِ این ترک رو می‌شه به کسی داد (k، i، علاقه‌مندی‌ها)؟

    نه برای لینکی که خود کاربر فرستاده (private)، نه برای محتوای پولی.
    """
    if not meta:
        return False
    if meta.get("private") or meta.get("service") in PAID_PRIVATE_SERVICES:
        return False
    return bool(meta.get("public_url"))


def is_downloadable(meta):
    """
    فایلِ این ترک رو می‌شه با dl توی کانال گذاشت؟

    لینکی که کاربر خودش داده آره -- مال خودشه. محتوای پولی نه.
    """
    return bool(meta) and meta.get("service") not in PAID_PRIVATE_SERVICES


def display_title(meta, candidate=None):
    """
    اسمی که می‌شه به همه نشون داد: استاتوس، «Now playing» کانال، صف.

    هیچ‌وقت لینک خامِ یه ترک غیرقابل‌اشتراک برنمی‌گردونه. دو جا لینک
    یواشکی جای عنوان می‌نشست: fallback_label (که معمولاً خودِ لینکه) و
    media-title خودِ mpv (که بدون متادیتا به اسم فایل یا خودِ آدرس
    برمی‌گرده).

    candidate: عنوانی که از جای دیگه اومده (مثلاً mpv)؛ اگه نبود از meta.
    """
    meta = meta or {}
    shareable = is_shareable(meta)
    for value in (meta.get("title"), candidate, meta.get("fallback_label")):
        if not value:
            continue
        if value is candidate and _looks_like_url_tail(value):
            continue
        if is_link(value) and not shareable:
            continue
        return value
    if meta.get("private") or meta.get("service") in PAID_PRIVATE_SERVICES:
        return i18n.t("private_track_label")
    return None
