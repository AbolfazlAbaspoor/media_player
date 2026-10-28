"""
پخش زنده‌ی کانال‌های تلویزیون/رادیوی اینترنتی (IPTV).

    tv                  وضعیت کوتاه (تعداد منبع/کانال) + راهنما
    tv <متن>            سرچ نام کانال (تحمل‌پذیر به بزرگی/کوچکی، ی/ي، ک/ك،
                        رقم فارسی/عربی، و تطبیق جزئی) و نمایش یه صفحه نتیجه
    tv <متن> <صفحه>     همون سرچ، صفحه‌ی دیگه
    tv <شماره>          پخش کانال شماره‌ی داده‌شده از آخرین لیستِ نشون‌داده‌شده
    tv list [صفحه]      همه‌ی کانال‌ها، صفحه‌بندی‌شده

بعد از یه لیست *یا* یه پخش، ربات توی «حالت تلویزیون» می‌مونه: فرستادن یه
عدد خام هم دقیقاً همین «tv <شماره>» رو انجام می‌ده، و n/b بین کانال‌های
همون لیست جابه‌جا می‌شن. پخش هر چیز دیگه‌ای (سرچ یوتیوب، لینک، مستند) این
حالت رو می‌بنده. منطق اصلی توی core/iptv.py است، چون مسیر «عدد خام» توی
bot.py هم از همون استفاده می‌کنه.

هیچ‌جا آدرس واقعیِ استریم/پلی‌لیست چاپ نمی‌شه (core/iptv.py را ببین).
"""

from core import command_helpers
from core import i18n
from core import iptv
from core import logging_setup

NAME = "tv"
USAGE = "tv [search text | number | list [page]]"

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _to_ascii_digits(text):
    return (text or "").translate(_DIGIT_MAP)


def _as_page_number(text):
    """رشته -> شماره‌صفحه، یا None اگه عدد نبود (رقم فارسی/عربی هم قبوله)."""
    normalized = _to_ascii_digits(text)
    return int(normalized) if normalized.isdigit() else None


def _show_list(bot, uid, header_key, header_kwargs, channels_page):
    lines = [i18n.t(header_key, **header_kwargs)]
    for i, ch in enumerate(channels_page, start=1):
        lines.append(f"{i}. {ch.get('name') or '?'}")
    bot.send_long_text(lambda text: bot.t.user_message(uid, text), "\n".join(lines))


def _play_number(bot, ctx, number):
    uid = ctx["uid"]
    try:
        channel = iptv.play(bot, number, requested_by=ctx.get("username"))
    except iptv.IPTVError as e:
        bot.t.user_message(uid, str(e))
        return
    except Exception as e:
        command_helpers.notify(bot, ctx, "generic_error", error=logging_setup.safe_error_text(e))
        return
    iptv.announce_playing(bot, channel, ctx["nickname"])


def _run_status(bot, uid):
    try:
        total = len(iptv.fetch_channels(bot))
    except iptv.IPTVError:
        total = 0
    bot.t.user_message(uid, i18n.t(
        "tv_status", sources=len(iptv.sources(bot)), channels=total, usage=USAGE))


def _run_list(bot, uid, page):
    try:
        channels = iptv.fetch_channels(bot)
    except iptv.IPTVError as e:
        bot.t.user_message(uid, str(e))
        return
    page_items, page, pages, total = iptv.paginate(channels, page, iptv.page_size(bot))
    iptv.set_list(bot, page_items)
    _show_list(bot, uid, "tv_list_header", {"page": page, "pages": pages, "total": total}, page_items)


def _run_search(bot, ctx, query, page):
    uid = ctx["uid"]
    try:
        results = iptv.search(bot, query)
    except iptv.IPTVError as e:
        bot.t.user_message(uid, str(e))
        return
    if not results:
        command_helpers.notify(bot, ctx, "nothing_found")
        return
    page_items, page, pages, total = iptv.paginate(results, page, iptv.page_size(bot))
    iptv.set_list(bot, page_items)
    _show_list(bot, uid, "tv_search_header",
               {"query": query, "page": page, "pages": pages, "total": total}, page_items)


def run(ctx):
    bot, uid = ctx["bot"], ctx["uid"]
    args = ctx.get("args") or []

    if not args:
        _run_status(bot, uid)
        return

    # tv <عدد>: دقیقاً همون مسیر عدد خام (core/iptv.play).
    if len(args) == 1 and _as_page_number(args[0]) is not None:
        _play_number(bot, ctx, _as_page_number(args[0]))
        return

    if args[0].lower() in ("list", "لیست"):
        page = _as_page_number(args[1]) if len(args) > 1 else None
        _run_list(bot, uid, page or 1)
        return

    # آخرین کلمه اگه عدد باشه یعنی شماره‌ی صفحه؛ بقیه‌اش متنِ سرچه.
    query_words = list(args)
    page = 1
    if len(query_words) > 1:
        maybe_page = _as_page_number(query_words[-1])
        if maybe_page is not None:
            page = maybe_page
            query_words.pop()
    _run_search(bot, ctx, " ".join(query_words), page)
