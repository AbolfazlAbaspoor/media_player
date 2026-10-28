"""
سرویس تلوبیون: آرشیو شبکه‌های تلویزیون ایران.

استفاده:
    w telewebion  +  p <عبارت>                -> جستجو در آرشیو
    p https://telewebion.ir/episode/162175536  -> یه قسمت مشخص

## نکته‌ی دامنه

دامنه‌ی درست **telewebion.ir** است، نه .com. اکسترکتور yt-dlp هم فقط
همین رو می‌شناسه، پس لینک‌های .com قبل از پخش ترجمه می‌شن -- وگرنه
کاربر یه لینک کاملاً معتبر می‌داد و «پشتیبانی نمی‌شود» می‌گرفت.

## جستجو

تلوبیون API عمومی REST نداره؛ همون GraphQL ای که خود yt-dlp برای گرفتن
مشخصات قسمت‌ها استفاده می‌کنه تنها راه رسمیه. همون قرارداد فراخوانی
این‌جا تکرار شده.

اگه اسکیمای سمت سرور عوض بشه، جستجو «نتیجه‌ای نیست» می‌ده و کرش
نمی‌کنه -- پخش لینک مستقیم که مسیر جداگانه‌ایه دست‌نخورده کار می‌کنه.

## تلوبیون پلاس

اضافه نشده. بخش پلاس اشتراکیه و پشت لاگین و DRM است؛ بدون حساب
پرداخت‌شده هیچ مسیر فنی‌ای براش وجود نداره.
"""

import json
import urllib.request

from core import logging_setup
from core import proxy_state
from core.services._ytdlp_service import YtdlpService

GRAPHQL_URL = "https://graph.telewebion.ir/graphql"
EPISODE_URL = "https://telewebion.ir/episode/{episode_id}"

_SEARCH_QUERY = """query search($text: String!, $count: Int!) @cacheControl(maxAge: 60) {
  search(text: $text, first: $count) {
    ... on Episode {
      EpisodeID
      episode_id
      title
      ProgramTitle
    }
  }
}
"""


class Telewebion(YtdlpService):
    SERVICE_NAME = "telewebion"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("telewebion.ir", "telewebion.com")
    AUDIO_ONLY = True

    def search(self, query):
        query = (query or "").strip()
        if query.startswith(("http://", "https://")):
            # لینک‌های .com رو به .ir ترجمه کن تا اکسترکتور بشناستشون.
            query = query.replace("telewebion.com", "telewebion.ir")
        return super().search(query)

    def _search_stubs(self, query, count, interactive=False):
        """
        جستجو از طریق GraphQL تلوبیون.

        خروجی همون شکل stub استاندارده، پس resolve/صف/رشد پلی‌لیست هیچ
        فرقی با بقیه‌ی سرویس‌ها نمی‌بینن.
        """
        try:
            payload = self._graphql(_SEARCH_QUERY, {"text": query, "count": int(count)})
        except Exception as e:
            logging_setup.log_debug(f"[telewebion] search failed: {e}")
            return []

        results = (payload.get("data") or {}).get("search") or []
        stubs = []
        for item in results:
            if not isinstance(item, dict):
                continue
            episode_id = item.get("episode_id") or item.get("EpisodeID")
            if not episode_id:
                continue
            url = EPISODE_URL.format(episode_id=episode_id)
            title = item.get("title") or item.get("ProgramTitle") or "Unknown"
            stubs.append({
                "id": str(episode_id),
                "url": url,
                "webpage_url": url,
                "title": title,
            })
            if len(stubs) >= count:
                break
        return stubs

    def _graphql(self, query, variables):
        body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
        request = urllib.request.Request(GRAPHQL_URL, data=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        })
        proxy_url = proxy_state.get_proxy_url()
        if proxy_url:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
        else:
            opener = urllib.request.build_opener()
        with opener.open(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
