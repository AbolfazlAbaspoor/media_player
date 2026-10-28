"""
توضیح یه سرویس (پیش‌فرض: سرویس فعال فعلی) و دستورات مرتبط باهاش.

Usage:
    wh              -> توضیح سرویس فعال (همونی که w نشونش می‌ده)
    wh <name>       -> توضیح یه سرویس مشخص (حتی اگه با w قابل‌انتخاب نباشه)
"""

from core import i18n
from core import command_helpers

NAME = 'wh'
ADMIN_ONLY = False
USAGE = 'wh [service name]  (explain a service and its commands)'

SERVICE_INFO = {
    "youtube": {
        "description": "Full text search, playlists, channels, mixes.",
        "commands": [
            "p <query or url> - search or play a URL",
            "n / b - next / previous track (also grows search results)",
            "w [name|number] - switch active service",
            "c - queue all channel content",
            "cv - queue channel videos",
            "cs - queue channel shorts",
            "cp / cpl [number] - channel playlists",
            "pl - load the YouTube mix for the current track",
        ],
    },
    "instagram": {
        "description": "Direct links only (no text search) -- profile reels / hashtag feeds.",
        "commands": [
            "ir <username> - queue a profile's reels feed",
            "ird <hashtag> - queue a multi-creator reels feed from a hashtag",
            "ig <username> <password> - login / session for private content",
            "n / b - next / previous in the loaded queue",
        ],
    },
    "tiktok": {
        "description": "Direct video links only (no text search).",
        "commands": ["tk <url> - play a TikTok video or a user's videos", "n / b - next / previous in the loaded queue"],
    },
    "soundcloud": {
        "description": "Text search (select it with w, then p), tracks, sets and artist pages.",
        "commands": [
            "p <query> - search SoundCloud when it is the active service",
            "sc <url> - play a track, set or artist page",
            "n / b - next / previous (sets and results keep loading)",
        ],
    },
    "spotify": {
        "description": "Plays Spotify track, album, playlist and artist links: the track list comes from Spotify and each song is played from YouTube (Spotify audio itself is DRM-protected). No text search.",
        "commands": [
            "spt <url> - play a track, album or playlist",
            "spt info <url> - list the tracks without playing",
            "n / b - next / previous (the rest of an album or playlist keeps loading)",
        ],
    },
}


def run(ctx):
    bot = ctx["bot"]
    args = ctx["args"]

    if args:
        query = args[0].lower()
        if query not in bot.services:
            bot.t.user_message(ctx["uid"], i18n.t("wh_unknown_service", query=query, options=", ".join(bot.services.keys())))
            return
        name = query
    else:
        name, _service = bot.active_service()
        if not name:
            bot.t.user_message(ctx["uid"], command_helpers.no_services_message(bot))
            return

    info = SERVICE_INFO.get(name, {"description": "(no info available for this service)", "commands": []})
    lines = [i18n.t("service_help_header", service=name, description=info["description"])]
    lines.extend(f"  {c}" for c in info["commands"])
    bot.send_long_text(lambda text: bot.t.user_message(ctx["uid"], text), "\n".join(lines))
