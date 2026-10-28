# سرویس‌ها

هر فایل `.py` داخل `core/services/` یه سرویسه. فایل‌هایی که با `_` شروع
می‌شن لود نمی‌شن (مثل `_ytdlp_service.py` که خودش سرویس نیست، پایه‌ست).

## وضعیت فعلی

| سرویس | جستجو | از کجا | تأییدشده |
|---|---|---|---|
| youtube | ✅ ytsearch | yt-dlp | ✅ |
| youtubemusic | ✅ صفحه‌ی جستجو (`youtube:music:search_url` توی yt-dlp) | yt-dlp | ⚠️ شبکه |
| soundcloud | ✅ scsearch | yt-dlp | ⚠️ شبکه |
| aparat | ✅ API رسمی (جستجو + کانال + پلی‌لیست) | API خود آپارات | ✅ زنده |
| telewebion | ✅ GraphQL | API خود تلوبیون | ⚠️ شبکه |
| radiojavan | ✅ API وب‌اپ (`play.radiojavan.com/api/p/search`) -- mp3 مستقیم توی نتیجه؛ لینک صفحه/ویدیو/`rj.app` | API خود رادیو جوان (اکسترکتور yt-dlp خرابه و سایت پشت Cloudflare) | ✅ زنده |
| upmusics / nex1music / rozmusic | ✅ صفحه‌ی جستجوی HTML؛ mp3 (۳۲۰/۱۲۸) از صفحه‌ی پست؛ کد مشترک `_wp_music.py` | خودِ سایت | ✅ زنده |
| tamasha | ✅ صفحه‌ی جستجوی HTML (`/search?query=`)؛ نتیجه‌های پاک‌شده کنار می‌رن | yt-dlp (html5/HLS) | ✅ زنده |
| mixcloud | ✅ API رسمی (`api.mixcloud.com/search`) | API خود Mixcloud | ⚠️ شبکه |
| archive | ✅ API رسمی (`advancedsearch.php`) | API خود archive.org | ⚠️ شبکه |
| dailymotion | ✅ `dailymotion:search` (اکسترکتور جستجوی خودِ yt-dlp) | yt-dlp | ⚠️ شبکه |
| audiomack | ⚠️ صفحه‌ی جستجو -- yt-dlp اکسترکتور جستجو نداره (فقط آهنگ/آلبوم تکی)؛ صفحه هم کاملاً کلاینت‌ساید(React) است | yt-dlp (عمومی) | ⚠️ شبکه، احتمالاً هنوز خراب |
| jamendo | ⚠️ صفحه‌ی جستجو -- yt-dlp اکسترکتور جستجو نداره (فقط track/album)؛ API رسمی به client_id نیاز داره | yt-dlp (عمومی) | ⚠️ شبکه، احتمالاً هنوز خراب |
| vimeo | ⚠️ صفحه‌ی جستجو -- yt-dlp اکسترکتور جستجو نداره؛ صفحه کلاینت‌ساید است | yt-dlp (عمومی) | ⚠️ شبکه، احتمالاً هنوز خراب |
| instagram / tiktok | ❌ فقط لینک | yt-dlp | ✅ |
| spotify | ❌ فقط لینک | متادیتا از embed اسپاتیفای، صدا از یوتیوب | ⚠️ شبکه |

«⚠️ شبکه» یعنی کد نوشته و لود می‌شه ولی از این شبکه (یه sandbox که هم
اتصال مستقیم هم مسیر پروکسیِ سیستم `http://10.10.14.1:8080` روی هر دو
از این جلسه غیرقابل‌دسترس بودن -- فقط google.com، aparat.com و
open.spotify.com مستقیم جواب دادن) به اون سرویس دسترسی نبود تا پخشش زنده
تست بشه؛ به‌جاش با mock کردن شکلِ مستندِ JSON هر API تست شده. archive و
mixcloud همین الان (این پچ) از صفحه‌ی جستجوی شکسته به API رسمی و
بدون‌کلیدشون منتقل شدن -- منطق درسته و آفلاین تست شده، ولی هیچ‌وقت زنده
روی خودِ سایت اجرا نشده. audiomack/jamendo/vimeo دست‌نخورده موندن: بدون
دسترسی زنده نمی‌شد مطمئن شد کدوم endpoint بدون کلید واقعاً کار می‌کنه، و
حدس‌زدنِ یه آدرس نادرست بدتر از دست‌نخورده گذاشتنشه.

## قابلیت‌ها (نه فایل توی core/services/)

مستند (`md`) و IPTV (`tv`/`tvs`) روی این جدول نیستن چون سرویسِ پخشِ
عادی (`core/services/*.py`) نیستن -- «قابلیت»ن (`CAPABILITY_SERVICES`
توی `licensing/catalog.py`): منطقشون یه ماژول مستقل توی `core/` است
(`core/documentary.py`، `core/iptv.py`) و منبعشون کانفیگه، نه یه
اکسترکتور yt-dlp. IPTV مستنداتِ خودش رو داره: [`IPTV.md`](IPTV.md).

## ساختن یه سرویس جدید

اگه yt-dlp اکسترکتور داره، کل سرویس چند خطه:

```python
from core.services._ytdlp_service import YtdlpService

class Bandcamp(YtdlpService):
    SERVICE_NAME = "bandcamp"
    URL_MARKERS = ("bandcamp.com",)
    SEARCH_URL_TEMPLATE = "https://bandcamp.com/search?q={query}&item_type=t"
```

جستجو، resolve، صف، و رشد تدریجی پلی‌لیست از پایه میان.

### وقتی yt-dlp جستجو نداره

`_search_stubs` رو override کن و از API خود سرویس stub بساز — دقیقاً
کاری که `aparat.py` و `telewebion.py` می‌کنن. بقیه‌ی زنجیره فرقی
نمی‌بینه.

### وقتی خود اکسترکتور خرابه

`_resolve_entry` رو هم override کن. `aparat.py` نمونه‌شه: اکسترکتور
آپاراتِ yt-dlp با ساختار فعلی صفحه هماهنگ نیست و با
«Unable to extract og:title» رد می‌شه، پس resolve از API رسمی انجام
می‌شه و yt-dlp فقط fallback می‌مونه.

## سرویس‌های قدیمی هم روی پایه‌ن

youtube، soundcloud، instagram، tiktok و spotify حالا همه از
`YtdlpService` ارث می‌برن. هر کدوم فقط رفتارِ واقعاً مخصوص خودش رو نگه
داشته:

| سرویس | چیزی که مال خودشه |
|---|---|
| youtube | مسیر سریع YouTube Data API و سهمیه‌ش، کش توضیحات (`di`)، تب‌های کانال، پلی‌لیست از stubهای کش‌شده |
| soundcloud | پیشوند `scsearch` و `SEARCH_FIRST_COUNT = 1` (نتایج صفحه‌صفحه میان) |
| instagram | پیام‌های راهنما به‌جای None، عنوان از توضیحات پست، فید پروفایل و هشتگ |
| tiktok | User-Agent مرورگر، لینک بدون http، «TikTok by …» برای ویدیوی بی‌عنوان |
| spotify | لیست ترک‌ها از صفحه‌ی embed اسپاتیفای، صدای هر ترک از یوتیوب با تطبیق مدت (`COOKIE_SERVICE = "youtube"`) |

دو چیز که موقع این انتقال به پایه اضافه شد و به همه‌ی سرویس‌ها می‌رسه:

  * `FIRST_PLAYABLE_TRIES`: اگه آیتم اولِ یه پلی‌لیست حذف یا خصوصی شده
    باشه، چندتای بعدی امتحان می‌شن و رشد صف از بعدِ همونی که پخش شد ادامه
    پیدا می‌کنه -- قبلاً کل پلی‌لیست «چیزی پیدا نشد» می‌داد.
  * `COOKIE_SERVICE`: سرویسی که صداش رو از جای دیگه می‌گیره، کوکیِ همون‌جا
    رو استفاده می‌کنه.

دستورهای اختصاصیِ لینک (`sc`، `tk`، `spt`) از
`command_helpers.run_search_and_play_command` می‌گذرن تا رشد صف راه بیفته؛
بدون اون از یه set یا پروفایل فقط آیتم اول پخش می‌شد.

## لینکِ تک‌خط (پیستِ خام یا `u <لینک>`) -- E8/E13

هر لینکی که کاربر بدون هیچ دستوری پیست کنه (`bot.py::on_user_msg`، شاخه‌ی
`cmd_name is None`) یا صریحاً با `u <لینک>` بفرسته (`commands/u.py`)، از
یک نقطه‌ی مشترک می‌گذره: `core/command_helpers.py::run_link_command`.
قبلاً این دو مسیر تقریباً یکی ولی کدشون جدا بود و به‌مرور از هم دور
می‌شدن؛ حالا `commands/u.py` فقط یه پوسته‌ی نازکه و هر اصلاحی خودکار به
هر دو راه می‌رسه.

ترتیبِ resolve (هوشمندی‌ای که E8 خواسته -- «فایل واقعی پشتِ لینک» رو با
بهترین کیفیت پیدا کن، نه فقط اولین چیزی که جواب بده):

  1. هر سرویسِ لودشده‌ای که `owns_url(url)` بگه «این لینک مالِ منه»
     (`core/services/_ytdlp_service.py::owns_url`، از روی `URL_MARKERS`).
     اگه چند سرویس ادعا کنن (مثلاً `music.youtube.com` هم به مارکر
     `youtube.com` می‌خوره هم `music.youtube.com`)، اونی که طولانی‌ترین
     مارکر رو داره (خاص‌ترین) برنده می‌شه -- `_owning_service_for_url`.
     این مسیر همون چیزیه که `p <همون لینک>` می‌داد: عنوانِ واقعی،
     `channel_url` (برای `cv`/`cs`/`c`)، و رشدِ خودکارِ پلی‌لیست با `n`.
  2. اگه هیچ سرویسی ادعا نکرد، `core/link_resolver.py::resolve`:
     بازنویسیِ لینکِ اشتراک (Dropbox `dl=1`، Google Drive) -> مدیا/پلی‌لیستِ
     مستقیم (m3u/pls/xspf/asx باز می‌شن) -> probe با دنبال‌کردنِ ریدایرکت
     (لینک‌کوتاه‌کن، بی‌پسوند، ICY) -> yt-dlp عمومی -> اسکن HTML سبک
     (تگ‌ها، og/twitter:player:stream، JSON-LD، کلیدهای JSON، meta-refresh/JS،
     iframe تا ۳ سطح) -> yt-dlp با generic اجباری -> مرورگر headless.
     کلِ کار سقفِ زمانی (۷۵ ثانیه) و سقفِ ۸ صفحه داره. اگه رسانه Referer/UA
     لازم داشته باشه، آیتم کلیدِ `headers` می‌گیره و `bot.load_and_play` با
     همون مکانیزمِ IPTV (`iptv.apply_stream_headers`) روی mpv می‌ذاردشون.

نکته‌ی مهم: `core/services/youtube.py` تا قبل از این تغییر `URL_MARKERS`
نداشت (خالی از پایه به ارث می‌رسید)، یعنی `owns_url` همیشه `False` بود و
یه لینکِ خامِ یوتیوب که پیست می‌شد **هیچ‌وقت** از سرویسِ یوتیوب رد نمی‌شد،
فقط از لوله‌ی عمومی -- درحالی‌که `p <همون لینک>` نتیجه‌ی خیلی بهتری
می‌داد. حالا `URL_MARKERS = ("youtube.com", "youtu.be")` داره.

private همیشه `True`ه، صرف‌نظر از این‌که کدوم مسیر (سرویس یا عمومی)
جواب داده -- لینکی که کاربر خودش فرستاده هیچ‌وقت نباید با `k` به کسی
داده بشه یا وارد تاریخچه‌ی عمومی بشه.

## ثبت توی لایسنس — فراموش نکن

اضافه‌کردن فایل سرویس **کافی نیست**. `core/license_gate.py` هر سرویس و
دستوری که توی `licensing/catalog.py` نباشه رو فیلتر می‌کنه، پس روی یه
ربات لایسنس‌دار اصلاً دیده نمی‌شه.

بعد از اضافه‌کردن سرویس، توی `FEATURES` ثبتش کن:

```python
"svc_bandcamp": {
    "title_fa": "...", "title_en": "...",
    "price_usd": 1.5,
    "services": ["bandcamp"],
    "commands": ["bc"],
    "note_fa": "...", "note_en": "...",
},
```

و لایسنس‌های موجود رو دوباره صادر کن تا امکان جدید رو بگیرن
(`python manage.py self-license <id> <bot_dir>` برای مال خودت).

## اجراکننده‌ی جاوااسکریپت (js_runtimes)

yt-dlp ۲۰۲۶ بدون یه runtime جاوااسکریپت (deno یا node) برای استخراج
یوتیوب هشدار «No supported JavaScript runtime» می‌ده. `core/platform_paths.py::js_runtime()`
مسیر deno/node رو پیدا می‌کنه؛ `core/ytdlp_opts.py::with_js_runtime()`
همون نتیجه رو به گزینه‌های واقعی yt-dlp وصل می‌کنه -- `YtdlpService._opts()`
(پس همه‌ی سرویس‌های روی پایه) و `link_resolver.try_ytdlp` هر دو ازش
استفاده می‌کنن. سرویس/مسیر تازه‌ای که مستقیم `YoutubeDL(...)` می‌سازه
باید همین تابع رو صدا بزنه، نه خودش یه راه جدید.

## پروکسی

هر دو مسیرِ شبکه fallback دارن:

  * `proxy_retry.extract_with_fallback` — برای درخواست‌های سطح‌بالا
    (جستجو). اگه پروکسی fail کنه توی چت خبر می‌ده و بدون پروکسی دوباره
    امتحان می‌کنه.
  * `proxy_retry.extract_pooled` — برای resolve تک‌آیتم‌ها. همون
    fallback، ولی **بی‌صدا** (وگرنه یه پلی‌لیست ۵۰تایی ۵۰ تا پیام
    می‌داد) و روی نمونه‌های pool.

اگه مسیر resolve این fallback رو نداشته باشه، نتیجه‌ش یه خرابیِ
گیج‌کننده‌ست: سرویس **جستجو می‌شه ولی پخش نمی‌شه**.
