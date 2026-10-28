"""
تاریخچه‌ی پخش: آخرین N آهنگی که این ربات پخش کرده، برای دستور hi.

فایل: data/<host>_<port>/<bot>/history.json -- مخصوص هر ربات. فقط
آهنگ‌های عمومی (public_url دارن) ثبت می‌شن؛ لینک‌های خصوصی/مستقیم مثل
همه‌جای دیگه‌ی پروژه (k، fav) نادیده گرفته می‌شن.
"""

import json
import os
import time

from core import paths
from core import logging_setup

MAX_ENTRIES = 50


def _path(bot):
    return os.path.join(bot.bot_dir, 'history.json')


def load(bot):
    path = _path(bot)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        logging_setup.log_debug(f"loading history.json failed ({path})")
        return []


def record(bot, title, public_url):
    """یه آهنگ رو به ابتدای تاریخچه اضافه می‌کنه (جدیدترین اول)."""
    if not public_url:
        return
    try:
        entries = load(bot)
        # اگه همین لینک قبلاً (نزدیک‌ترین آیتم) ثبت شده، تکراری اضافه نکن
        # -- مثلاً وقتی 'p' بدون آرگومان همون آهنگ رو دوباره پخش می‌کنه.
        if entries and entries[0].get('url') == public_url:
            return
        entries.insert(0, {"title": title, "url": public_url, "played_at": time.time()})
        entries = entries[:MAX_ENTRIES]
        path = _path(bot)
        paths.write_json_atomic(path, entries)
    except Exception:
        logging_setup.log_debug("recording playback history failed")
