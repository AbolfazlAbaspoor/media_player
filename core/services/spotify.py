"""
سرویس اسپاتیفای: لینک ترک، آلبوم، پلی‌لیست، هنرمند یا اپیزود -> پخش.

استفاده:
    spt <لینک اسپاتیفای>        -> پخش (آلبوم/پلی‌لیست: اولی فوری، بقیه با n)
    spt info <لینک اسپاتیفای>   -> فقط اسم ترک‌ها و خواننده‌ها، بدون پخش

جستجوی متنی نداره، پس توی چرخه‌ی w/p نیست.

## چرا صدا از خودِ اسپاتیفای نمیاد

صدای اسپاتیفای DRM داره و yt-dlp از ۲۰۲۳ اصلاً اکسترکتور اسپاتیفای نداره.
کد قبلی همون لینک رو مستقیم به yt-dlp می‌داد، پس در بهترین حالت فقط یه
عنوان برمی‌گشت و هیچ‌وقت پخش نمی‌شد -- درحالی‌که کاتالوگ «پخش لینک
اسپاتیفای» می‌فروشه. حالا دو قدم جدا شدن:

  ۱. **متادیتا** از صفحه‌ی embed عمومی اسپاتیفای (بدون کلید و بدون لاگین):
     اسم ترک، خواننده‌ها و مدت؛ برای آلبوم/پلی‌لیست، لیست ترک‌ها. اگه اون
     صفحه جواب نداد، برای یه ترک تکی oEmbed (فقط اسم ترک).
  ۲. **صدا** از یوتیوب: «خواننده - اسم ترک» جستجو می‌شه و از چندتا نتیجه‌ی
     اول، اولین نتیجه‌ای که مدتش به ترکِ اسپاتیفای نزدیکه انتخاب می‌شه -- تا
     به‌جای آهنگ یه میکس یک‌ساعته یا یه ویدیوی دیگه پخش نشه.

هر ترک فقط وقتی نوبتش برسه resolve می‌شه (صف و رشد پلی‌لیستِ پایه)، پس یه
پلی‌لیست صدتایی قبل از اولین صدا صد جستجو نمی‌زنه.

## پایه‌ی مشترک

opts، پروکسی، استخر yt-dlp، صف، رشد پلی‌لیست و «اولین آیتمِ قابل‌پخش» از
core/services/_ytdlp_service.py میان. کوکیِ یوتیوبِ همین ربات استفاده می‌شه،
چون همه‌ی درخواست‌های صدا به یوتیوب می‌رن.
"""

import json
import re
import urllib.parse

from core import logging_setup
from core import net
from core import proxy_retry
from core.services._ytdlp_service import YtdlpService

#: ترک/آلبوم/پلی‌لیست... در همه‌ی شکل‌هاش: لینک معمولی، لینک intl-xx، لینک
#: embed، و URI خودِ اپ (spotify:track:ID).
_LINK_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z]{2}(?:-[a-z]{2})?/)?(?:embed/)?|spotify:)"
    r"(track|album|playlist|artist|episode|show)[/:]([A-Za-z0-9]{22})",
    re.IGNORECASE,
)

#: لینک‌های کوتاهِ دکمه‌ی «Share» اپ موبایل.
_SHORT_LINK_MARKERS = ("spotify.link", "spotify.app.link")

_NEXT_DATA_RE = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def canonical_link(text):
    """لینک استاندارد (https://open.spotify.com/<نوع>/<id>) یا None."""
    match = _LINK_RE.search(text or "")
    if not match:
        return None
    return f"https://open.spotify.com/{match.group(1).lower()}/{match.group(2)}"


def _id_from_uri(uri):
    """spotify:track:ID -> ID"""
    if not isinstance(uri, str) or ":" not in uri:
        return None
    return uri.rsplit(":", 1)[-1] or None


def _seconds(milliseconds):
    try:
        value = float(milliseconds)
    except (TypeError, ValueError):
        return None
    return value / 1000.0 if value > 0 else None


def _artist_names(entity):
    names = [a.get("name") for a in (entity.get("artists") or []) if isinstance(a, dict) and a.get("name")]
    return ", ".join(names) or (entity.get("subtitle") or "").strip()


def _clean(text):
    # اسپاتیفای بین اسم خواننده‌ها فاصله‌ی نشکن (\xa0) می‌ذاره؛ توی جستجوی
    # یوتیوب و پیام‌های تیم‌تاک فاصله‌ی معمولی لازمه.
    return " ".join(str(text or "").split())


def _track(track_id, title, artists, duration):
    title = _clean(title)
    if not title:
        return None
    return {"id": track_id, "title": title, "artists": _clean(artists), "duration": duration}


def _find_entity(node, depth=0):
    """
    entity رو هر جای JSON که باشه پیدا می‌کنه.

    مسیر فعلی props.pageProps.state.data.entity است، ولی اسپاتیفای ساختار
    Next.js صفحه‌هاش رو بی‌خبر عوض می‌کنه؛ جستجوی ساختاری یعنی یه جابه‌جایی
    ساده کل سرویس رو نمی‌خوابونه.
    """
    if depth > 12:
        return None
    if isinstance(node, dict):
        if isinstance(node.get("trackList"), list) and node["trackList"]:
            return node
        if node.get("type") in ("track", "episode") and (node.get("name") or node.get("title")):
            return node
        for value in node.values():
            found = _find_entity(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_entity(value, depth + 1)
            if found is not None:
                return found
    return None


def parse_embed_page(html):
    """
    (اسمِ مجموعه، [ترک‌ها]) از صفحه‌ی embed اسپاتیفای.

    هر ترک: {"id", "title", "artists", "duration"} (مدت به ثانیه یا None).
    صفحه‌ی ناشناخته یا خراب ([], نه exception) -- تصمیمِ «پیدا نشد» با
    صداکننده‌ست.
    """
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None, []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None, []

    entity = None
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        pass
    if not isinstance(entity, dict) or not (entity.get("trackList") or entity.get("name") or entity.get("title")):
        entity = _find_entity(data)
    if not isinstance(entity, dict):
        return None, []

    name = entity.get("name") or entity.get("title")
    track_list = entity.get("trackList")
    if isinstance(track_list, list) and track_list:
        tracks = []
        for item in track_list:
            if not isinstance(item, dict):
                continue
            tracks.append(_track(
                _id_from_uri(item.get("uri")) or item.get("id"),
                item.get("title") or item.get("name"),
                _artist_names(item),
                _seconds(item.get("duration")),
            ))
    else:
        tracks = [_track(
            entity.get("id") or _id_from_uri(entity.get("uri")),
            entity.get("title") or entity.get("name"),
            _artist_names(entity),
            _seconds(entity.get("duration") or entity.get("maxDuration")),
        )]
    return name, [t for t in tracks if t]


def display_name(track):
    """«خواننده - اسم ترک»، همون چیزی که هم نشون داده و هم جستجو می‌شه."""
    if track.get("artists"):
        return f"{track['artists']} - {track['title']}"
    return track["title"]


def pick_match(candidates, duration, tolerance):
    """
    از نتایج جستجوی یوتیوب (به ترتیب رتبه) کدوم پخش بشه.

    اولین نتیجه‌ای که مدتش تا tolerance ثانیه با ترک فرق داره؛ رتبه‌ی
    یوتیوب حفظ می‌شه و فقط نتیجه‌های با مدتِ کاملاً متفاوت (میکس، لایو
    طولانی، تیزر) رد می‌شن. اگه مدت معلوم نبود یا هیچ‌کدوم نزدیک نبود،
    اولین نتیجه -- یه آهنگ نزدیک بهتر از هیچه.
    """
    candidates = [c for c in (candidates or []) if c]
    if not candidates:
        return None
    if duration:
        for candidate in candidates:
            try:
                gap = abs(float(candidate.get("duration")) - float(duration))
            except (TypeError, ValueError):
                continue
            if gap <= tolerance:
                return candidate
    return candidates[0]


class Spotify(YtdlpService):
    SERVICE_NAME = "spotify"
    SUPPORTS_SEARCH = False
    URL_MARKERS = ("open.spotify.com", "spotify:") + _SHORT_LINK_MARKERS
    # صدا از یوتیوب میاد، پس کوکیِ یوتیوبِ همین ربات لازمه نه کوکی اسپاتیفای.
    COOKIE_SERVICE = "youtube"

    #: چندتا نتیجه‌ی یوتیوب برای پیدا کردنِ نسخه‌ای که مدتش جوره.
    MATCH_CANDIDATES = 5
    #: حداکثر اختلاف مدت (ثانیه) تا نتیجه «همون آهنگ» حساب بشه.
    MATCH_TOLERANCE_SECONDS = 10

    PAGE_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        "Accept-Language": "en-US,en;q=0.8",
    }

    # ------------------------------------------------------------ متادیتا

    def _fetch_text(self, url):
        """(آدرس نهایی بعد از ریدایرکت، متن صفحه) -- از مسیر مشترکِ core/net.py."""
        return net.fetch_text(url, headers=self.PAGE_HEADERS, label="spotify")

    def canonical_link(self, text):
        """
        لینک استاندارد یا None. لینک کوتاهِ اپ موبایل (spotify.link) یه
        درخواست می‌خواد تا معلوم بشه به کجا اشاره می‌کنه.
        """
        if not isinstance(text, str):
            return None
        link = canonical_link(text)
        if link or not any(marker in text.lower() for marker in _SHORT_LINK_MARKERS):
            return link
        short = text.strip()
        if not short.lower().startswith(("http://", "https://")):
            short = "https://" + short
        try:
            final_url, body = self._fetch_text(short)
        except Exception:
            return None
        return canonical_link(final_url) or canonical_link(body)

    def _oembed_title(self, link):
        try:
            _, body = self._fetch_text(
                "https://open.spotify.com/oembed?url=" + urllib.parse.quote(link, safe=""))
            return (json.loads(body).get("title") or "").strip() or None
        except Exception as e:
            logging_setup.log_debug(f"[spotify] oembed failed: {e}")
            return None

    def describe(self, text):
        """
        (اسم مجموعه، [ترک‌ها]) برای یه لینک اسپاتیفای، بدون هیچ جستجوی
        یوتیوبی. spt info و خودِ search از همین استفاده می‌کنن.
        """
        link = self.canonical_link(text)
        if not link:
            return None, []
        kind, item_id = link.rsplit("/", 2)[-2:]
        _, html = self._fetch_text(f"https://open.spotify.com/embed/{kind}/{item_id}")
        name, tracks = parse_embed_page(html)
        if not tracks and kind == "track":
            title = self._oembed_title(link)
            if title:
                tracks = [_track(item_id, title, "", None)]
        return name, tracks

    # ---------------------------------------------------------------- صدا

    def _stub(self, track, link):
        return {
            "id": track.get("id"),
            "title": display_name(track),
            "match_query": display_name(track),
            "duration": track.get("duration"),
            "webpage_url": (f"https://open.spotify.com/track/{track['id']}"
                            if track.get("id") else link),
        }

    def _best_match(self, query, duration, interactive):
        opts = dict(self._opts(interactive))
        opts["extract_flat"] = "in_playlist"
        target = f"ytsearch{self.MATCH_CANDIDATES}:{query}"
        try:
            info = proxy_retry.extract_pooled(self.SERVICE_NAME, opts, target, label=self.SERVICE_NAME)
        except Exception as e:
            logging_setup.log_debug(f"[spotify] youtube match search failed: {e}")
            return None
        return pick_match((info or {}).get("entries"), duration, self.MATCH_TOLERANCE_SECONDS)

    def _resolve_entry(self, entry, interactive=False):
        """
        stubِ اسپاتیفای -> نسخه‌ی یوتیوبیِ همون آهنگ.

        عنوان و لینک عمومی مال اسپاتیفای می‌مونن: کاربر اسپاتیفای فرستاده،
        پس «Now playing» باید اسم ترکِ اسپاتیفای رو بگه نه عنوان یه ویدیو.
        """
        if not entry:
            return None
        query = entry.get("match_query")
        if not query:
            return super()._resolve_entry(entry, interactive)
        video = self._best_match(query, entry.get("duration"), interactive)
        if not video:
            return None
        resolved = super()._resolve_entry(video, interactive)
        if not resolved:
            return None
        resolved.update({
            "id": entry.get("id") or resolved.get("id"),
            "title": entry.get("title") or resolved.get("title"),
            "public_url": entry.get("webpage_url") or resolved.get("public_url"),
            # کانالِ یوتیوبیِ یه نتیجه‌ی جستجو، کانالِ این آهنگ نیست.
            "channel_url": None,
        })
        return resolved

    def search(self, query):
        """
        لینک اسپاتیفای -> یه آیتمِ قابل‌پخش، یا برای مجموعه‌ها [اولین قابل‌پخش]
        با بقیه به‌صورت stub برای رشد صف. متن خالی یا لینکِ غیر اسپاتیفای: None.
        """
        self._last_playlist_info = None
        link = self.canonical_link(query)
        if not link:
            return None

        cached = self._search_cache.get(link)
        if cached is not None:
            return cached

        try:
            _, tracks = self.describe(link)
        except Exception as e:
            logging_setup.log_debug(f"[spotify] reading the link failed: {e}")
            return None

        stubs = [self._stub(track, link) for track in tracks]
        if not stubs:
            return None

        if len(stubs) == 1:
            resolved = self._resolve_entry(stubs[0], interactive=True)
            if resolved:
                self._search_cache.set(link, resolved)
            return resolved

        self._stub_cache.set(link, stubs)
        index, first = self._first_playable(stubs)
        if not first:
            return None
        self._last_playlist_info = (link, len(stubs), index + 1)
        return [first]
