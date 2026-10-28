"""
پخشِ زنده با قابلیتِ برگشت به عقب (DVR) -- دستور cld.

## چرا cl کافی نیست

mpv یه لینکِ HLS زنده رو (چیزی که cl/core/services/youtube.py::get_channel_live
می‌ده) به‌عنوانِ یه استریمِ شبکه باز می‌کنه، نه یه فایل؛ حتی اگه سرورِ
یوتیوب چند ساعت بافر نگه داشته باشه (playlist_type=DVR توی خودِ منیفست)،
mpv فقط چند ثانیه‌ی آخر رو seekable می‌بینه -- تست زنده (پایینِ همین فایل
توی داکیومنتِ agent-a87989c5f935005bd تأیید شده) نشون داد duration/seekable
هیچ ربطی به چیزی که سرور واقعاً نگه داشته نداره.

## راه‌حل: دانلودِ پس‌زمینه با yt-dlp

yt-dlp یه گزینه‌ی مستندشده داره: `live_from_start=True` -- با این، خودِ
yt-dlp (نه mpv) از *ابتدای* پخشِ زنده مدام فرگمنت دانلود می‌کنه و به یه
فایلِ محلی می‌نویسه. تستِ زنده (روی یه کانالِ واقعاً لایو، از پشتِ پروکسیِ
127.0.0.1:2080) نشون داد:

  * فرمتِ صوتیِ خالص (مثلاً itag 140، m4a/AAC) با پروتکلِ
    `http_dash_segments_generator` می‌آد -- یه فایلِ fragmented-mp4 که
    yt-dlp تکه‌به‌تکه بهش append می‌کنه (اسمش تا آخرِ دانلود `....m4a.part`
    می‌مونه؛ چون سشنِ ما هیچ‌وقت "کامل" نمی‌شه -- همیشه یا کاربر متوقفش
    می‌کنه یا سقفِ منابع می‌رسه -- همیشه همینِ `.part` رو مستقیم به mpv
    می‌دیم، نه اسمِ نهایی).
  * mpv (از طریق libmpv/python-mpv، دقیقاً همون کتابخونه‌ای که
    core/mpv/player.py استفاده می‌کنه) این فایلِ محلی رو seekable=True
    می‌بینه، و seek نسبی به عقب (`raw.seek(-n, reference="relative")`) --
    دقیقاً همون چیزی که دستورهای `+`/`-` (core/mpv/player.py::seek_relative)
    صدا می‌زنن -- واقعاً کار می‌کنه: تا جایی که دانلود شده می‌ره عقب و اگه
    بیشتر از بافرِ موجود بخوای، به‌جای خطا/کرش فقط clamp می‌شه به اولِ
    بافر.
  * نکته‌ی مهم: وقتی پخش به لبه‌ی چیزی که تا اون لحظه دانلود شده می‌رسه
    (EOF محلی، نه لایو واقعی)، mpv با تنظیماتِ پیش‌فرض فایل رو "تموم‌شده"
    حساب می‌کنه و player رو idle می‌کنه -- برخلافِ استریمِ شبکه که خودش
    منتظر داده‌ی بیشتر می‌مونه. راه‌حلِ تستِ‌شده: `keep_open=yes` +
    `keep_open_pause=no` روی mpv (فقط تا وقتی سشنِ DVR فعاله، بعدش مثلِ
    core/iptv.py::_restore_player_headers برمی‌گرده) -- با این، mpv منتظر
    می‌مونه تا فایل بازم رشد کنه، دقیقاً مثلِ یه استریمِ زنده‌ی واقعی.

## سقفِ منابع (چرا لایسنسِ جدا)

بر خلافِ cl (که فقط یه لینک resolve می‌کنه)، این قابلیت تا وقتی فعاله یه
پروسه/ترد yt-dlp دائم داره از شبکه دانلود می‌کنه و روی دیسک می‌نویسه --
هم CPU/شبکه‌ی مداوم هم فضای موقت. برای همین:

  1. لایسنسِ جدا (`cap_live_dvr` توی licensing/catalog.py، نه بسته‌شده با
     cap_channel_live) و گرون‌تر.
  2. سقفِ سخت روی زمان (`max_minutes`) و حجم (`max_megabytes`) --
     core/config_defaults.py::LIVE_DVR_DEFAULTS. هر کدوم زودتر برسه،
     تابعِ داخلِ progress_hook (core.live_dvr._download_thread) یه DownloadCancelled می‌ندازه و
     دانلود متوقف می‌شه -- ولی فایلِ تا اون لحظه دانلودشده پاک نمی‌شه؛
     پخش/سیک توی همون بافر ادامه پیدا می‌کنه، فقط دیگه جلوتر نمی‌ره.
     این یه trade-off عمدیه: به‌جای یه ring-buffer واقعی (که پیاده‌سازیش
     برای یه فایلِ fragmented-mp4 که وسطش نمی‌شه از اول برید بدونِ خرابکردنِ
     seek، خیلی پیچیده و پرخطر می‌شد)، یه سقفِ سادهٔ "توقفِ رشد" داریم.

## v2: شروع از لبه‌ی لایو + بافرِ عقبِ انتخابی (cld [minutes])

مشکلِ نسخه‌ی اول (با خوندنِ سورسِ yt-dlp تأیید شد،
extractor/youtube/_video.py::_live_adaptive_fragments): مولدِ فرگمنت‌ها با
`begin_index = 0` شروع می‌کنه، یعنی از *اولِ برودکست* (تا ۱۲۰ ساعتِ عقب) و
ترتیبی پیش می‌ره؛ پس پخش از اولِ برودکست شروع می‌شد و فقط تا همون‌جایی
که دانلود رسیده بود می‌شد سیک کرد -- نه لبه‌ی لایو، نه عقب‌تر از بافر.
(تستِ زنده‌ی کاملِ این مسیر توی محیطِ توسعه ممکن نشد: پروکسیِ تست از
طرفِ یوتیوب «Sign in to confirm you're not a bot» می‌گیره و بدونِ کوکی
استخراج انجام نمی‌شه؛ منطقِ جدید با تستِ واحد و خوندنِ سورس پوشش داده شده.)

راه‌حل: yt-dlp فقط *استخراج* می‌کنه (extract_info بدونِ دانلود)؛
خودِ فرمت یه مولدِ `fragments(ctx)` داره که URLهای `...&sq=N` می‌ده و
`fragment_count` = شماره‌ی سرِ فعلیِ لایو (X-Head-Seqnum). ما:
  1. اولین آیتمِ مولد رو می‌خونیم تا head رو بدونیم،
  2. start_sq = head - minutes*60/طولِ فرگمنت رو حساب می‌کنیم،
  3. هدرِ MP4 (ftyp+moov) رو از sq=0 جدا می‌کنیم (بقیه‌ی sq=0 مدیای
     اولِ برودکسته و دور ریخته می‌شه)،
  4. فرگمنت‌های [start_sq, head) رو هم‌زمان (چند ترد، ولی به ترتیبِ
     درست روی فایل) دانلود می‌کنیم -- backfill،
  5. بعدش همون مولد مدام فرگمنتِ تازه می‌ده و ما append می‌کنیم (tail).
mpv فقط وقتی backfill تموم شد فایل رو باز می‌کنه و سیک می‌کنه به انتهای
فایل = لبه‌ی لایو؛ پس پخش از لبه‌ی لایو شروع می‌شه و با +/- می‌شه تا
ابتدای backfill (یعنی `minutes` دقیقه عقب) رفت.

محدودیت‌های صادقانه: (۱) فایل append-only است، پس عقب‌ترین نقطه همون
لحظه‌ی شروعه و بعداً نمی‌شه عقب‌تر کشیدش؛ برای عقب‌تر باید دوباره
`cld <بیشتر>` زد. (۲) سقفِ آرگومان max_back_minutes و سقفِ حجمِ
max_megabytes؛ یوتیوب هم خودش تا ۱۲۰ ساعت نگه می‌داره. (۳) دقتِ «دقیقه»
به طولِ فرگمنت (target_duration، پیش‌فرض ۲ ثانیه) بستگی داره. (۴) اگه فرمتِ
مولددار پیدا نشه، به مسیرِ قدیمی (yt-dlp از اولِ برودکست) برمی‌گردیم.

## پاکسازی

فایلِ موقت هیچ‌وقت توی data/ نیست -- هر سشن پوشه‌ی خودش رو با
`tempfile.mkdtemp` می‌سازه (کنارِ بقیه‌ی فایل‌های موقتِ سیستم، نه پروژه)
و `clear()` هم ترد دانلود رو متوقف می‌کنه (stop_event) هم کل پوشه رو پاک
می‌کنه. `clear()` از دو جا صدا زده می‌شه (bot.py):
  * `load_and_play` -- هر پخشِ دیگه‌ای (سرچ، لینک، cl معمولی) سشنِ DVR رو
    می‌بنده، دقیقاً مثلِ iptv.clear/documentary.clear.
  * `stop_player` -- s/ss/قطع‌اتصال/full_shutdown هم نباید یه دانلودِ
    پس‌زمینه‌ی یتیم جا بذارن.
"""

import collections
import concurrent.futures
import os
import shutil
import struct
import tempfile
import threading
import time
import urllib.parse

from core import command_helpers
from core import config_defaults
from core import i18n
from core import license_gate
from core import logging_setup
from core import proxy_state
from core import ytdlp_lazy
from core import ytdlp_opts

SERVICE_NAME = "live_dvr"

DEFAULTS = config_defaults.LIVE_DVR_DEFAULTS

# حداقل حجمی که باید قبل از شروعِ پخش دانلود شده باشه -- خیلی کم باشه
# mpv فوراً به EOF می‌خوره و idle می‌شه؛ خیلی زیاد باشه کاربر معطل می‌مونه.
_MIN_BUFFER_BYTES = 150 * 1024
# سقفِ زمانِ انتظار برای بافرِ اولیه، جدا از start_wait_seconds (که فقط
# "حداقلِ" انتظاره) -- تا یه لایوِ کند/پروکسیِ کند کاربر رو تا ابد معطل نکنه.
_START_TIMEOUT_EXTRA_SECONDS = 20
# فاصله‌ی ایمن از انتهای فایل هنگامِ پرش به لبه‌ی لایو.
_EDGE_MARGIN_SECONDS = 4


class LiveDVRError(Exception):
    """خطای قابل‌نمایش به کاربر (لایسنس نداره، شروع نشد، ...)."""


# ---------------------------------------------------------------- تنظیمات

def settings(bot):
    return config_defaults.feature_settings(bot, "live_dvr", DEFAULTS)


def max_minutes(bot):
    return config_defaults.positive_int_setting(settings(bot), "max_minutes", DEFAULTS)


def default_back_minutes(bot):
    return config_defaults.positive_int_setting(settings(bot), "default_back_minutes", DEFAULTS)


def max_back_minutes(bot):
    return config_defaults.positive_int_setting(settings(bot), "max_back_minutes", DEFAULTS)


def backfill_timeout_seconds(bot):
    return config_defaults.positive_int_setting(settings(bot), "backfill_timeout_seconds", DEFAULTS)


def max_megabytes(bot):
    return config_defaults.positive_int_setting(settings(bot), "max_megabytes", DEFAULTS)


def start_wait_seconds(bot):
    return config_defaults.positive_int_setting(settings(bot), "start_wait_seconds", DEFAULTS)


def licensed(bot):
    """آیا این ربات اجازه‌ی این قابلیت رو داره؟ (لایسنسِ جدا از cap_channel_live)."""
    return license_gate.bot_allows_service(bot, SERVICE_NAME)


# --------------------------------------------------------------- yt-dlp

def _cookiefile_for(service):
    """اگه سرویسِ کانالِ فعلی (معمولاً youtube) یه cookiefile داره همون رو برگردون."""
    return getattr(service, "_cookiefile", None)


def _ytdlp_opts(cookiefile=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "logger": logging_setup.get_ytdlp_logger(),
    }
    proxy_url = proxy_state.get_proxy_url()
    if proxy_url:
        opts["proxy"] = proxy_url
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return ytdlp_opts.with_js_runtime(opts)


# ------------------------------------------------------------- سشن/پخش

def _player_raw(bot):
    player = getattr(bot, "player", None)
    return getattr(player, "raw", None) if player is not None else None


_KEEP_OPEN_PROPERTIES = ("keep_open", "keep_open_pause")


def _apply_keep_open(bot, session):
    """
    mpv رو موقتاً keep_open=yes می‌کنه تا وقتی پخش به لبه‌ی چیزی که تا اون
    لحظه دانلود شده رسید (EOF محلی)، به‌جای idle‌شدن منتظرِ رشدِ بیشترِ
    فایل بمونه -- تستِ زنده بالای فایل توضیح داده شده. مقدارهای قبلی برای
    clear() نگه داشته می‌شن (دقیقاً مثلِ core/iptv.py::apply_stream_headers).
    """
    raw = _player_raw(bot)
    if raw is None:
        return
    defaults = {}
    for name in _KEEP_OPEN_PROPERTIES:
        try:
            defaults[name] = getattr(raw, name)
        except Exception:
            defaults[name] = None
    session["keep_open_defaults"] = defaults
    try:
        raw.keep_open = "yes"
        raw.keep_open_pause = "no"
    except Exception:
        logging_setup.log_debug("live_dvr: could not set keep_open")


def _restore_keep_open(session):
    defaults = session.get("keep_open_defaults")
    bot = session.get("bot")
    if not defaults or bot is None:
        return
    raw = _player_raw(bot)
    if raw is None:
        return
    for name, value in defaults.items():
        if value is None:
            continue
        try:
            setattr(raw, name, value)
        except Exception:
            logging_setup.log_debug(f"live_dvr: could not restore player {name}")


def _find_part_file(tmpdir):
    """
    فایلِ اصلیِ در-حال-دانلود رو پیدا می‌کنه: چیزی که به `.part` تموم می‌شه
    ولی خودش یه فرگمنتِ تکی نیست (اون‌ها `.part-FragN.part` هستن).
    بزرگ‌ترین همچین فایلی انتخاب می‌شه (معمولاً فقط یکی هست).
    """
    try:
        names = os.listdir(tmpdir)
    except OSError:
        return None
    candidates = [n for n in names if n.endswith(".part") and ".part-Frag" not in n]
    if not candidates:
        return None
    candidates.sort(key=lambda n: os.path.getsize(os.path.join(tmpdir, n)), reverse=True)
    return os.path.join(tmpdir, candidates[0])


def is_active(bot):
    session = getattr(bot, "live_dvr_session", None)
    return bool(session and session.get("active"))


def _download_thread(bot, session, watch_url, cookiefile, cap_seconds, cap_bytes):
    start_time = time.time()

    def hook(d):
        if session["stop_event"].is_set():
            raise ytdlp_lazy.download_cancelled()("live_dvr: stopped")
        downloaded = d.get("downloaded_bytes") or 0
        if (time.time() - start_time) > cap_seconds or downloaded > cap_bytes:
            raise ytdlp_lazy.download_cancelled()("live_dvr: resource cap reached")

    opts = _ytdlp_opts(cookiefile)
    opts.update({
        "live_from_start": True,
        "format": "ba/b",
        "outtmpl": os.path.join(session["tmpdir"], "stream.%(ext)s"),
        "progress_hooks": [hook],
    })
    try:
        with ytdlp_lazy.YoutubeDL(opts) as ydl:
            ydl.download([watch_url])
    except ytdlp_lazy.download_cancelled():
        logging_setup.log_debug("[live_dvr] download stopped (cap or explicit stop)")
    except Exception as e:
        logging_setup.log_debug(f"[live_dvr] download failed: {e}")
    finally:
        session["download_done"] = True


# ------------------------------------------------- دانلودِ v2 (sq-based)

_DEFAULT_FRAGMENT_SECONDS = 2.0
_BACKFILL_WORKERS = 6
_FRAGMENT_RETRIES = 3


def split_mp4_header(data):
    """
    از بدنه‌ی sq=0 فقط باکس‌های سطحِ بالای ftyp و moov رو نگه می‌داره (هدرِ
    init)؛ moof/mdat/sidx/styp (مدیای اولِ برودکست) دور ریخته می‌شه. اگه
    باکسِ خراب بود همون‌جا می‌ایسته. خروجی b"" یعنی moov پیدا نشد.
    """
    out = []
    pos, n = 0, len(data)
    have_moov = False
    while pos + 8 <= n:
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        if size == 1 and pos + 16 <= n:
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
        elif size == 0:
            size = n - pos
        if size < 8 or pos + size > n:
            break
        if kind in (b"ftyp", b"moov"):
            out.append(data[pos:pos + size])
            have_moov = have_moov or kind == b"moov"
        pos += size
    return b"".join(out) if have_moov else b""


def _sq_of(url):
    try:
        return int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["sq"][0])
    except (KeyError, ValueError, IndexError):
        return None


def _with_sq(url, sq):
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    query["sq"] = [str(sq)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query, doseq=True)))


def compute_start_sq(head, minutes, fragment_seconds):
    """شماره‌ی اولین فرگمنتِ backfill (sq=0 فقط برای هدره، پس حداقل ۱)."""
    frag = fragment_seconds if fragment_seconds and fragment_seconds > 0 else _DEFAULT_FRAGMENT_SECONDS
    back = int(round(minutes * 60 / frag))
    return max(1, head - back)


def find_fragment_generator(info):
    """مولدِ fragments(ctx) رو از نتیجه‌ی استخراج در میاره (یا None)."""
    for fmt in (info.get("requested_formats") or [info]):
        if callable(fmt.get("fragments")):
            return fmt["fragments"], fmt.get("target_duration")
    return None, None


def _fetch(ydl, url, stop_event):
    last = None
    for _ in range(_FRAGMENT_RETRIES):
        if stop_event.is_set():
            return None
        try:
            return ydl.urlopen(url).read()
        except Exception as e:
            last = e
            time.sleep(0.5)
    logging_setup.log_debug(f"[live_dvr] fragment failed: {logging_setup.safe_error_text(last)}")
    return None


def _dvr_thread(bot, session, watch_url, cookiefile, back_minutes, cap_seconds, cap_bytes):
    """
    دانلودِ v2: backfill [start_sq, head) هم‌زمان + بعدش tail زنده. توضیح بالای
    فایل. اگه مولد پیدا نشد به _download_thread (مسیرِ قدیمی) برمی‌گرده.
    """
    if _dvr_download(session, watch_url, cookiefile, back_minutes, cap_seconds, cap_bytes):
        _download_thread(bot, session, watch_url, cookiefile, cap_seconds, cap_bytes)


def _dvr_download(session, watch_url, cookiefile, back_minutes, cap_seconds, cap_bytes):
    """True یعنی مولدِ فرگمنت پیدا نشد و باید مسیرِ قدیمی اجرا بشه."""
    stop = session["stop_event"]
    out_path = os.path.join(session["tmpdir"], "stream.dvr.part")
    opts = _ytdlp_opts(cookiefile)
    opts.update({"live_from_start": True, "format": "ba/b"})
    written = 0
    started_tail = None
    legacy = False
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=_BACKFILL_WORKERS)
    try:
        with ytdlp_lazy.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(watch_url, download=False)
            gen_fn, frag_seconds = find_fragment_generator(info or {})
            if gen_fn is None:
                legacy = True
                return True
            frags = iter(gen_fn({"start": time.time()}))
            first = next(frags, None)
            if first is None:
                return False
            head = first.get("fragment_count") or _sq_of(first["url"]) or 0
            start_sq = compute_start_sq(head, back_minutes, frag_seconds)
            session["head_sq"] = head
            session["start_sq"] = start_sq

            header = split_mp4_header(_fetch(ydl, _with_sq(first["url"], 0), stop) or b"")
            if not header:
                logging_setup.log_debug("[live_dvr] no mp4 header in sq=0")
                return False
            with open(out_path, "wb") as fh:
                fh.write(header)
                written = len(header)
                fh.flush()
                pending = collections.deque()

                def flush(limit):
                    nonlocal written
                    while len(pending) > limit:
                        data = pending.popleft().result()
                        if data:
                            fh.write(data)
                            fh.flush()
                            written += len(data)

                def items():
                    yield first
                    yield from frags

                for frag in items():
                    if stop.is_set():
                        return False
                    sq = _sq_of(frag["url"])
                    if sq is not None and sq < start_sq:
                        continue
                    in_backfill = sq is not None and sq < head
                    if not in_backfill and started_tail is None:
                        flush(0)
                        started_tail = time.time()
                        session["backfill_done"].set()
                    pending.append(pool.submit(_fetch, ydl, frag["url"], stop))
                    flush(_BACKFILL_WORKERS if in_backfill else 0)
                    if written > cap_bytes:
                        return False
                    if started_tail is not None and time.time() - started_tail > cap_seconds:
                        return False
                flush(0)
    except Exception as e:
        logging_setup.log_debug(f"[live_dvr] v2 download failed: {logging_setup.safe_error_text(e)}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        session["backfill_done"].set()
        if not legacy:
            session["download_done"] = True
    return False


def start(bot, service, channel_url, requested_by=None, back_minutes=None):
    """
    سشنِ DVR رو برای لایوِ *همین‌الانِ* channel_url شروع می‌کنه.

    خروجی: dict {"title": ...} در موفقیت، یا None اگه کانال الان لایو
    نیست (خطا نیست -- جوابه، دقیقاً مثلِ core/services/youtube.py::get_channel_live).
    خطا: LiveDVRError با متنِ قابل‌نمایش.
    """
    if not licensed(bot):
        raise LiveDVRError(i18n.t("live_dvr_not_licensed"))

    try:
        live_items = service.get_channel_live(channel_url)
    except Exception as e:
        raise LiveDVRError(i18n.t("command_error", error=logging_setup.safe_error_text(e)))
    if not live_items:
        return None

    item = live_items[0]
    watch_url = item.get("public_url") or item.get("url")
    title = item.get("title") or "-"
    if not watch_url:
        raise LiveDVRError(i18n.t("live_dvr_start_failed"))

    # هر سشنِ قبلی (ولو مالِ همین کانال) قبل از شروعِ تازه بسته می‌شه --
    # وگرنه دو تا دانلودِ پس‌زمینه هم‌زمان روشن می‌موند.
    clear(bot)

    tmpdir = tempfile.mkdtemp(prefix="cp_live_dvr_")
    session = {
        "bot": bot,
        "tmpdir": tmpdir,
        "stop_event": threading.Event(),
        "thread": None,
        "download_done": False,
        "backfill_done": threading.Event(),
        "active": False,
        "keep_open_defaults": None,
        "channel_url": channel_url,
    }
    bot.live_dvr_session = session

    if back_minutes is None:
        back_minutes = default_back_minutes(bot)
    back_minutes = max(1, min(int(back_minutes), max_back_minutes(bot)))
    session["back_minutes"] = back_minutes
    cap_seconds = max_minutes(bot) * 60
    cap_bytes = max_megabytes(bot) * 1024 * 1024
    cookiefile = _cookiefile_for(service)

    thread = threading.Thread(
        target=_dvr_thread,
        args=(bot, session, watch_url, cookiefile, back_minutes, cap_seconds, cap_bytes),
        daemon=True,
    )
    session["thread"] = thread
    thread.start()

    # تا backfill تموم نشه پخش شروع نمی‌شه (وگرنه mpv وسطِ دانلود به EOF
    # می‌خوره و «لبه‌ی لایو» هنوز مشخص نیست).
    wait_seconds = start_wait_seconds(bot)
    deadline = time.time() + wait_seconds + _START_TIMEOUT_EXTRA_SECONDS + backfill_timeout_seconds(bot)
    part_path = None
    while time.time() < deadline:
        part_path = _find_part_file(tmpdir)
        if (session["backfill_done"].is_set() and part_path
                and os.path.getsize(part_path) >= _MIN_BUFFER_BYTES):
            break
        if session["download_done"] and not thread.is_alive():
            # ترد قبل از رسیدن به حداقلِ بافر تموم شده -- یعنی خطا/کنسل زودهنگام.
            break
        time.sleep(0.3)

    if not part_path or not os.path.exists(part_path) or os.path.getsize(part_path) < _MIN_BUFFER_BYTES:
        clear(bot)
        raise LiveDVRError(i18n.t("live_dvr_start_failed"))

    _apply_keep_open(bot, session)

    play_item = {"url": part_path, "title": title, "public_url": None, "verified_media": True}
    try:
        bot.load_and_play(play_item, private=True, service_name=SERVICE_NAME)
    except Exception as e:
        clear(bot)
        raise LiveDVRError(i18n.t("command_error", error=logging_setup.safe_error_text(e)))

    if not command_helpers._confirm_playback(bot):
        clear(bot)
        raise LiveDVRError(i18n.t("live_dvr_start_failed"))

    _seek_to_live_edge(bot)
    session["active"] = True
    return {"title": title, "back_minutes": back_minutes}


def _seek_to_live_edge(bot):
    """پخش از ابتدای backfill شروع می‌شه؛ می‌پریم نزدیکِ انتهای فایل (لبه‌ی لایو)."""
    raw = _player_raw(bot)
    if raw is None:
        return
    try:
        duration = float(getattr(raw, "duration", 0) or 0)
        if duration > _EDGE_MARGIN_SECONDS:
            raw.seek(duration - _EDGE_MARGIN_SECONDS, reference="absolute")
    except Exception:
        logging_setup.log_debug("live_dvr: could not seek to live edge")


def clear(bot):
    """
    سشنِ DVR رو می‌بنده (اگه فعال باشه): ترد دانلود رو متوقف می‌کنه،
    تنظیماتِ mpv رو برمی‌گردونه، و کل پوشه‌ی موقت رو پاک می‌کنه. صداکردنش
    وقتی سشنی در جریان نیست کاملاً بی‌خطره (no-op). دقیقاً مثلِ
    core/iptv.py::clear، از load_and_play و bot.py::stop_player صدا زده می‌شه.
    """
    session = getattr(bot, "live_dvr_session", None)
    bot.live_dvr_session = None
    if not session:
        return
    stop_event = session.get("stop_event")
    if stop_event:
        stop_event.set()
    thread = session.get("thread")
    if thread and thread.is_alive():
        thread.join(timeout=5)
    _restore_keep_open(session)
    tmpdir = session.get("tmpdir")
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
