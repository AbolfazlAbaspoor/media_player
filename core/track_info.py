"""
متن دستورهای i (اطلاعات کامل) و di (توضیحات) از روی متادیتای نرمالِ ترک.

هر دو فقط از `bot.track_meta[idx]["info"]` (که موقع resolve پر شده، بدون
درخواست اضافه) و پلیر می‌خونن -- هیچ چیزشون مخصوص یه سرویس نیست. فیلدی که
مقدار نداره اصلاً نمایش داده نمی‌شه. لینک منبع فقط برای ترکِ قابل‌اشتراک
(command_helpers.is_shareable) چاپ می‌شه؛ لینک پیست‌شده/پولی/خصوصی هیچ‌وقت.
"""

from core import command_helpers, i18n, track_meta

#: بیشترین تعداد تگ توی i (بقیه با «+N» خلاصه می‌شن).
MAX_TAGS = 12

#: کلیدهای i18n به‌صورت لیترال (تستِ «هر کلید توی کد تعریف شده» فقط
#: literalها رو می‌بینه).
_LABEL_KEYS = {
    "title": "info_label_title", "service": "info_label_service", "link": "info_label_link",
    "uploader": "info_label_uploader", "uploaded": "info_label_uploaded",
    "position": "info_label_position", "duration": "info_label_duration",
    "view_count": "info_label_view_count", "like_count": "info_label_like_count",
    "dislike_count": "info_label_dislike_count", "comment_count": "info_label_comment_count",
    "repost_count": "info_label_repost_count", "live": "info_label_live",
    "categories": "info_label_categories", "tags": "info_label_tags",
    "description": "info_label_description", "format": "info_label_format",
    "playlist": "info_label_playlist", "age_limit": "info_label_age_limit",
    "license": "info_label_license", "availability": "info_label_availability",
    "source": "info_label_source",
}
_LIVE_KEYS = {
    "is_live": "info_live_is_live", "was_live": "info_live_was_live",
    "not_live": "info_live_not_live", "is_upcoming": "info_live_is_upcoming",
    "post_live": "info_live_post_live",
}


def current_track(bot):
    """(meta, info) ترکِ در حال پخش؛ هر دو همیشه dict هستن."""
    idx = bot.queue.index
    meta = {}
    if idx is not None and 0 <= idx < len(bot.track_meta):
        meta = bot.track_meta[idx] or {}
    return meta, dict(meta.get("info") or {})


def _num(value, lang):
    return track_meta.localize_digits(track_meta.format_count(value), lang)


def _digits(text, lang):
    return track_meta.localize_digits(text, lang)


def _line(key, value):
    return f"{i18n.t(_LABEL_KEYS[key])}: {value}"


def _rate(value):
    return f"{value:g}"


def _format_summary(info, lang):
    """قالب/کدک/بیت‌ریت/رزولوشن/حجم در یک خط."""
    parts = []
    if info.get("ext"):
        parts.append(info["ext"])
    if info.get("acodec"):
        parts.append(info["acodec"])
    if info.get("vcodec"):
        parts.append(info["vcodec"])
    if info.get("resolution"):
        parts.append(info["resolution"])
    if info.get("fps"):
        parts.append(f"{_rate(info['fps'])} fps")
    if info.get("abr"):
        parts.append(f"{_rate(round(info['abr']))} kbps")
    elif info.get("tbr"):
        parts.append(f"{_rate(round(info['tbr']))} kbps")
    if info.get("asr"):
        parts.append(f"{_rate(info['asr'])} Hz")
    if info.get("filesize"):
        parts.append(track_meta.format_size(info["filesize"]))
    return _digits(" | ".join(parts), lang) if parts else None


def build_info_text(bot):
    """متن کاملِ دستور i، یا None اگه چیزی پخش نمی‌شه."""
    player = bot.player
    if not player.current_url:
        return None

    lang = i18n.current_language()[0]
    meta, info = current_track(bot)

    # مشخصات فنیِ زنده‌ی mpv فقط جای خالی‌ها رو پر می‌کنه (لینک مستقیم/رادیو/IPTV).
    live = {}
    getter = getattr(player, "stream_info", None)
    if callable(getter):
        try:
            live = getter() or {}
        except Exception:
            live = {}
    if isinstance(live, dict):
        for key, value in live.items():
            info.setdefault(key, value)
        if "width" in live and "height" in live:
            info.setdefault("resolution", f"{live['width']}x{live['height']}")

    title = command_helpers.display_title(meta) or "Unknown"
    lines = [_line("title", title)]

    service = meta.get("service") or info.get("service")
    if service:
        lines.append(_line("service", service))

    if command_helpers.is_shareable(meta) and meta.get("public_url"):
        lines.append(_line("link", meta["public_url"]))

    uploader, channel = info.get("uploader"), info.get("channel")
    if uploader and channel and uploader != channel:
        lines.append(_line("uploader", f"{uploader} ({channel})"))
    elif uploader or channel:
        lines.append(_line("uploader", uploader or channel))

    when = track_meta.format_date(info.get("timestamp"))
    if when:
        lines.append(_line("uploaded", _digits(when, lang)))

    pos = player.position_seconds
    dur = player.duration_seconds if player.duration_seconds is not None else info.get("duration")
    if pos is not None:
        lines.append(_line("position", _digits(bot.format_time(pos), lang)))
    if dur is not None:
        lines.append(_line("duration", _digits(bot.format_time(dur), lang)))

    for key in ("view_count", "like_count", "dislike_count", "comment_count", "repost_count"):
        if info.get(key) is not None:
            lines.append(_line(key, _num(info[key], lang)))

    status = info.get("live_status")
    if status:
        label = i18n.t(_LIVE_KEYS[status]) if status in _LIVE_KEYS else status
        lines.append(_line("live", label))

    if info.get("categories"):
        lines.append(_line("categories", ", ".join(info["categories"])))
    tags = info.get("tags") or []
    if tags:
        shown = ", ".join(tags[:MAX_TAGS])
        if len(tags) > MAX_TAGS:
            shown += f" (+{_digits(len(tags) - MAX_TAGS, lang)})"
        lines.append(_line("tags", shown))

    if info.get("description"):
        lines.append(_line("description", i18n.t(
            "info_description_length",
            count=_num(len(info["description"]), lang))))

    fmt = _format_summary(info, lang)
    if fmt:
        lines.append(_line("format", fmt))

    if info.get("playlist_title"):
        lines.append(_line("playlist", info["playlist_title"]))
    if info.get("age_limit"):
        lines.append(_line("age_limit", _digits(f"{info['age_limit']}+", lang)))
    if info.get("license"):
        lines.append(_line("license", info["license"]))
    if info.get("availability"):
        lines.append(_line("availability", info["availability"]))
    if info.get("extractor"):
        lines.append(_line("source", info["extractor"]))

    return "\n".join(lines)


def build_description_text(bot):
    """
    (kind, text): kind یکی از "nothing" / "none" / "ok".
    توضیحات از متادیتای نرمال می‌آد؛ برای همه‌ی انواع ترک یکسانه.
    """
    if not bot.player.current_url:
        return "nothing", i18n.t("nothing_playing")
    _meta, info = current_track(bot)
    description = (info.get("description") or "").strip()
    if not description:
        return "none", i18n.t("info_no_description")
    return "ok", i18n.t("info_description_header", description=description)


def deliver(bot, uid, text):
    """یک پیام به درخواست‌کننده؛ متن بلند از مسیر مشترکِ send_long_text تکه می‌شه."""
    sender = getattr(bot, "send_long_text", None)
    if callable(sender) and len(text) > 300:
        sender(lambda part: bot.t.user_message(uid, part), text)
    else:
        bot.t.user_message(uid, text)
