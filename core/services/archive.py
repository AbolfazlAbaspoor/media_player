"""
سرویس archive.org: آرشیو عمومی فیلم، موسیقی، و رادیوهای قدیمی.

استفاده:
    w archive  +  p <عبارت>
    p https://archive.org/details/<identifier>

چرا مهمه: بزرگ‌ترین منبعِ آزادِ فیلم و موسیقیِ بدون کپی‌رایته -- از
فیلم‌های public domain تا کنسرت‌های ضبط‌شده.

## چرا جستجو مستقیم به yt-dlp نمی‌ره

yt-dlp برای archive.org فقط اکسترکتور *آیتم* داره
(archive.org/details/<id> یا /embed/<id>) -- برای جستجو هیچ اکسترکتوری
نداره. قبلاً SEARCH_URL_TEMPLATE مستقیم آدرسِ advancedsearch.php (که
JSON برمی‌گردونه، نه یه صفحه‌ی قابل‌استخراج) رو به اکسترکتور عمومیِ
yt-dlp می‌داد؛ اکسترکتور عمومی روی JSON چیزی برای استخراج پیدا نمی‌کرد
و با خطای مبهمِ «internal error» رد می‌شد. نتیجه: جستجو همیشه هیچی
برنمی‌گردوند.

راه‌حل -- دقیقاً همون الگوی core/services/aparat.py: خودمون JSON رو
می‌گیریم (با core.net، همون مسیر پروکسی‌دارِ بقیه‌ی سرویس‌ها)، شناسه‌ها
رو در میاریم، و stub می‌سازیم؛ resolve نهاییِ هر آیتم رو خودِ اکسترکتور
archive.org yt-dlp (که سالمه) انجام می‌ده.
"""

import json
import urllib.parse

from core import logging_setup
from core import net
from core.services._ytdlp_service import YtdlpService

SEARCH_API = (
    "https://archive.org/advancedsearch.php"
    "?q={query}&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=creator"
    "&rows={rows}&page=1&output=json"
)
DETAILS_URL = "https://archive.org/details/{identifier}"


class ArchiveOrg(YtdlpService):
    SERVICE_NAME = "archive"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("archive.org",)
    AUDIO_ONLY = False

    def _search_stubs(self, query, count, interactive=False):
        """
        نتایج جستجوی archive.org به‌صورت stub -- از advancedsearch.php،
        نه از اکسترکتور جستجوی yt-dlp (که وجود نداره).
        """
        url = SEARCH_API.format(query=urllib.parse.quote(query), rows=max(count, 1))
        try:
            _, body = net.fetch_text(url, label="archive")
            payload = json.loads(body)
        except Exception as e:
            logging_setup.log_debug(f"[archive] search API failed: {e}")
            return []

        docs = ((payload.get("response") or {}).get("docs")) or []
        stubs = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            identifier = doc.get("identifier")
            if not identifier:
                continue
            title = doc.get("title")
            if isinstance(title, list):
                title = title[0] if title else None
            creator = doc.get("creator")
            if isinstance(creator, list):
                creator = creator[0] if creator else None
            stubs.append({
                "id": identifier,
                "url": DETAILS_URL.format(identifier=identifier),
                "webpage_url": DETAILS_URL.format(identifier=identifier),
                "title": title or identifier,
                "uploader": creator,
            })
            if len(stubs) >= count:
                break
        return stubs
