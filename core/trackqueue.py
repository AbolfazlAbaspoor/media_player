"""
صف پخش مستقل از mpv.

## چرا این لازم بود

قبلاً «صف» همون پلی‌لیست داخلی mpv بود و `n` یعنی `mpv.playlist_next()`.
چهار مشکل جدی داشت:

  ۱. **همه‌ی آیتم‌ها باید از قبل resolve می‌شدن** تا بشه ریختشون توی
     پلی‌لیست mpv. برای یه پلی‌لیست ۵۰تایی یعنی ۵۰ استخراج قبل از شنیدن
     آهنگ اول -- و لینک‌های استریم یوتیوب چند ساعته منقضی می‌شن، پس نصف
     اون کار هم هدر می‌رفت.
  ۲. **رشد صف با حدس و گمان** انجام می‌شد: «اگه تا ۵ آیتم به آخر رسیدیم و
     قبلاً loading نبود، شاید...». هر کدوم از این شرط‌ها اشتباه می‌زد،
     `n` می‌گفت «آخر صفه» در حالی که نبود.
  ۳. **`n` تا ۴ ثانیه بلاک می‌کرد**: اگه `playlist_next()` شکست می‌خورد،
     یه حلقه‌ی sleep راه می‌افتاد به امید این‌که رشد پس‌زمینه آیتم اضافه کنه.
  ۴. **مصرف حافظه**: mpv برای هر آیتم پلی‌لیست ساختار نگه می‌داره.

## مدل جدید

این کلاس صاحب حقیقته. mpv در هر لحظه **فقط یک آیتم** دارد:

    items: [Track, Track, Track, ...]   <- صف ما، شامل stub های resolve‌نشده
    index: 3                            <- کرسر
                 |
                 v
    mpv: فقط URL آیتم شماره ۳

`n` فقط کرسر رو جلو می‌بره و URL جدید رو به mpv می‌ده. **همیشه فوری و
قطعی** -- چون هیچ‌چیزی به وضعیت داخلی mpv وابسته نیست.

## سرعت: prefetch

وقتی آیتم n پخش می‌شه، آیتم n+1 (و n+2) در پس‌زمینه resolve می‌شن. پس وقتی
کاربر `n` می‌زنه، لینک از قبل آماده‌ست و پخش **بدون هیچ تأخیری** شروع
می‌شه. این تنها جاییه که resolve روی مسیر کاربر نیست.

## رشد

وقتی کرسر به GROWTH_THRESHOLD آیتم آخر می‌رسه، grow_fn صدا زده می‌شه تا
آیتم بیشتری بیاره. برخلاف قبل، این یه حدس نیست: خودِ صف می‌دونه چند آیتم
مونده، چون خودش صاحب لیسته.

## نکته‌ی مهم برای نگه‌داری

هیچ‌کدوم از متدهای این کلاس نباید I/O شبکه‌ای *داخل قفل* انجام بدن. قفل فقط
برای تغییر لیست و کرسره؛ resolve و پخش بیرون قفل انجام می‌شن، وگرنه یه
استخراج کند کل ربات رو قفل می‌کرد.
"""

import random
import threading

from core import logging_setup
from core import track_meta

# چند آیتم جلوتر از کرسر از قبل resolve بشه.
DEFAULT_PREFETCH = 2

# وقتی این تعداد آیتم یا کمتر تا آخر صف مونده، رشد رو راه بنداز.
GROWTH_THRESHOLD = 3

# حالت‌های پخش (همون اعدادی که دستور m استفاده می‌کنه). این‌ها فقط رفتارِ
# «آهنگ تموم شد» رو تعیین می‌کنن (advance/on_track_finished پایین‌تر) --
# نه این‌که چندتا آیتم توی صف بریزیم. قبلاً SINGLE_TRACK_MODES این دو مسئله
# رو قاطی می‌کرد: replace/append صف رو به یک آیتم محدود می‌کردن، یعنی توی
# مُد «تک‌آهنگ» یا «تکرار آهنگ» جستجو/پلی‌لیست هیچ‌وقت رشد نمی‌کرد.
MODE_SINGLE = 1
MODE_PLAYLIST = 2
MODE_REPEAT_TRACK = 3
MODE_REPEAT_PLAYLIST = 4


class Track:
    """
    یه آیتم صف. ممکنه resolve شده باشه (url داره) یا فقط یه stub باشه.

    __slots__ عمدیه: روی یه سرور ضعیف با چند ربات و صف‌های بزرگ، هر
    dict اضافه‌ی هر آیتم واقعاً دیده می‌شه.
    """

    __slots__ = ("url", "title", "public_url", "private", "service",
                 "stub", "fallback_label", "failed", "duration", "info")

    def __init__(self, url=None, title=None, public_url=None, private=True,
                 service=None, stub=None, fallback_label=None, duration=None, info=None):
        self.url = url
        self.title = title
        self.public_url = public_url
        self.private = private
        self.service = service
        self.stub = stub
        self.fallback_label = fallback_label
        self.failed = False
        self.duration = duration
        # متادیتای نرمال (core/track_meta.py) برای i/di؛ موقع resolve پر می‌شه.
        self.info = dict(info) if info else {}

    @property
    def resolved(self):
        return bool(self.url)

    def label(self):
        return self.title or self.fallback_label or "..."

    def as_meta(self):
        """
        همون شکلی که bot.track_meta همیشه داشته -- تا دستورهای موجود
        (i, di, dl, af, k, ...) بدون تغییر کار کنن.
        """
        return {
            "title": self.title,
            "public_url": self.public_url,
            "private": self.private,
            "fallback_label": self.fallback_label,
            "service": self.service,
            "info": self.info,
        }

    @classmethod
    def from_item(cls, item, private=True, service=None):
        """
        از هر چیزی که load_and_play قبول می‌کنه یه Track می‌سازه:
        رشته (لینک)، dict با url/title/public_url، یا یه stub سرویس.
        """
        if isinstance(item, Track):
            return item
        if isinstance(item, str):
            return cls(url=item, private=private, service=service,
                       fallback_label=_netloc(item))
        if isinstance(item, dict):
            url = item.get("url")
            # اگه خودِ آیتم صراحتاً "private" داشته باشه (مثلاً رشدِ خودکارِ
            # صف که ممکنه از یه دسته‌ی سرچِ عمومی باشه، نه از پیوستِ لینکِ
            # خصوصیِ کاربر)، همون اولویت داره؛ وگرنه مقدارِ کل دسته (private
            # پارامترِ replace/append) به‌کار می‌ره. قبلاً همیشه مقدارِ کل
            # دسته اعمال می‌شد، یعنی هر چیزی که با append به صف اضافه می‌شد
            # (رشدِ سرچ) خصوصی حساب می‌شد چون append پیش‌فرضش private=True
            # است -- در نتیجه k روی آیتم دوم به بعدِ هر سرچی همیشه «لینک
            # خصوصیه» می‌گفت.
            item_private = item.get("private", private)
            return cls(
                url=url,
                title=item.get("title"),
                public_url=item.get("public_url"),
                private=item_private,
                service=service or item.get("service"),
                stub=item.get("stub"),
                fallback_label=_netloc(url) if url else None,
                duration=item.get("duration"),
                info=item.get("info"),
            )
        return cls(stub=item, private=private, service=service)


def _netloc(url):
    try:
        import urllib.parse
        return urllib.parse.urlparse(url).netloc or None
    except Exception:
        return None


class TrackQueue:
    """
    play_fn(url)        -> به mpv می‌گه این URL رو پخش کن
    resolve_fn(track)   -> stub رو به لینک واقعی تبدیل می‌کنه (اختیاری)
    grow_fn(needed)     -> آیتم بیشتری میاره (اختیاری)، لیست Track/dict برمی‌گردونه
    submit_fn(fn, *a)   -> اجرای کار پس‌زمینه (core.workers.submit)
    """

    def __init__(self, play_fn, resolve_fn=None, grow_fn=None, submit_fn=None,
                 prefetch=DEFAULT_PREFETCH):
        self._play = play_fn
        self._resolve = resolve_fn
        self._grow = grow_fn
        self._submit = submit_fn
        self.prefetch_count = prefetch

        self._lock = threading.RLock()
        # قفلِ جداگانه‌ی جابه‌جایی (n/b/jump/on_track_finished). هر دستورِ
        # کاربر توی ترد جدای خودشه (bot.py) و on_track_finished توی ترد
        # حلقه‌ی اصلیه -- بدونِ این قفل، یه دستورِ دستی و تشخیصِ خودکارِ
        # «آهنگ تموم شد» می‌تونستن هم‌زمان هر دو advance() رو صدا بزنن و
        # صف دو قدم با هم جلو بره (دو پیامِ Now playeing پشتِ‌سرهم برای
        # دو آیتمِ متوالی -- باگی که کاربر گزارش داد). RLock چون
        # on_track_finished از همین تردی که خودش قفل رو گرفته advance()
        # رو دوباره صدا می‌زنه.
        self._nav_lock = threading.RLock()
        self._items = []
        self._index = -1
        self._mode = MODE_PLAYLIST
        # True از لحظه‌ی شروع پخش تا stop() -- برای تشخیص «آهنگ تموم شد»
        # از «ما عمداً متوقف کردیم».
        self._active = False
        self._growing = False
        # با هر replace/clear یکی زیاد می‌شه؛ رشدِ در حال اجرا برای صفِ قبلی
        # (سرچ/پلی‌لیست قدیمی) با همین شماره تشخیص داده و دور ریخته می‌شه.
        self._epoch = 0
        self._resolving = set()
        # وقتی منبع می‌دونه کل چند آیتمه (پلی‌لیست بزرگ)، برای نمایش.
        self.expected_total = 0

    # ------------------------------------------------------------ خواندن

    @property
    def length(self):
        with self._lock:
            return len(self._items)

    @property
    def index(self):
        """ایندکس صفر-مبنا، یا None اگه هیچی پخش نمی‌شه."""
        with self._lock:
            return self._index if 0 <= self._index < len(self._items) else None

    @property
    def active(self):
        with self._lock:
            return self._active

    @property
    def mode(self):
        with self._lock:
            return self._mode

    @mode.setter
    def mode(self, value):
        with self._lock:
            self._mode = int(value)

    def current(self):
        with self._lock:
            if 0 <= self._index < len(self._items):
                return self._items[self._index]
            return None

    def items(self):
        """کپی از لیست (برای نمایش با q)."""
        with self._lock:
            return list(self._items)

    def remaining(self):
        with self._lock:
            return max(0, len(self._items) - self._index - 1)

    def meta(self):
        """لیست dict برای bot.track_meta."""
        with self._lock:
            return [track.as_meta() for track in self._items]

    def describe(self):
        with self._lock:
            total = len(self._items)
            position = self._index + 1 if 0 <= self._index < total else 0
        if self.expected_total > total:
            return f"{position}/{total} (از {self.expected_total})"
        return f"{position}/{total}"

    # ------------------------------------------------------------ نوشتن

    def replace(self, items, private=True, service=None, mode=None, expected_total=0):
        """
        صف رو کامل عوض می‌کنه و آیتم اول رو پخش می‌کنه.
        خروجی: (تعداد آیتم‌ها، Track پخش‌شده) یا (0, None) اگه چیزی نبود.
        """
        tracks = [Track.from_item(item, private=private, service=service)
                  for item in (items if isinstance(items, (list, tuple)) else [items])]
        tracks = [t for t in tracks if t.url or t.stub]
        if not tracks:
            return 0, None

        # زیرِ _nav_lock: وگرنه پیشرویِ خودکارِ پایانِ آهنگِ *صفِ قبلی*
        # (on_track_finished، ترد خودش) می‌تونست وسطِ یه سرچِ تازه اجرا بشه و
        # آهنگِ قبلی -- گاهی حتی بعد از آهنگِ جدید -- توی چت اعلام بشه.
        with self._nav_lock:
            with self._lock:
                if mode is not None:
                    self._mode = int(mode)
                # همیشه همه‌ی آیتم‌هایی که آورده شدن توی صف می‌رن -- تعداد رو
                # جستجو/پلی‌لیست تعیین می‌کنه، نه مُدِ «آهنگ تموم شد». (m، E5)
                self._items = tracks
                self._index = 0
                self.expected_total = max(int(expected_total or 0), len(tracks))
                self._resolving.clear()
                self._epoch += 1
                self._growing = False

            track = self._play_index(0)
            if track is None:
                return 0, None
            self._after_move()
            return len(tracks), track

    def append(self, items, private=True, service=None):
        """آیتم به انتهای صف اضافه می‌کنه بدون قطع پخش فعلی. تعداد اضافه‌شده برمی‌گردونه."""
        tracks = [Track.from_item(item, private=private, service=service)
                  for item in (items if isinstance(items, (list, tuple)) else [items])]
        tracks = [t for t in tracks if t.url or t.stub]
        if not tracks:
            return 0
        with self._lock:
            # رشد صف (سرچ/پلی‌لیست) صرف‌نظر از مُدِ «آهنگ تموم شد» ادامه
            # داره -- m فقط تعیین می‌کنه بعد از تموم‌شدن یه آهنگ چی بشه، نه
            # این‌که چیزی برای رفتن جلوتر (با n) وجود داشته باشه یا نه.
            self._items.extend(tracks)
            self.expected_total = max(self.expected_total, len(self._items))
        return len(tracks)

    def clear(self):
        with self._lock:
            self._items = []
            self._index = -1
            self._active = False
            self.expected_total = 0
            self._resolving.clear()
            self._epoch += 1
            self._growing = False

    def shuffle(self):
        """
        آیتم فعلی سر جاش می‌مونه و بقیه به‌هم می‌ریزن -- وگرنه shuffle
        وسط آهنگ، آهنگ در حال پخش رو عوض می‌کرد.
        """
        with self._lock:
            if len(self._items) < 3 or not (0 <= self._index < len(self._items)):
                return False
            head = self._items[: self._index + 1]
            tail = self._items[self._index + 1:]
            random.shuffle(tail)
            self._items = head + tail
            return True

    def remove_current(self):
        with self._lock:
            if not (0 <= self._index < len(self._items)):
                return False
            self._items.pop(self._index)
            if self._index >= len(self._items):
                self._index = len(self._items) - 1
            return True

    # ----------------------------------------------------------- حرکت

    def advance(self, by=1, force=False):
        """
        جلو رفتن. خروجی (ok, track). **بلاک نمی‌کنه** روی رشد صف: اگه
        آیتمی نباشه فوراً (False, None) برمی‌گردونه و رشد رو در پس‌زمینه
        راه می‌ندازه، پس کاربر می‌تونه یه لحظه بعد دوباره n بزنه.

        force=True (دستورِ دستیِ n): صرف‌نظر از MODE_REPEAT_TRACK یه قدمِ
        واقعی جلو می‌ره -- چون کاربر صریحاً «بعدی» رو خواسته، نه تکرارِ
        خودکارِ همون آهنگ. on_track_finished (پایانِ طبیعی) force نمی‌ده،
        پس مُدِ تکرار همون‌جا هنوز رعایت می‌شه. رفتارِ MODE_REPEAT_PLAYLIST
        (برگشت به اول در انتهای صف) برای n هم منطقیه و دست‌نخورده می‌مونه.

        کلِ تابع زیرِ _nav_lock است (توضیح کاملِ چرایی‌ش کنارِ تعریفِ
        _nav_lock در __init__).
        """
        with self._nav_lock:
            with self._lock:
                if self._mode == MODE_REPEAT_TRACK and not force:
                    target = self._index
                else:
                    target = self._index + by
                    if target >= len(self._items):
                        if self._mode == MODE_REPEAT_PLAYLIST and self._items:
                            target = 0
                        else:
                            self._trigger_growth_locked()
                            return False, None
                if target < 0:
                    return False, None

            return self._play_and_settle(target)

    def retreat(self, by=1):
        with self._nav_lock:
            with self._lock:
                target = self._index - by
                if target < 0:
                    if self._mode == MODE_REPEAT_PLAYLIST and self._items:
                        target = len(self._items) - 1
                    else:
                        return False, None
            return self._play_and_settle(target)

    def jump(self, position):
        """position یک-مبناست (همون عددی که کاربر می‌فرسته)."""
        with self._nav_lock:
            with self._lock:
                target = int(position) - 1
                if not (0 <= target < len(self._items)):
                    return False, None
            return self._play_and_settle(target)

    def on_track_finished(self):
        """
        از حلقه‌ی اصلی صدا زده می‌شه وقتی mpv بیکار شده ولی ما متوقفش
        نکردیم -- یعنی آهنگ طبیعی تموم شده. خروجی (advanced, track).

        قفلِ جابه‌جایی این‌جا **بلاک نمی‌شه**: اگه همین الان یه دستورِ
        دستیِ n/b/جهش (توی ترد خودش) داره صف رو جابه‌جا می‌کنه، این تیکِ
        housekeeping فقط رد می‌شه (تیکِ بعدی، کمتر از یه ثانیه‌ی دیگه،
        دوباره امتحان می‌کنه) -- وگرنه ترد حلقه‌ی اصلی چند ثانیه (طولِ
        resolve) قفل می‌موند و پیام‌های بقیه‌ی کاربرها معطل می‌شد.
        """
        if not self._nav_lock.acquire(blocking=False):
            return False, None
        try:
            with self._lock:
                if not self._active:
                    return False, None
                if self._mode == MODE_SINGLE:
                    self._active = False
                    return False, None
            return self.advance()
        finally:
            self._nav_lock.release()

    # ------------------------------------------------- resolve و پخش

    def _play_index(self, target):
        """
        آیتم target رو resolve (اگه لازم بود) و پخش می‌کنه.
        **بیرون قفل** resolve می‌کنه، چون استخراج می‌تونه ثانیه‌ها طول بکشه.
        آیتم‌های خراب رد می‌شن و از صف حذف نمی‌شن (تا شماره‌ها ثابت بمونن).
        """
        attempts = 0
        while True:
            with self._lock:
                if not (0 <= target < len(self._items)):
                    return None
                track = self._items[target]

            if not track.resolved and not track.failed:
                self._resolve_track(track)

            if track.resolved:
                with self._lock:
                    self._index = target
                    self._active = True
                try:
                    self._play(track.url)
                except Exception:
                    logging_setup.log_exception(f"playing '{track.label()}'")
                    track.failed = True
                    track.url = None
                else:
                    return track

            # این آیتم قابل پخش نبود: برو سراغ بعدی. سقف تلاش می‌ذاریم تا
            # یه صف کاملاً خراب باعث حلقه‌ی طولانی نشه.
            attempts += 1
            if attempts >= 5:
                return None
            target += 1

    def _resolve_track(self, track):
        if self._resolve is None or track.stub is None:
            return
        key = id(track)
        with self._lock:
            if key in self._resolving:
                # یه prefetch داره همین رو resolve می‌کنه؛ منتظرش نمی‌مونیم
                # چون ممکنه کند باشه -- خودمون جدا انجام می‌دیم.
                pass
            self._resolving.add(key)
        try:
            resolved = self._resolve(track.stub)
        except Exception:
            logging_setup.log_debug(f"resolving '{track.label()}' failed")
            resolved = None
        finally:
            with self._lock:
                self._resolving.discard(key)

        if not resolved or not resolved.get("url"):
            track.failed = True
            return
        self._apply_resolved(track, resolved)

    def _play_and_settle(self, target):
        """پخش آیتمِ target و کارهای بعد از جابه‌جایی؛ (موفق؟، آهنگ)."""
        track = self._play_index(target)
        if track is None:
            return False, None
        self._after_move()
        return True, track

    def _apply_resolved(self, track, resolved):
        track.url = resolved["url"]
        track.title = resolved.get("title") or track.title
        track.public_url = resolved.get("public_url") or track.public_url
        track.info = track_meta.merge(track.info, resolved.get("info"))
        if not track.fallback_label:
            track.fallback_label = _netloc(track.url)

    def _after_move(self):
        """بعد از هر جابه‌جایی: prefetch جلو، و رشد اگه به آخر نزدیکیم."""
        self.prefetch_async()
        with self._lock:
            self._trigger_growth_locked()

    def prefetch_async(self):
        """
        آیتم‌های بعدی رو در پس‌زمینه resolve می‌کنه. همین تنها دلیلیه که
        `n` بدون تأخیر شروع می‌شه.
        """
        if self._resolve is None or self._submit is None:
            return
        with self._lock:
            targets = []
            for offset in range(1, self.prefetch_count + 1):
                position = self._index + offset
                if not (0 <= position < len(self._items)):
                    break
                track = self._items[position]
                if track.resolved or track.failed or id(track) in self._resolving:
                    continue
                self._resolving.add(id(track))
                targets.append(track)

        for track in targets:
            try:
                self._submit(self._prefetch_one, track)
            except Exception:
                with self._lock:
                    self._resolving.discard(id(track))

    def _prefetch_one(self, track):
        try:
            resolved = self._resolve(track.stub) if track.stub is not None else None
            if resolved and resolved.get("url"):
                self._apply_resolved(track, resolved)
            else:
                track.failed = True
        except Exception:
            logging_setup.log_debug("prefetch failed")
            track.failed = True
        finally:
            with self._lock:
                self._resolving.discard(id(track))

    # ------------------------------------------------------------- رشد

    def _trigger_growth_locked(self):
        """باید داخل قفل صدا زده بشه. خودِ رشد در پس‌زمینه انجام می‌شه."""
        if self._grow is None or self._submit is None or self._growing:
            return
        remaining = len(self._items) - self._index - 1
        if remaining > GROWTH_THRESHOLD:
            return
        self._growing = True
        try:
            self._submit(self._grow_now, self._epoch)
        except Exception:
            self._growing = False

    def _grow_now(self, epoch=None):
        try:
            needed = GROWTH_THRESHOLD * 2
            more = self._grow(needed) or []
            # اگه وسطِ گرفتن، صف عوض شده (سرچ جدید)، نتیجه مالِ صفِ قبلیه.
            with self._lock:
                stale = epoch is not None and epoch != self._epoch
            if more and not stale:
                self.append(more)
                self.prefetch_async()
        except Exception:
            logging_setup.log_debug("queue growth failed")
        finally:
            with self._lock:
                if epoch is None or epoch == self._epoch:
                    self._growing = False

    def is_growing(self):
        with self._lock:
            return self._growing

    @property
    def epoch(self):
        """با هر replace/clear یکی زیاد می‌شه -- «این هنوز همون صفه؟»."""
        with self._lock:
            return self._epoch

    @property
    def is_navigating(self):
        """
        آیا همین الان یه جابه‌جایی (دستی یا خودکار) در جریانه؟ یعنی
        _nav_lock دستِ یه ترد دیگه‌ست. bot.py ازش استفاده می‌کنه تا وقتی
        مسئولِ واقعیِ جابه‌جایی (که خودش broadcast_now_playing رو صدا
        می‌زنه) هنوز کارش تموم نشده، watcherِ عنوانِ housekeeping یه پیامِ
        کوتاهِ زودهنگام برای همون آهنگ نفرسته -- وگرنه هم پیامِ کوتاه هم
        پیامِ کاملِ بعدی، هر دو برای یه آهنگ، پشتِ‌سرهم می‌رفت.
        """
        acquired = self._nav_lock.acquire(blocking=False)
        if acquired:
            self._nav_lock.release()
            return False
        return True

    def can_grow(self):
        """آیا اصلاً منبعی برای گرفتن آیتم بیشتر هست؟"""
        return self._grow is not None

    def mark_stopped(self):
        """
        بعد از توقف عمدی (stop_player) صدا زده می‌شه، تا «mpv بیکاره»
        اشتباهاً به‌عنوان «آهنگ تموم شد» تفسیر نشه.
        """
        with self._lock:
            self._active = False
