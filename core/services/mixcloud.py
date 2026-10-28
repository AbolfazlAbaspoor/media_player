"""
سرویس Mixcloud: دی‌جی‌ست، رادیو شو، و پادکست‌های بلند.

استفاده:
    w mixcloud  +  p <عبارت>
    p https://www.mixcloud.com/user/show-name/

Mixcloud برای ست‌های طولانی (یکی دو ساعته) ساخته شده، پس برای پخش
پس‌زمینه‌ی طولانی توی کانال گزینه‌ی خوبیه.

## چرا جستجو از API عمومی میاد، نه از خود صفحه

yt-dlp برای Mixcloud فقط اکسترکتورهای *آیتم* داره (mixcloud،
mixcloud:playlist، mixcloud:user) -- برای جستجو هیچ‌کدوم نیست.
mixcloud.com/search/ یه صفحه‌ی کاملاً کلاینت-ساید (React) است؛ اکسترکتور
عمومیِ yt-dlp هیچ لینک ویدیویی توی HTML اولیه پیدا نمی‌کنه، پس جستجو
همیشه خالی برمی‌گشت (همون الگوی خرابیِ archive.org قبل از این پچ).

راه‌حل: API عمومی و بدون کلیدِ Mixcloud (api.mixcloud.com/search) --
دقیقاً همون الگوی core/services/aparat.py.
"""

import json
import urllib.parse

from core import logging_setup
from core import net
from core.services._ytdlp_service import YtdlpService

SEARCH_API = "https://api.mixcloud.com/search/?q={query}&type=cloudcast&limit={limit}"


class Mixcloud(YtdlpService):
    SERVICE_NAME = "mixcloud"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("mixcloud.com",)
    AUDIO_ONLY = True

    def _search_stubs(self, query, count, interactive=False):
        url = SEARCH_API.format(query=urllib.parse.quote(query), limit=max(count, 1))
        try:
            _, body = net.fetch_text(url, label="mixcloud")
            payload = json.loads(body)
        except Exception as e:
            logging_setup.log_debug(f"[mixcloud] search API failed: {e}")
            return []

        stubs = []
        for item in (payload.get("data") or []):
            if not isinstance(item, dict):
                continue
            webpage_url = item.get("url")
            if not webpage_url:
                continue
            user = item.get("user") or {}
            stubs.append({
                "id": item.get("key") or webpage_url,
                "url": webpage_url,
                "webpage_url": webpage_url,
                "title": item.get("name") or "Unknown",
                "uploader": user.get("name") or user.get("username"),
                "channel_url": user.get("url"),
            })
            if len(stubs) >= count:
                break
        return stubs
