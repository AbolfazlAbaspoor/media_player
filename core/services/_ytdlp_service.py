"""
پایه‌ی مشترک سرویس‌های مبتنی بر yt-dlp.

## چرا این فایل هست

سرویس‌های قدیمی (youtube/soundcloud/instagram/tiktok/spotify) هرکدوم
حدود ۲۵۰ خط کدِ تقریباً یکسان داشتن: ساخت opts، پیداکردن لینک مستقیم،
resolve کردن stub، جستجو، رشد تدریجی پلی‌لیست. برای اضافه‌کردن ده‌تا
سرویس جدید، کپی‌کردن اون ۲۵۰ خط ده بار یعنی ده نسخه که هر باگی باید
ده جا درست بشه.

این کلاس همون منطق رو یک‌بار می‌نویسه تا هر سرویس جدید فقط *تفاوت‌های
واقعیِ خودش* رو تعریف کنه (آدرس‌ها، پیشوند جستجو، فرمت).

## سرویس‌های قدیمی

youtube/soundcloud/instagram/tiktok/spotify هم حالا روی همین پایه‌ن. هر
کدوم فقط تفاوت واقعیِ خودش رو نگه داشته (یوتیوب: مسیر سریع API، کش
توضیحات و تب‌های کانال؛ اینستاگرام: پیام‌های راهنما و فیدها؛ تیک‌تاک:
User-Agent؛ اسپاتیفای: متادیتا از اسپاتیفای و صدا از یوتیوب) و بقیه‌ی
لوله‌کشی -- opts، پروکسی، کوکی، صف، رشد پلی‌لیست -- یک‌جا اینجاست.

## ساخت یه سرویس جدید

    from core.services._ytdlp_service import YtdlpService

    class Bandcamp(YtdlpService):
        SERVICE_NAME = "bandcamp"
        URL_MARKERS = ("bandcamp.com",)
        SEARCH_URL_TEMPLATE = "https://bandcamp.com/search?q={query}&item_type=t"

همین. جستجو، پخش، صف، و رشد پلی‌لیست از این‌جا میان.
"""

import os
import urllib.parse
from concurrent.futures import wait as _wait_futures

from core import ytdlp_lazy

from core import bot_context
from core import cache
from core import logging_setup
from core import proxy_retry
from core import proxy_state
from core import track_meta
from core import workers
from core import ytdlp_opts


class YtdlpService:
    # -------------------------------------------------- چیزهایی که هر سرویس تعریف می‌کنه

    #: کلید pool و برچسب لاگ‌ها. حتماً پرش کن.
    SERVICE_NAME = ""

    #: توی چرخه‌ی w/p دیده بشه؟ سرویس‌های فقط-لینک False می‌ذارن.
    SUPPORTS_SEARCH = True

    #: پیشوند جستجوی خود yt-dlp، مثل "scsearch" یا "ytsearch".
    #: با این، جستجو بدون هیچ API کلیدی کار می‌کنه.
    SEARCH_PREFIX = None

    #: اگه سرویس پیشوند جستجو نداره، آدرس صفحه‌ی جستجوش.
    #: {query} با عبارتِ urlencode‌شده جایگزین می‌شه.
    SEARCH_URL_TEMPLATE = None

    #: تکه‌هایی که یه لینک رو «مال این سرویس» می‌کنن.
    URL_MARKERS = ()

    #: فقط صدا می‌خوایم یا ویدیو هم مهمه. سرویس‌های تصویری این رو False
    #: می‌کنن تا کیفیت ویدیو هم انتخاب بشه.
    AUDIO_ONLY = True

    #: چندتا stub در یک جستجو گرفته بشه (یه درخواست به‌جای چند تا).
    SEARCH_STUB_FETCH_SIZE = 40

    #: چندتا نتیجه برای *اولین* پخشِ یه جستجو. None یعنی همون
    #: SEARCH_STUB_FETCH_SIZE. برای سایت‌هایی که نتایج رو یه‌جا می‌دن (یوتیوب)
    #: گرفتنِ ۴۰ تا همون اول ارزونه و بعداً درخواستی نمی‌خواد؛ ولی سایتی که
    #: صفحه‌صفحه جواب می‌ده (ساندکلاد) با ۴۰ تا اولین آهنگ رو از ~۵ به ~۳۰
    #: ثانیه می‌رسوند. اون‌ها ۱ می‌ذارن و بقیه با search_batch موقع رشد صف میان.
    SEARCH_FIRST_COUNT = None

    #: هر بار رشد صف چندتا آیتم اضافه کنه.
    PLAYLIST_PAGE_SIZE = 20

    #: گزینه‌های اضافه‌ی yt-dlp مخصوص این سرویس.
    EXTRA_OPTS = {}

    #: کوکیِ کدوم سرویس استفاده بشه. None یعنی SERVICE_NAME. سرویسی که
    #: صداش رو از جای دیگه می‌گیره (اسپاتیفای -> یوتیوب) کوکیِ همون‌جا رو لازم داره.
    COOKIE_SERVICE = None

    #: برای لیست‌های «فید» (صفحه‌ی هنرمند/کانال/پروفایل) که yt-dlp فقط
    #: entryهای بی‌تاریخ می‌ده: تا چندتا از اولین آیتم‌ها برای گرفتنِ تاریخ
    #: انتشار کامل استخراج بشن (موازی، توی استخر مشترک). 0 = خاموش.
    #: باقیِ آیتم‌ها قدیمی‌تر از این‌ها فرض می‌شن و همون‌جا می‌مونن.
    DATE_PROBE_LIMIT = 0
    #: سقف زمانِ کلِ این کار (ثانیه)؛ هر چی تا اون موقع جواب نداده بی‌تاریخ می‌مونه.
    DATE_PROBE_BUDGET = 20

    # -------------------------------------------------- پیاده‌سازی مشترک

    def __init__(self):
        self._base_opts = {
            "quiet": True,
            "no_warnings": False,
            "format": "bestaudio/best" if self.AUDIO_ONLY else "best",
            "noplaylist": False,
            "skip_download": True,
            # کم‌کردن ردپای درخواست‌ها، دقیقاً مثل سرویس‌های قدیمی: retry
            # کمتر یعنی به‌ازای هر خطا چند برابر درخواست نمی‌زنیم، و مکث
            # کوتاه بین درخواست‌های داخلی الگو رو از حالت رگباری درمیاره.
            "retries": 2,
            "extractor_retries": 1,
            "fragment_retries": 2,
            "sleep_interval_requests": 1,
            "logger": logging_setup.get_ytdlp_logger(),
        }
        self._base_opts.update(self.EXTRA_OPTS)
        self._search_cache = cache.TTLCache(ttl=1800, max_items=200)
        self._stub_cache = cache.TTLCache(ttl=1800, max_items=60)
        self._last_playlist_info = None
        self._cookiefile = self._resolve_cookiefile()

    def _resolve_cookiefile(self):
        """
        فایل cookies.txt این سرویس، یا None.

        بدون این، سرویس‌های جدید به دیوار «Sign in to confirm you're
        not a bot» می‌خوردن و دستور ck هیچ کاری براشون نمی‌کرد --
        مخصوصاً youtubemusic که روی همون زیرساخت یوتیوبه.

        مثل سرویس youtube یه‌بار موقع ساخت حساب می‌شه، پس ck همون
        رفتار رو داره: بعد از تغییر باید ری‌استارت بشه.
        """
        bot = getattr(bot_context, "bot", None)
        if bot is None:
            return None
        cfg = getattr(bot, "cfg", None) or {}
        if not cfg.get("cookies", {}).get("enabled", True):
            return None
        getter = getattr(bot, "cookies_file_for", None)
        if not getter:
            return None
        try:
            path = getter(self.COOKIE_SERVICE or self.SERVICE_NAME)
        except Exception:
            return None
        return path if (path and os.path.exists(path)) else None

    # ------------------------------------------------------------- opts

    def _opts(self, interactive=False):
        """
        interactive=True یعنی کاربر *همین الان* منتظر این درخواسته، پس
        مکث ضدرباتیِ بین درخواست‌ها برداشته می‌شه. برای کارهای پس‌زمینه
        (رشد صف) سر جاش می‌مونه -- همون‌جا که حجم درخواست بالاست و ردپا
        اهمیت داره.
        """
        opts = dict(self._base_opts)
        if interactive:
            opts["sleep_interval_requests"] = 0
        proxy_url = proxy_state.get_proxy_url()
        if proxy_url:
            opts["proxy"] = proxy_url
        if self._cookiefile:
            opts["cookiefile"] = self._cookiefile
        return ytdlp_opts.with_js_runtime(opts)

    def _direct_url(self, info):
        if not info:
            return None
        if info.get("url"):
            return info["url"]
        for fmt in info.get("requested_formats") or []:
            if fmt.get("url"):
                return fmt["url"]
        for fmt in reversed(info.get("formats") or []):
            if fmt.get("url"):
                return fmt["url"]
        return None

    def owns_url(self, url):
        low = (url or "").lower()
        return any(marker in low for marker in self.URL_MARKERS)

    # ---------------------------------------------------------- resolve

    def _resolve_entry(self, entry, interactive=False):
        """
        یه entry (کامل یا flat) رو به لینک قابل‌پخش تبدیل می‌کنه.

        توی entryهای flat، entry["url"] لینک *صفحه*ست نه استریم، پس
        صراحتاً چک می‌کنیم فرمت واقعی داره یا نه.
        """
        if not entry:
            return None

        fully_resolved = bool(entry.get("formats") or entry.get("requested_formats")
                              or entry.get("acodec"))
        url = self._direct_url(entry) if fully_resolved else None
        title = entry.get("title")
        public_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        channel_url = entry.get("uploader_url") or entry.get("channel_url")
        # متادیتای نرمال از همون داده‌ای که به‌هرحال داریم (stub، بعد نسخه‌ی
        # کامل روش می‌شینه) -- برای i/di، بدون هیچ درخواست اضافه.
        info = track_meta.from_info(entry, self.SERVICE_NAME)

        if not url:
            target = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
            if not target:
                return None
            try:
                full = proxy_retry.extract_pooled(
                    self.SERVICE_NAME, self._opts(interactive), target,
                    label=self.SERVICE_NAME)
            except Exception:
                logging_setup.log_debug(
                    f"[{self.SERVICE_NAME}] resolving stub failed ({target!r})")
                return None
            url = self._direct_url(full or {})
            title = (full or {}).get("title") or title
            public_url = (full or {}).get("webpage_url") or public_url
            channel_url = ((full or {}).get("uploader_url")
                           or (full or {}).get("channel_url") or channel_url)
            info = track_meta.merge(info, track_meta.from_info(full, self.SERVICE_NAME))

        if not url:
            return None

        return {
            "id": entry.get("id"),
            "url": url,
            "title": title or "Unknown",
            "public_url": public_url,
            "channel_url": channel_url,
            "info": info,
            # yt-dlp خودش این url رو از formats انتخاب کرده؛ یعنی حتماً یه
            # استریم/فایل واقعیه، نه یه فایل .m3u8/.m3u که فقط یه لیستِ متنیِ
            # ساده از لینک‌های جداست. بدون این پرچم، bot.py::_expand_item
            # هر لینکِ HLS (مثل لایوهای یوتیوب که آدرسشون به .m3u8 ختم
            # می‌شه) رو دوباره کامل دانلود می‌کرد فقط برای همین تشخیص --
            # چند ثانیه تأخیرِ کاملاً بی‌فایده روی مسیر داغِ پخش.
            "verified_media": True,
        }

    # ---------------------------------------------------------- ترتیب زمانی

    def _is_feed(self, info):
        """
        این لیست یه «فید» ـه (جدیدترین اول باید باشه) یا یه پلی‌لیست/آلبوم که
        ترتیبش رو خودِ صاحبش چیده؟ پیش‌فرض: پلی‌لیست -- پس ترتیب دست‌نخورده.
        سرویس‌ها برای صفحه‌ی هنرمند/کانال/پروفایل override می‌کنن.
        """
        return False

    def _date_entries(self, entries, info):
        """
        entryها رو با `timestamp` برمی‌گردونه هرجا سرویس ارزون می‌تونه.
        پیش‌فرض: اگه DATE_PROBE_LIMIT روشنه، اولین آیتم‌ها رو کامل
        استخراج می‌کنه (فقط برای گرفتن تاریخ و متادیتا).
        """
        limit = self.DATE_PROBE_LIMIT
        if not limit:
            return entries
        head = [e for e in entries[:limit]
                if not track_meta.timestamp_of(e) and (e.get("webpage_url") or e.get("url"))]
        if not head:
            return entries

        def probe(entry):
            target = entry.get("webpage_url") or entry.get("url")
            try:
                full = proxy_retry.extract_pooled(
                    self.SERVICE_NAME, self._opts(True), target, label=self.SERVICE_NAME)
            except Exception:
                return None
            if not full:
                return None
            return track_meta.from_info(full, self.SERVICE_NAME)

        futures = {workers.submit(probe, e): e for e in head}
        _wait_futures(list(futures), timeout=self.DATE_PROBE_BUDGET)
        dated = {}
        for future, entry in futures.items():
            if not future.done():
                continue
            try:
                meta = future.result()
            except Exception:
                meta = None
            if meta and meta.get("timestamp"):
                dated[id(entry)] = meta
        out = []
        for entry in entries:
            meta = dated.get(id(entry))
            out.append(dict(entry, timestamp=meta["timestamp"], info=meta) if meta else entry)
        return out

    def _order_entries(self, entries, info):
        """
        تنها مرحله‌ی مرتب‌سازیِ لیست‌های این سرویس: فقط فیدها نو به کهنه
        می‌شن (track_meta.sort_newest_first)؛ پلی‌لیست/آلبوم دست‌نخورده.
        """
        if not entries or not self._is_feed(info):
            return entries
        try:
            return track_meta.sort_newest_first(self._date_entries(entries, info))
        except Exception:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] ordering listing failed")
            return entries

    #: چندتا آیتم اولِ تا یه قابل‌پخش پیدا بشه.
    FIRST_PLAYABLE_TRIES = 5

    @staticmethod
    def _start_index(query, entries):
        """
        لینکِ watch?v=X&list=Y: پلی‌لیست از خودِ ویدیوی X شروع بشه، نه از
        اولش. index آیتمِ X توی entries (یا 0 اگه v= نبود/پیدا نشد).
        """
        try:
            video_id = (urllib.parse.parse_qs(urllib.parse.urlparse(query).query).get("v") or [None])[0]
        except Exception:
            video_id = None
        if not video_id:
            return 0
        for i, entry in enumerate(entries):
            if entry.get("id") == video_id:
                return i
        return 0

    def _first_playable(self, entries, start=0):
        """
        (index, resolved) اولین آیتمی از پلی‌لیست که واقعاً پخش می‌شه، یا
        (None, None).

        قبلاً فقط entries[0] امتحان می‌شد: اگه اولین ویدیو حذف یا خصوصی شده
        بود، *کل* پلی‌لیست «چیزی پیدا نشد» می‌داد درحالی‌که بقیه سالم بودن.
        """
        for index in range(start, min(len(entries), start + self.FIRST_PLAYABLE_TRIES)):
            resolved = self._resolve_entry(entries[index], interactive=True)
            if resolved:
                return index, resolved
        return None, None

    def resolve_stub(self, stub):
        """صف برای هر آیتم resolve‌نشده این رو صدا می‌زنه."""
        return self._resolve_entry(stub)

    # ----------------------------------------------------------- search

    def _search_target(self, query, count=1):
        """عبارت جستجو رو به چیزی که yt-dlp می‌فهمه تبدیل می‌کنه."""
        if self.SEARCH_PREFIX:
            return f"{self.SEARCH_PREFIX}{count}:{query}"
        if self.SEARCH_URL_TEMPLATE:
            return self.SEARCH_URL_TEMPLATE.format(query=urllib.parse.quote(query))
        return None

    def _search_stubs(self, query, count, interactive=False):
        """
        stubهای نتیجه‌ی جستجو -- تنها جایی که «جستجو» تعریف می‌شه.

        پیش‌فرض از خود yt-dlp استفاده می‌کنه (پیشوند جستجو مثل scsearch،
        یا آدرس صفحه‌ی جستجو). سرویس‌هایی که yt-dlp براشون اکسترکتور
        جستجو نداره ولی API عمومی خودشون رو دارن (مثل آپارات) همین یکی
        رو override می‌کنن و باقیِ زنجیره -- resolve، صف، رشد پلی‌لیست --
        بدون تغییر کار می‌کنه.
        """
        target = self._search_target(query, count=count)
        if target is None:
            return []
        opts = dict(self._opts(interactive))
        opts["extract_flat"] = "in_playlist"
        try:
            info = proxy_retry.extract_with_fallback(opts, target, label=self.SERVICE_NAME)
        except Exception as e:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] search failed: {e}")
            return []
        return [e for e in ((info or {}).get("entries") or []) if e]

    def search(self, query):
        """
        لینکِ این سرویس یا عبارت جستجو.

        برای پلی‌لیست/آلبوم فقط آیتم اول resolve می‌شه و بقیه stub کش
        می‌شن تا صف به‌تدریج لودشون کنه -- یه استخراج به‌جای پنجاه‌تا
        قبل از شنیدن آهنگ اول.
        """
        query = (query or "").strip()
        if not query:
            return None

        self._last_playlist_info = None
        is_url = query.startswith(("http://", "https://"))
        if is_url and self.URL_MARKERS and not self.owns_url(query):
            return None

        cache_key = query.lower()
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached

        if not is_url:
            # مسیر جستجو: stubها رو بگیر، اولی رو resolve کن، بقیه برای صف
            # کش بشن. یه استخراج به‌جای N تا.
            first_count = self.SEARCH_FIRST_COUNT or self.SEARCH_STUB_FETCH_SIZE
            stubs = self._search_stubs(query, first_count, interactive=True)
            if not stubs:
                return None
            if len(stubs) > 1:
                self._stub_cache.set(query.lower(), stubs)
            resolved = self._resolve_entry(stubs[0], interactive=True)
            if resolved:
                self._search_cache.set(cache_key, resolved)
            return resolved

        opts = dict(self._opts(interactive=True))
        opts["extract_flat"] = "in_playlist"

        try:
            info = proxy_retry.extract_with_fallback(opts, query, label=self.SERVICE_NAME)
        except ytdlp_lazy.download_error() as e:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] download error: {e}")
            return None
        except Exception as e:
            logging_setup.log_debug(f"[{self.SERVICE_NAME}] search failed: {e}")
            return None

        if not info:
            return None

        if info.get("_type") == "playlist" or "entries" in info:
            entries = [e for e in (info.get("entries") or []) if e]
            if not entries:
                return None
            entries = self._order_entries(entries, info)

            if len(entries) > 1:
                self._stub_cache.set(query, entries)
                index, first = self._first_playable(entries, self._start_index(query, entries))
                if not first:
                    return None
                # رشد از بعدِ همین آیتم ادامه پیدا می‌کنه؛ آیتم‌های خرابِ قبلش رد می‌شن.
                self._last_playlist_info = (query, len(entries), index + 1)
                return [first]

            resolved = self._resolve_entry(entries[0], interactive=True)
            if resolved:
                self._search_cache.set(cache_key, resolved)
            return resolved

        resolved = self._resolve_entry(info, interactive=True)
        if resolved:
            self._search_cache.set(cache_key, resolved)
        return resolved

    def search_batch(self, query, count=10):
        """
        یه دسته stub از نتایج جستجو. سریعه چون extract_flat هیچ‌کدوم رو
        کامل resolve نمی‌کنه.

        یه‌بار دسته‌ی بزرگ گرفته و کش می‌شه، چون اکثر این جستجوها آفست
        ندارن و «بیشتر گرفتن» یعنی جستجوی دوباره‌ی کل لیست.
        """
        query = (query or "").strip()
        if not query or query.startswith(("http://", "https://")):
            return []

        cached = self._stub_cache.get(query.lower())
        if cached and len(cached) >= count:
            return cached[:count]

        fetch_count = max(count, self.SEARCH_STUB_FETCH_SIZE)
        entries = self._search_stubs(query, fetch_count)
        if entries:
            self._stub_cache.set(query.lower(), entries)
        else:
            return list(cached or [])[:count]
        return entries[:count]

    # ------------------------------------------------------------- رشد

    def get_playlist_growth_info(self):
        """(url, total, loaded) آخرین پلی‌لیستی که ناقص لود شده، یا None."""
        return self._last_playlist_info

    def grow_playlist(self, url, start, count=None):
        """صفحه‌ی بعدی stubهای یه پلی‌لیست از قبل کش‌شده -- بدون درخواست جدید."""
        entries = self._stub_cache.get(url)
        if not entries:
            return []
        count = count or self.PLAYLIST_PAGE_SIZE
        return entries[start:start + count]
