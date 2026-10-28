"""
سرویس آپارات: ویدیو، کانال، پلی‌لیست، و **جستجوی متنی فارسی**.

استفاده:
    w aparat  +  p <هر عبارت فارسی>          -> جستجو
    p https://www.aparat.com/v/xxxxx          -> یه ویدیو
    p https://www.aparat.com/username         -> ویدیوهای یه کانال
    p https://www.aparat.com/playlist/12345   -> یه پلی‌لیست
    ap <link|عبارت>                           -> دستور اختصاصی

## جستجو از کجا میاد

yt-dlp برای آپارات فقط اکسترکتور *ویدیو* داره، نه جستجو. ولی خود
آپارات یه API عمومی و بدون کلید داره:

    https://www.aparat.com/api/fa/v1/video/video/search/text/<عبارت>

نتیجه‌ش JSON:API ـه و ویدیوها نه توی `data` بلکه توی `included` می‌شینن
(`data` فقط ردیف‌های چیدمان صفحه‌ست) -- یه تلهٔ ساده که باعث می‌شه
جستجو «صفر نتیجه» بده درحالی‌که پاسخ پر از ویدیوئه.

از هر ویدیو فقط `uid` لازمه؛ لینک صفحه‌ش رو می‌سازیم و resolve نهایی
دست خود اکسترکتور yt-dlp می‌مونه.

## پلی‌لیست و کانال

همون الگوی JSON:API برای سه تا API دیگه هم تکرار می‌شه (بدون هیچ
کتابخانه‌ی جدیدی -- فقط core.net، همون مسیر پروکسی‌دارِ بقیه‌ی سرویس‌ها):

  * `api/fa/v1/video/playlist/one/playlist_id/<id>` -- ویدیوهای یه
    پلی‌لیست (لینک‌های `aparat.com/playlist/<id>` یا `?playlist=<id>`).
  * `api/fa/v1/user/video/list/username/<u>` -- ویدیوهای یه کانال.
  * `api/fa/v1/user/playlist/list/username/<u>` -- پلی‌لیست‌های یه کانال.

## چرا برای این‌جا مهمه

آپارات از داخل ایران بدون فیلتر و بدون پروکسی در دسترسه، پس وقتی
یوتیوب و ساندکلاد پشت فیلترن این سرویس همچنان کار می‌کنه.
"""

import json
import re
import urllib.parse

from core import logging_setup
from core import net
from core import track_meta
from core.services._ytdlp_service import YtdlpService

SEARCH_API = "https://www.aparat.com/api/fa/v1/video/video/search/text/{query}"
VIDEO_API = "https://www.aparat.com/api/fa/v1/video/video/show/videohash/{uid}?pr=1&mf=1"
PLAYLIST_API = "https://www.aparat.com/api/fa/v1/video/playlist/one/playlist_id/{playlist_id}"
CHANNEL_VIDEOS_API = "https://www.aparat.com/api/fa/v1/user/video/list/username/{username}"
CHANNEL_PLAYLISTS_API = "https://www.aparat.com/api/fa/v1/user/playlist/list/username/{username}"
WATCH_URL = "https://www.aparat.com/v/{uid}"

#: از بین کیفیت‌های موجود کدوم رو برداریم. ربات فقط صدا پخش می‌کنه، پس
#: پایین‌ترین کیفیتِ تصویر یعنی دانلود سبک‌تر با همون صدا -- ولی خیلی
#: پایین (144p) گاهی بیت‌ریت صدا رو هم می‌شکنه، پس 480p سقف منطقیه.
#: عمداً «بهترین کیفیت» انتخاب نمی‌شه -- ربات فقط صدا پخش می‌کنه، بالاترین
#: تصویر فقط پهنای‌باند اضافه‌ست بدون فایده.
_QUALITY_ORDER = ("480p", "360p", "720p", "240p", "1080p", "144p")

# ------------------------------------------------------- شمارشِ فارسی

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
#: به ترتیب از بزرگ به کوچیک چک می‌شن، وگرنه "میلیون" با تطبیق ناقصِ
#: زودتر اشتباه می‌گرفت (اینجا فقط سه‌تاست، ترتیب فرقی نداره، ولی برای
#: خوانایی همون ترتیب بزرگ‌به‌کوچیک نگه داشته شده).
_COUNT_WORD_MULTIPLIERS = (
    ("میلیارد", 1_000_000_000),
    ("میلیون", 1_000_000),
    ("هزار", 1_000),
)


def _parse_persian_count(text):
    """
    "۱۲ هزار" -> 12000، "۳ میلیون" -> 3000000، "1,231,831" -> 1231831،
    یا None اگه قابل‌فهم نبود.

    آپارات معمولاً هم نسخه‌ی دقیق (visit_cnt_int/_non_formatted) هم
    نسخه‌ی خوانا (visit_cnt) رو برمی‌گردونه؛ این فقط برای وقتی‌ه که
    نسخه‌ی دقیق نیست (مثلاً روی پلی‌لیست‌های خالی دیده شد: مقدار عددی
    null بود ولی متن "0 " داشت).
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    text = str(text).strip().translate(_PERSIAN_DIGITS).replace(",", "")
    if not text:
        return None
    multiplier = 1
    for word, mult in _COUNT_WORD_MULTIPLIERS:
        if word in text:
            multiplier = mult
            text = text.replace(word, "")
            break
    text = text.strip()
    if not text:
        return None
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def _exact_count(attrs, text_key, *exact_keys):
    """اولویت با فیلدهای دقیق (int/non_formatted)؛ وگرنه parse متن فارسی."""
    for key in exact_keys:
        value = attrs.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return _parse_persian_count(attrs.get(text_key))


class Aparat(YtdlpService):
    SERVICE_NAME = "aparat"
    SUPPORTS_SEARCH = True
    URL_MARKERS = ("aparat.com",)
    # آپارات سرویس تصویریه، ولی ربات فقط صدا رو به کانال می‌فرسته؛
    # bestaudio/best یعنی اگه استریم جدا-صدا بود همون، وگرنه بهترین کل.
    AUDIO_ONLY = True

    def _search_stubs(self, query, count, interactive=False):
        """
        نتایج جستجوی آپارات به‌صورت stub.

        stubها همون شکلی‌ان که yt-dlp برمی‌گردونه (`url`/`title`/`id`)،
        پس بقیه‌ی زنجیره -- resolve، صف، رشد پلی‌لیست -- هیچ فرقی بین
        این و یه جستجوی معمولی yt-dlp نمی‌بینه.
        """
        try:
            payload = self._api_get(SEARCH_API.format(query=urllib.parse.quote(query)))
        except Exception as e:
            logging_setup.log_debug(f"[aparat] search API failed: {e}")
            return []

        stubs = []
        # ویدیوها توی included می‌شینن، نه data.
        for item in (payload.get("included") or []):
            stub = self._stub_from_video_item(item)
            if stub:
                stubs.append(stub)
                if len(stubs) >= count:
                    break
        return stubs

    def search(self, query):
        """
        لینک ویدیو/پلی‌لیست آپارات رو هم از مسیر API رد می‌کنیم، نه yt-dlp.

        بدون این، جستجو کار می‌کرد ولی پیست‌کردن لینک مستقیم رد می‌شد --
        چون فقط مسیر جستجو stub می‌ساخت و مسیر لینک می‌رفت سراغ همون
        اکسترکتور خرابِ yt-dlp.
        """
        query = (query or "").strip()
        if query.startswith(("http://", "https://")):
            playlist_id = self._playlist_id_from_url(query)
            if playlist_id:
                return self._search_playlist(playlist_id)
            uid = self._uid_from_url(query)
            if uid:
                self._last_playlist_info = None
                return self._resolve_entry({"id": uid, "webpage_url": query}, interactive=True)
        return super().search(query)

    def _search_playlist(self, playlist_id):
        """
        اولین ویدیوی پلی‌لیست رو resolve می‌کنه و بقیه رو برای رشدِ صف
        کش می‌کنه -- همون الگوی پلی‌لیستِ کلاس پایه، ولی با داده‌ی API
        خودِ آپارات به‌جای yt-dlp.
        """
        self._last_playlist_info = None
        entries = self.get_playlist_videos(playlist_id, count=None)
        if not entries:
            return None
        if len(entries) > 1:
            cache_key = f"aparat-playlist:{playlist_id}"
            self._stub_cache.set(cache_key, entries)
            index, first = self._first_playable(entries)
            if not first:
                return None
            self._last_playlist_info = (cache_key, len(entries), index + 1)
            return [first]
        return self._resolve_entry(entries[0], interactive=True)

    def _resolve_entry(self, entry, interactive=False):
        """
        resolve با API خود آپارات، نه با اکسترکتور yt-dlp.

        چرا: اکسترکتور آپاراتِ yt-dlp با ساختار فعلیِ صفحه هماهنگ نیست و
        با «Unable to extract og:title» رد می‌شه -- یعنی جستجو نتیجه
        می‌داد ولی هیچ‌کدوم پخش نمی‌شدن. API رسمی هم پایدارتره هم لینک
        مستقیم و بدون مرحله‌ی اضافه می‌ده.
        """
        if not entry:
            return None

        uid = entry.get("id") or self._uid_from_url(
            entry.get("webpage_url") or entry.get("url") or "")
        if not uid:
            return super()._resolve_entry(entry, interactive=interactive)

        try:
            payload = self._api_get(VIDEO_API.format(uid=uid))
        except Exception as e:
            logging_setup.log_debug(f"[aparat] video API failed for {uid}: {e}")
            # اگه API نشد، شانس آخر رو به yt-dlp می‌دیم.
            return super()._resolve_entry(entry, interactive=interactive)

        attrs = (payload.get("data") or {}).get("attributes") or {}
        stream = self._pick_stream(attrs)
        if not stream:
            return None

        username = attrs.get("owner_username") or attrs.get("username")
        info = track_meta.from_info({
            "id": uid,
            "uploader": username,
            "channel": username,
            "channel_url": f"https://www.aparat.com/{username}" if username else None,
            # mdate ISO با منطقه‌ی زمانیه؛ sdate_real بی‌منطقه و به وقت تهران.
            "timestamp": (track_meta.parse_timestamp(attrs.get("mdate"))
                          or track_meta.parse_timestamp(attrs.get("sdate_real"), 3.5 * 3600)),
            "view_count": _exact_count(attrs, "visit_cnt", "visit_cnt_non_formatted", "visit_cnt_int"),
            "like_count": _exact_count(attrs, "like_cnt", "like_cnt_non_formatted"),
            "comment_count": _exact_count(attrs, "comment_cnt", "comment_cnt_non_formatted"),
            "duration": _exact_count(attrs, "duration"),
            "description": attrs.get("description"),
            "tags": attrs.get("tags") if isinstance(attrs.get("tags"), list) else None,
            "categories": [(attrs.get("category") or {}).get("name")]
            if (attrs.get("category") or {}).get("name") else None,
        }, "aparat")
        return {
            "id": uid,
            "url": stream,
            "title": attrs.get("title") or entry.get("title") or "Unknown",
            "public_url": WATCH_URL.format(uid=uid),
            "channel_url": (f"https://www.aparat.com/{username}" if username
                            else entry.get("channel_url")),
            # متادیتای اضافه برای دستورهای i/di -- بقیه‌ی سرویس‌ها این
            # کلیدها رو ندارن، پس مصرف‌کننده‌ها باید با .get() بخونن.
            "view_count": _exact_count(attrs, "visit_cnt", "visit_cnt_non_formatted", "visit_cnt_int"),
            "like_count": _exact_count(attrs, "like_cnt", "like_cnt_non_formatted"),
            "upload_date": attrs.get("sdate_real") or attrs.get("date_exact"),
            "description": attrs.get("description"),
            "info": info,
        }

    # -------------------------------------------------------- کانال/پلی‌لیست

    def get_channel_videos(self, username, count=40):
        """لیستِ استاب ویدیوهای یه کانال (جدیدترین اول)."""
        try:
            payload = self._api_get(CHANNEL_VIDEOS_API.format(username=urllib.parse.quote(username)))
        except Exception as e:
            logging_setup.log_debug(f"[aparat] channel videos failed for {username!r}: {e}")
            return []
        stubs = []
        for item in (payload.get("included") or []):
            stub = self._stub_from_video_item(item)
            if stub:
                stubs.append(stub)
        # ترتیب یکتای لیست‌ها (نو به کهنه) روی *کل* نتیجه، بعد سقف تعداد.
        return track_meta.sort_newest_first(stubs)[:count]

    def get_channel_playlists(self, username, count=40):
        """لیستِ پلی‌لیست‌های یه کانال: [{"id","title","uid","count"}]."""
        try:
            payload = self._api_get(CHANNEL_PLAYLISTS_API.format(username=urllib.parse.quote(username)))
        except Exception as e:
            logging_setup.log_debug(f"[aparat] channel playlists failed for {username!r}: {e}")
            return []
        out = []
        for item in (payload.get("included") or []):
            if not isinstance(item, dict) or item.get("type") != "playlist":
                continue
            attrs = item.get("attributes") or {}
            out.append({
                "id": item.get("id"),
                "title": attrs.get("title") or "Unknown",
                "uid": attrs.get("uid"),
                "count": _exact_count(attrs, "cnt", "cnt"),
            })
            if len(out) >= count:
                break
        return out

    def get_playlist_videos(self, playlist_id, count=None):
        """
        استابِ ویدیوهای یه پلی‌لیست، به ترتیبِ خودِ پلی‌لیست.

        relationships.video.data فقط ترتیب/idهای JSON:API رو می‌ده؛
        متادیتای واقعی توی included می‌شینه (همون تله‌ی جستجو، این‌جا هم
        هست) -- پس اول id -> attrs رو map می‌کنیم، بعد به همون ترتیبِ
        relationships برمی‌گردونیم.
        """
        try:
            payload = self._api_get(PLAYLIST_API.format(playlist_id=playlist_id))
        except Exception as e:
            logging_setup.log_debug(f"[aparat] playlist failed for {playlist_id!r}: {e}")
            return []

        by_id = {}
        for item in (payload.get("included") or []):
            if not isinstance(item, dict) or item.get("type") != "Video":
                continue
            stub = self._stub_from_video_item(item)
            if stub:
                by_id[str(item.get("id"))] = stub

        order = (((payload.get("data") or {}).get("relationships") or {})
                 .get("video", {}).get("data") or [])
        stubs = [by_id[str(ref["id"])] for ref in order if str(ref.get("id")) in by_id]
        # اگه relationships خالی بود ولی included چیزی داشت (سازگاریِ عقب‌رو).
        if not stubs and by_id:
            stubs = list(by_id.values())
        return stubs[:count] if count else stubs

    # ---------------------------------------------------------- کمکی‌ها

    @staticmethod
    def _stub_from_video_item(item):
        if not isinstance(item, dict) or item.get("type") != "Video":
            return None
        attrs = item.get("attributes") or {}
        uid = attrs.get("uid")
        if not uid:
            return None
        return {
            "id": uid,
            "url": WATCH_URL.format(uid=uid),
            "webpage_url": WATCH_URL.format(uid=uid),
            "title": attrs.get("title") or "Unknown",
            "duration": attrs.get("duration"),
            "uploader": attrs.get("sender_name") or attrs.get("username"),
            "channel_url": (f"https://www.aparat.com/{attrs['username']}"
                             if attrs.get("username") else None),
            "view_count": _exact_count(attrs, "visit_cnt", "visit_cnt_int", "visit_cnt_non_formatted"),
            "like_count": _exact_count(attrs, "like_cnt", "like_cnt_non_formatted"),
            "upload_date": attrs.get("sdate_rss") or attrs.get("date_exact"),
            "timestamp": track_meta.parse_timestamp(attrs.get("sdate_rss"), 3.5 * 3600),
            "description": attrs.get("description"),
        }

    @staticmethod
    def _uid_from_url(url):
        parts = [p for p in (url or "").split("/") if p]
        if "v" in parts:
            index = parts.index("v")
            if index + 1 < len(parts):
                return parts[index + 1]
        return None

    @staticmethod
    def _playlist_id_from_url(url):
        """
        شناسه‌ی پلی‌لیست از `aparat.com/playlist/<id>` یا از کوئری‌
        پارامترِ `?playlist=<id>` (هر مسیر دیگه‌ای که این پارامتر رو
        داشته باشه).
        """
        parsed = urllib.parse.urlparse(url or "")
        match = re.search(r"/playlist/(\d+)", parsed.path)
        if match:
            return match.group(1)
        qs = urllib.parse.parse_qs(parsed.query)
        values = qs.get("playlist")
        if values and values[0].isdigit():
            return values[0]
        return None

    @staticmethod
    def _pick_stream(attrs):
        """بهترین کیفیتِ موجود بر اساس _QUALITY_ORDER، وگرنه اولین چیزی که هست."""
        by_profile = {}
        for item in (attrs.get("file_link_all") or []):
            if not isinstance(item, dict):
                continue
            urls = item.get("urls") or ([item["url"]] if item.get("url") else [])
            if urls:
                by_profile[str(item.get("profile") or "")] = urls[0]

        for profile in _QUALITY_ORDER:
            if by_profile.get(profile):
                return by_profile[profile]
        if by_profile:
            return next(iter(by_profile.values()))
        # بعضی ویدیوها فقط HLS دارن (مثلاً پخش زنده).
        return attrs.get("file_link") or attrs.get("hls_link") or None

    def _api_get(self, url):
        """
        یه GET ساده روی API آپارات.

        عمداً از yt-dlp رد نمی‌شه: این یه API معمولیِ JSON ـه، نه یه صفحه‌ی
        قابل‌استخراج. core.net مسیر پروکسیِ زنده‌ی بقیه‌ی سرویس‌ها رو
        همین‌جا هم اعمال می‌کنه.
        """
        _, body = net.fetch_text(url, headers={"Accept": "application/json"}, label="aparat")
        return json.loads(body)
