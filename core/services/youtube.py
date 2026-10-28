"""
سرویس جستجو/پلی‌لیست/کانال یوتیوب (و هر سایتی که yt-dlp ازش پشتیبانی می‌کنه).

پیش‌نیاز:
    pip install yt-dlp

خروجی search:
    - dict {"url","title","public_url","channel_url"}  برای یک نتیجه
    - list[dict]                                        برای پلی‌لیست

استفاده در چت:
    p <عبارت جستجو>      -> اولین نتیجه پیدا و پخش می‌شه (کانالش هم برای cv/cs/c/cpl ذخیره می‌شه)
    p <لینک ویدیو>        -> همون ویدیو پخش می‌شه
    p <لینک پلی‌لیست>     -> کل پلی‌لیست به صف اضافه و اولین آیتم پخش می‌شه

قابلیت کانال (cv/cs/c/cp/cpl از ttbot استفاده می‌کنن):
    get_channel_videos / get_channel_shorts / get_channel_all / get_channel_playlists
"""

import datetime
import json
import time
import xml.etree.ElementTree as ET
import urllib.error
import urllib.parse
import urllib.request

from core import proxy_state
from core import ytdlp_lazy
from core.ytdlp_lazy import YoutubeDL
from core import cache
from core import logging_setup
from core import workers
from core import youtube_api_state
from core import proxy_retry
from core import net
from core import track_meta
from core.services._ytdlp_service import YtdlpService

YOUTUBE_API_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

CHANNEL_ITEM_LIMIT = 20

class Youtube(YtdlpService):
    # از پایه‌ی مشترک فقط لوله‌کشی به ارث می‌رسه (ساخت opts با کوکیِ همین
    # ربات و پروکسی، انتخاب استریم، search_batch، resolve_stub). جستجو،
    # مسیر سریع API، کش توضیحات و تب‌های کانال مال خودِ یوتیوب‌اند و
    # دست‌نخورده موندن: این پربارترین سرویسه و هر تفاوت ظریف رفتاری روی
    # همه‌ی مشتری‌ها اثر می‌ذاره.
    SERVICE_NAME = "youtube"
    SEARCH_PREFIX = "ytsearch"
    # بدون این، owns_url همیشه False بود (پایه‌ی مشترک URL_MARKERS رو خالی
    # می‌ذاره) -- یعنی لینکِ خامِ یوتیوب که کاربر پیست می‌کرد یا با `u`
    # می‌فرستاد، هیچ‌وقت از این سرویس (با متادیتای غنی/channel_url/رشدِ
    # پلی‌لیست) رد نمی‌شد و فقط از لوله‌ی عمومیِ link_resolver می‌گذشت --
    # درحالی‌که `p <همون لینک>` این‌جا می‌رسید. music.youtube.com هم به
    # همین مارکر می‌خوره، ولی core/command_helpers.py::_owning_service_for_url
    # طولانی‌ترین مارکرِ منطبق رو برنده می‌کنه، پس همچنان می‌ره سراغِ
    # youtubemusic (مارکرِ خاص‌تر).
    URL_MARKERS = ("youtube.com", "youtu.be")
    # پلی‌لیست‌های لینک‌مستقیم بزرگ فقط تا این تعداد در بار اول resolve
    # می‌شن (سرعت)؛ بقیه با n به‌تدریج لود می‌شن (core.test._grow_playlist_queue).
    PLAYLIST_PAGE_SIZE = 20

    # وقتی برای رشد صف به stub بیشتری نیاز داریم، به‌جای چند بار سرچ با
    # countهای بزرگ‌شونده (ytsearch5 بعد ytsearch10 بعد ytsearch15 -- که هر
    # بار کل لیست رو دوباره می‌گیره و از دید یوتیوب مثل یه scraper به‌نظر
    # می‌رسه)، یه بار یه دسته‌ی بزرگ می‌گیریم و از همون کش سرو می‌کنیم.
    SEARCH_STUB_FETCH_SIZE = 40

    def __init__(self):
        super().__init__()
        # سقف عمر و تعداد داره. TTLها عمداً بلندن: هر بار که کش جواب بده،
        # یه درخواست کمتر به یوتیوب.
        self._search_cache = cache.TTLCache(ttl=1800, max_items=300)
        self._channel_cache = cache.TTLCache(ttl=1800, max_items=60)
        # entryهای فلت (resolve‌نشده) پلی‌لیست‌های بزرگ، کلید = URL پلی‌لیست.
        self._playlist_stub_cache = cache.TTLCache(ttl=3600, max_items=30)
        # توضیحات ویدیوها (کلید = video id) که موقع resolve به‌هرحال گرفته
        # شدن؛ دستور di از همین‌جا می‌خونه و درخواست اضافه نمی‌زنه.
        self._description_cache = cache.TTLCache(ttl=3600, max_items=200)
        # تاریخ انتشار آخرین آپلودهای هر کانال (از فید RSS)، کلید = channel id.
        self._feed_dates_cache = cache.TTLCache(ttl=600, max_items=60)
        self._api_quota_exhausted_until = 0

    def _resolve_entry(self, entry, interactive=False):
        """اگه entry به‌صورت flat باشه (فقط id/url داره، بدون فرمت‌های واقعی)، کامل resolveش می‌کنه."""
        # نکته‌ی مهم: توی entryهای flat (از extract_flat)، entry["url"] در
        # واقع لینک صفحه‌ی یوتیوبه (webpage)، نه لینک مستقیم استریم! قبلاً
        # اینجا با entry["url"] هم به‌عنوان لینک مستقیم رفتار می‌شد که باعث
        # می‌شد لینک صفحه‌ی یوتیوب مستقیم بره توی صف mpv (و mpv خودش سعی
        # می‌کرد با yt-dlp داخلی‌ی خودش -- بدون پروکسی -- resolve کنه که اغلب
        # fail می‌شد). این‌جا صراحتاً چک می‌کنیم که واقعاً فرمت واقعی داره یا
        # نه، وگرنه همیشه یه‌بار کامل resolve می‌کنیم.
        is_fully_resolved = bool(entry.get("formats") or entry.get("requested_formats") or entry.get("acodec"))
        url = self._direct_url(entry) if is_fully_resolved else None
        title = entry.get("title")
        public_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        channel_url = entry.get("channel_url") or entry.get("uploader_url")
        video_id = entry.get("id")
        # توضیحات همین‌جا (توی همون extract_info که به‌هرحال داریم می‌زنیم)
        # برداشته می‌شه، تا دستور di بعداً مجبور نشه یه درخواست کاملاً جدا
        # برای همون ویدیو بزنه.
        description = entry.get("description")
        info = track_meta.from_info(entry, "youtube")

        if not url:
            target = entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or entry.get("id")
            if target and not str(target).startswith(("http://", "https://")):
                target = f"https://www.youtube.com/watch?v={target}"
            if not target:
                return None
            try:
                # نمونه‌ی pool (تا برای هر entry یه instance تازه ساخته نشه)
                # + همون fallback پروکسی که جستجو داره.
                full = proxy_retry.extract_pooled(
                    "youtube", self._opts(interactive), target, label="youtube")
                url = self._direct_url(full)
                title = full.get("title", title)
                public_url = full.get("webpage_url", public_url)
                channel_url = full.get("channel_url") or full.get("uploader_url") or channel_url
                video_id = full.get("id", video_id)
                description = full.get("description") or description
                info = track_meta.merge(info, track_meta.from_info(full, "youtube"))
            except Exception:
                logging_setup.log_debug(f"resolving a stub failed (target={target!r})")
                return None

        if not url:
            return None

        if video_id and description:
            self._description_cache.set(video_id, description)

        return {
            "id": video_id,
            "url": url,
            "title": title or "Unknown title",
            "public_url": public_url,
            "channel_url": channel_url,
            "description": description,
            "info": info,
            # توضیح کامل: core/services/_ytdlp_service.py::_resolve_entry.
            "verified_media": True,
        }

    def get_cached_description(self, video_id):
        """
        توضیحات یه ویدیو رو -- فقط اگه از قبل موقع resolve گرفته شده باشه --
        برمی‌گردونه. هدف: دستور di برای ویدیویی که همین الان داره پخش می‌شه
        هیچ درخواست جدیدی به یوتیوب نزنه.
        """
        return self._description_cache.get(video_id) if video_id else None

    def _next_midnight_ts(self):
        now = datetime.datetime.now()
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return tomorrow.timestamp()

    def _search_via_api(self, query):
        """
        مسیر سریع: یه درخواست سبک به YouTube Data API (به‌جای جستجوی کامل
        yt-dlp که چند مرحله‌ست) برای پیدا کردن videoId، بعد فقط همون یه
        ویدیوی مشخص با yt-dlp resolve می‌شه (نه کل نتایج جستجو).
        اگه کلید تنظیم نشده، quota تموم شده باشه، یا هر مشکلی پیش بیاد،
        None برمی‌گردونه تا search() بره سراغ روش کامل yt-dlp.
        """
        api_key = youtube_api_state.get_api_key()
        if not api_key:
            return None
        if time.time() < self._api_quota_exhausted_until:
            return None

        params = urllib.parse.urlencode({
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 1,
            "key": api_key,
        })
        req = urllib.request.Request(f"{YOUTUBE_API_SEARCH_URL}?{params}")

        proxy_url = proxy_state.get_proxy_url()
        opener = (
            urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
            if proxy_url else urllib.request.build_opener()
        )

        try:
            with opener.open(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            if e.code == 403 and ("quotaExceeded" in body or "dailyLimitExceeded" in body):
                self._api_quota_exhausted_until = self._next_midnight_ts()
                logging_setup.get_ytdlp_logger().warning(
                    "YouTube Data API quota exceeded؛ تا فردا فقط از yt-dlp استفاده می‌شه."
                )
            else:
                logging_setup.get_ytdlp_logger().warning(f"YouTube Data API error: {e}")
            return None
        except Exception as e:
            logging_setup.get_ytdlp_logger().warning(f"YouTube Data API request failed: {e}")
            return None

        items = data.get("items") or []
        if not items:
            return None

        video_id = items[0].get("id", {}).get("videoId")
        if not video_id:
            return None

        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            with YoutubeDL(self._opts(interactive=True)) as ydl:
                info = ydl.extract_info(watch_url, download=False)
        except Exception:
            logging_setup.log_debug(f"YouTube API fast-path resolve failed for {watch_url!r}")
            return None

        url = self._direct_url(info)
        if not url:
            return None

        return {
            "id": video_id,
            "url": url,
            "title": info.get("title") or items[0].get("snippet", {}).get("title") or "Unknown title",
            "public_url": info.get("webpage_url") or watch_url,
            "channel_url": info.get("channel_url") or info.get("uploader_url"),
            "description": info.get("description"),
            "info": track_meta.from_info(info, "youtube"),
            "verified_media": True,
        }

    def _search_cache_get(self, key):
        return self._search_cache.get(key)

    def _search_cache_set(self, key, value):
        self._search_cache.set(key, value)

    def search(self, query: str):
        query = (query or "").strip()
        if not query:
            raise ValueError("No search query given.")

        # هر فراخوانی جدید از صفر شروع می‌شه؛ فقط شاخه‌ی truncate‌شده‌ی
        # پلی‌لیست دوباره ستش می‌کنه. وگرنه یه پخش تک‌ویدیوی بعدی می‌تونه
        # از رو growth info پلی‌لیست *قبلی* رشد غلط راه بندازه (چون
        # get_playlist_growth_info مقدار قدیمی رو برمی‌گردونه).
        self._last_playlist_info = None

        is_url = query.startswith("http://") or query.startswith("https://")
        cache_key = query.lower()

        cached = self._search_cache_get(cache_key)
        if cached is not None:
            return cached

        # پخش دوباره‌ی همون پلی‌لیست: stubهاش از دفعه‌ی قبل کش شدن، پس
        # نیازی نیست کل لیست رو دوباره از سرویس بگیریم -- فقط آیتم اول رو
        # resolve می‌کنیم و رشد بقیه مثل قبل از کش انجام می‌شه.
        if is_url:
            cached_stubs = self._playlist_stub_cache.get(query)
            if cached_stubs and len(cached_stubs) > 1:
                index, first = self._first_playable(cached_stubs, self._start_index(query, cached_stubs))
                if first:
                    self._last_playlist_info = (query, len(cached_stubs), index + 1)
                    return [first]

        if not is_url:
            fast_result = self._search_via_api(query)
            if fast_result:
                self._search_cache_set(cache_key, fast_result)
                return fast_result

        target = query if is_url else f"ytsearch1:{query}"

        try:
            opts = self._opts(interactive=True)
            if is_url:
                opts = dict(opts)
                opts["extract_flat"] = "in_playlist"
            info = proxy_retry.extract_with_fallback(opts, target, label="youtube")
        except ytdlp_lazy.download_error():
            logging_setup.log_exception(f"yt-dlp could not resolve '{query}'")
            raise ValueError("Nothing found.")
        except Exception:
            logging_setup.log_exception(f"unexpected error resolving '{query}'")
            raise ValueError("Nothing found.")

        if not info:
            raise ValueError("Nothing found.")

        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                raise ValueError("Nothing found.")
            entries = self._order_entries(entries, info)

            if is_url and len(entries) > 1:
                # پلی‌لیست/میکس چندآیتمی: درست مثل سرچ متنی، فقط آیتم اول
                # رو fast resolve کن تا پخش بلافاصله شروع بشه؛ بقیه‌ی
                # entryهای فلت کش می‌شن تا با n به‌تدریج (grow_playlist)
                # لود بشن -- منتظر resolve کل صفحه نمی‌مونیم.
                self._playlist_stub_cache.set(query, entries)
                index, first = self._first_playable(entries, self._start_index(query, entries))
                if not first:
                    raise ValueError("Nothing found.")
                self._last_playlist_info = (query, len(entries), index + 1)
                return [first]

            results = self._resolve_entries_parallel(entries)
            if not results:
                raise ValueError("Nothing found.")

            result = results[0] if not is_url else results
            self._last_playlist_info = None
            self._search_cache_set(cache_key, result)
            return result

        if is_url:
            resolved = self._resolve_entry(info, interactive=True)
            if not resolved:
                raise ValueError("Nothing found.")
            self._search_cache_set(cache_key, resolved)
            return resolved

        url = self._direct_url(info)
        if not url:
            raise ValueError("Nothing found.")
        result = {
            "id": info.get("id"),
            "url": url,
            "title": info.get("title") or "Unknown title",
            "public_url": info.get("webpage_url") or query,
            "channel_url": info.get("channel_url") or info.get("uploader_url"),
            "description": info.get("description"),
            "info": track_meta.from_info(info, "youtube"),
            "verified_media": True,
        }
        self._search_cache_set(cache_key, result)
        return result

    def grow_playlist(self, url, start, count=None):
        """
        صفحه‌ی بعدی (از ایندکس start، تا count تا) از entryهای فلتِ از قبل
        کش‌شده‌ی همون پلی‌لیست رو resolve می‌کنه. چون entryها همون اول (موقع
        extract_flat اولیه) کامل شناخته شدن، این فقط resolve می‌کنه، دوباره
        کل پلی‌لیست رو لیست نمی‌کنه.
        """
        count = count or self.PLAYLIST_PAGE_SIZE
        entries = self._playlist_stub_cache.get(url)
        if not entries:
            return []
        page = entries[start:start + count]
        if not page:
            return []
        # هر entry همون‌جای خودش می‌مونه (خراب‌ها به‌صورت stub)؛ وگرنه شمارنده‌ی
        # «چندتا لود شد» جلوتر از موقعیت واقعی می‌رفت و صفحه‌ی بعد آیتم‌های
        # تکراری/جابه‌جا می‌آورد.
        return self._resolve_entries_parallel(page, keep_unresolved=True)

    # ---------------------------------------------------------- ترتیب زمانی

    def _is_feed(self, info):
        """تب/صفحه‌ی کانال (شناسه‌ی UC...) فیده؛ پلی‌لیست (PL...) نه."""
        return str((info or {}).get("id") or "").startswith("UC")

    def _feed_dates(self, channel_id):
        """
        {video_id: epoch} برای ۱۵ آپلود اخیر کانال (ویدیو و شورت و لایو
        باهم) از فید RSS رسمی -- یک درخواست سبک به‌جای استخراج کاملِ هر
        ویدیو. آپلودهای قدیمی‌تر از اون فید تاریخ نمی‌گیرن ولی قدیمی‌تر از
        همه‌ی تاریخ‌دارها هستن، پس همون‌جا (بعدشون) می‌مونن.
        """
        if not channel_id:
            return {}
        cached = self._feed_dates_cache.get(channel_id)
        if cached is not None:
            return cached
        dates = {}
        try:
            _, body = net.fetch_text(
                f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                label="youtube")
            ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
            for node in ET.fromstring(body).findall("a:entry", ns):
                vid = node.findtext("yt:videoId", namespaces=ns)
                stamp = track_meta.parse_timestamp(node.findtext("a:published", namespaces=ns))
                if vid and stamp:
                    dates[vid] = stamp
        except Exception:
            logging_setup.log_debug(f"[youtube] RSS dates unavailable for {channel_id}")
            return {}
        self._feed_dates_cache.set(channel_id, dates)
        return dates

    def _date_entries(self, entries, info):
        dates = self._feed_dates((info or {}).get("channel_id") or (info or {}).get("id"))
        if not dates:
            return entries
        return [dict(e, timestamp=dates[e["id"]])
                if e.get("id") in dates and not track_meta.timestamp_of(e) else e
                for e in entries]

    def _channel_tab_url(self, channel_url, tab):
        return channel_url.rstrip("/") + f"/{tab}"

    def _resolve_entries_parallel(self, entries, max_workers=None, keep_unresolved=False):
        """
        هر entry رو موازی به یه لینک واقعی قابل‌پخش تبدیل می‌کنه.

        از استخر ترد مشترک پروژه استفاده می‌شه، نه یه
        ThreadPoolExecutor تازه به‌ازای هر فراخوانی؛ توضیح کامل
        توی core/workers.py.
        """
        entries = [e for e in entries if e]
        if not entries:
            return []
        resolved = workers.map_unordered(self._resolve_entry, entries)
        if keep_unresolved:
            return [r or e for r, e in zip(resolved, entries)]
        return [r for r in resolved if r]

    def _list_tab(self, url, cache_key, limit=CHANNEL_ITEM_LIMIT):
        # مثل search(): از صفر شروع می‌شه تا growth info یه پلی‌لیست/کانال
        # قبلاً truncate‌شده‌ی دیگه اینجا اشتباهی reuse نشه.
        self._last_playlist_info = None

        cached = self._channel_cache.get(cache_key)
        if cached is not None:
            return cached[:limit]

        opts = dict(self._opts(interactive=True))
        opts["extract_flat"] = "in_playlist"
        opts["playlistend"] = limit

        try:
            info = proxy_retry.extract_with_fallback(opts, url, label="youtube")
        except Exception:
            logging_setup.log_exception(f"listing channel tab '{url}'")
            return []

        entries = [e for e in (info.get("entries") or []) if e][:limit]
        if not entries:
            return []
        entries = self._order_entries(entries, info)

        if len(entries) > 1:
            # مثل سرچ متنی/پلی‌لیست: فقط آیتم اول رو fast resolve کن تا
            # پخش زودتر شروع بشه؛ بقیه با n به‌تدریج (grow_playlist) لود
            # می‌شن. cache_key همون کلیدیه که get_playlist_growth_info/
            # grow_playlist بعداً باهاش صدا زده می‌شن.
            self._playlist_stub_cache.set(cache_key, entries)
            index, first = self._first_playable(entries)
            if not first:
                return []
            self._last_playlist_info = (cache_key, len(entries), index + 1)
            return [first]

        results = self._resolve_entries_parallel(entries)
        self._channel_cache.set(cache_key, results)
        return results

    def get_channel_videos(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        url = self._channel_tab_url(channel_url, "videos")
        return self._list_tab(url, (channel_url, "videos"), limit)

    def get_channel_shorts(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        url = self._channel_tab_url(channel_url, "shorts")
        return self._list_tab(url, (channel_url, "shorts"), limit)

    def get_channel_all(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        return self.get_channel_videos(channel_url, limit)

    def get_channel_live(self, channel_url):
        """
        پخشِ *زنده‌ی همین الانِ* این کانال، یا [] اگه زنده نیست.

        یوتیوب برای این کار آدرس `/live` رو داره که وقتی کانال زنده‌ست به
        خود ویدیوی زنده ریدایرکت می‌شه. وقتی زنده نیست یوتیوب ۴۰۴ می‌ده
        یا صفحه‌ی کانال رو برمی‌گردونه -- پس نبودِ نتیجه یعنی «زنده نیست»،
        نه خطا؛ و همین‌طور هم به کاربر گزارش می‌شه.

        عمداً کش نمی‌شه: «الان زنده‌ست یا نه» دقیقاً همون چیزیه که هر بار
        باید تازه باشه.
        """
        if not channel_url:
            return []
        self._last_playlist_info = None

        url = self._channel_tab_url(channel_url, "live")
        opts = dict(self._opts(interactive=True))
        # extract_flat نمی‌ذاریم: می‌خوایم همین یه ویدیو کامل resolve بشه.
        try:
            info = proxy_retry.extract_with_fallback(opts, url, label="youtube")
        except Exception as e:
            logging_setup.log_debug(f"[youtube] channel live check failed ({url}): {e}")
            return []

        if not info:
            return []

        # اگه کانال زنده نباشه ممکنه به‌جای ویدیو، لیست تب برگرده.
        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                return []
            info = entries[0]

        # فقط چیزی که *واقعاً* الان زنده‌ست. یوتیوب برای پخش‌های تمام‌شده
        # هم همین آدرس رو ممکنه جواب بده و بدون این چک، cl بی‌سروصدا یه
        # ضبطِ قدیمی پخش می‌کرد.
        if info.get("live_status") in ("was_live", "post_live", "not_live"):
            return []
        if not info.get("is_live") and info.get("live_status") != "is_live":
            return []

        resolved = self._resolve_entry(info, interactive=True)
        return [resolved] if resolved else []

    def get_channel_streams(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        """
        تبِ «پخش‌های زنده»ی کانال: ضبطِ لایوهای قبلی که کانال نگه داشته.

        این همون چیزیه که خیلی کانال‌ها به‌جای آپلود جدا، آرشیو لایوشون
        رو توش می‌ذارن -- و توی تبِ videos دیده نمی‌شه.
        """
        url = self._channel_tab_url(channel_url, "streams")
        return self._list_tab(url, (channel_url, "streams"), limit)

    def get_channel_podcasts(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        """تبِ پادکست‌های کانال (اگه داشته باشه)."""
        url = self._channel_tab_url(channel_url, "podcasts")
        return self._list_tab(url, (channel_url, "podcasts"), limit)

    def get_channel_releases(self, channel_url, limit=CHANNEL_ITEM_LIMIT):
        """تبِ آلبوم/ریلیزهای موسیقیِ کانال (اگه داشته باشه)."""
        url = self._channel_tab_url(channel_url, "releases")
        return self._list_tab(url, (channel_url, "releases"), limit)

    def get_channel_playlists(self, channel_url):
        cache_key = (channel_url, "playlists")
        cached = self._channel_cache.get(cache_key)
        if cached is not None:
            return cached

        url = self._channel_tab_url(channel_url, "playlists")
        opts = dict(self._opts(interactive=True))
        opts["extract_flat"] = "in_playlist"

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            logging_setup.log_exception(f"listing playlists for channel '{channel_url}'")
            return []

        entries = [e for e in (info.get("entries") or []) if e]
        results = []
        for e in entries:
            list_id = e.get("id")
            playlist_url = f"https://www.youtube.com/playlist?list={list_id}" if list_id else e.get("url")
            if not playlist_url or not playlist_url.startswith("http"):
                continue
            results.append({"title": e.get("title") or "Untitled playlist", "url": playlist_url})

        self._channel_cache.set(cache_key, results)
        return results
