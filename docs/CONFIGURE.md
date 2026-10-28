# راه‌اندازی یک‌جای پروژه (configure.py)

`configure.py` ویزاردیه که بعد از `git clone` کل پروژه رو آماده‌ی اجرا
می‌کنه: نصبِ چیزهایی که کم‌ان، توکن و پروکسیِ ربات فروش، ادمین‌ها و
کارت، و اختیاری Cloudflare، کریپتو، اولین ربات و لایسنس مالک. آخرش هم
همون `license_server.py --check` رو اجرا می‌کنه.

```bash
python configure.py                        # تعاملی، قدم‌به‌قدم
python configure.py --non-interactive --sales-token ... --admin-ids ... --card-number ...
python configure.py --help                 # همه‌ی گزینه‌ها
```

پرامپت‌ها دوزبانه‌ان (اول انگلیسی، بعد فارسی)، بدون رنگ و بدون
ASCII-art، تا با صفحه‌خوان راحت خونده بشن. هر قدم جدا و قابل‌رد‌کردنه.
پیش‌نیاز: پایتون ۳.۱۰+ (خودِ نصبِ پایتون کارِ این اسکریپت نیست).

> این فایل عمداً نازکه. هر کاری که قبلاً یه جای دیگه انجام می‌شد همون‌جا
> مونده و اینجا فقط صدا زده می‌شه: نصب توسط [`install.py`](INSTALL.md)،
> ساختن فایل‌ها توسط `license_server.init_files` (همون `--init`)،
> نوشتن کانفیگ توسط `licensing.config.save_values`، لایسنس مالک توسط
> `manage.py self-license`، چک آخر توسط `license_server.py --check`.

---

## قدم‌ها

| # | قدم | چی می‌کنه |
|---|---|---|
| ۱ | پایتون و کامپوننت‌ها | نسخه‌ی پایتون رو چک می‌کنه؛ برای هر چیزِ نصب‌نشده (پکیج‌های پایتون، TeamTalk SDK، ffmpeg، libmpv، pulseaudio-utils، جاوااسکریپت‌رانتایم، و اختیاری tesseract) **قبل از نصب می‌پرسه** و بعد `install.py` رو اجرا می‌کنه. |
| ۲ | فایل‌های پلتفرم | `data/licensing/config.json`، `catalog.json`، کلید امضا و دیتابیس -- همون `license_server.py --init`. |
| ۳ | تلگرام | **اول پروکسی، بعد توکن.** توکن با `getMe` تست می‌شه، از مسیر همون پروکسیِ صریح. |
| ۴ | ادمین و پرداخت | آیدی عددیِ ادمین‌ها، شماره کارت، نام صاحب کارت، بانک، یوزرنیم پشتیبانی. |
| ۵ | Cloudflare (اختیاری) | شناسه‌ی حساب، KV namespace و توکن API؛ قبل از ذخیره با یه درخواست واقعی تست می‌شه. |
| ۶ | کریپتو (اختیاری) | سؤالِ بله/خیر (پیش‌فرض خیر). اگه بله: شبکه (`trc20`/`bep20`)، آدرس دریافت، کلیدهای API مربوط به همون شبکه، مهلت و تأیید، و در آخر فعال‌کردن. آدرس و شبکه با خودِ `licensing/crypto_pay.py` اعتبارسنجی می‌شن (چک‌سام ترون/فرمت BSC) و کلیدها تودرتو زیر `"crypto": {...}` نوشته می‌شن. اگه نسخه‌ی کانفیگ کلید `crypto.*` نداشته باشه، بی‌صدا رد می‌شه. جزئیات: [`CRYPTO_PAYMENTS.md`](CRYPTO_PAYMENTS.md). |
| ۷ | تنظیمات پیشرفته (اختیاری) | بقیه‌ی کلیدهای کانفیگ (تایم‌اوت‌ها، مهلت تمدید، ...). |
| ۸ | ذخیره | تغییرها (رازها ماسک‌شده) نشون داده می‌شن و با تأیید نوشته می‌شن. |
| ۹ | اولین ربات و لایسنس مالک (اختیاری) | پوشه‌ی سرور و ربات تیم‌تاک، و `self-license` برای اولین ادمین. |
| ۱۰ | خلاصه و چک | مقدارهای نهایی (رازها ماسک‌شده) و `license_server.py --check`. |

### پروکسیِ تلگرام

`api.telegram.org` روی بعضی شبکه‌ها بسته‌ست، برای همین پروکسی **اول**
پرسیده می‌شه و `getMe` فقط از همون مسیر می‌ره: پروکسیِ سیستم و
`HTTPS_PROXY` هیچ‌وقت خونده نمی‌شن (`trust_env=False`). «با پروکسیِ
سیستم کار کرد» روی سرور یعنی هیچی. فقط `http://` و `socks5://` قبوله
(برای socks باید `pip install "python-telegram-bot[socks]"` باشه)؛
لینک vless/vmess پشتیبانی نمی‌شه چون خودِ ربات فروش نمی‌تونه ازش
استفاده کنه.

اگه `getMe` شکست بخوره، یکی از این‌ها رو انتخاب می‌کنی: دوباره تلاش،
توکن دیگه، عوض‌کردن پروکسی، نگه‌داشتنِ همین، یا کنار گذاشتنِ تغییر.

### اجباری‌ها

لیست کلیدهای اجباری از `licensing.config.missing_required_keys()` می‌آد
(همون شرط‌های `missing_required()`): توکن ربات فروش، آیدی ادمین و
شماره کارت (که اگه پرداخت با تتر فعال و آدرسش معتبر باشه دیگه اجباری
نیست). اینجا خالی‌گذاشتنشون ممکن نیست مگه این‌که قبلاً مقدار داشته باشن.

---

## اجرای دوباره (idempotent)

- هر فیلد مقدارِ فعلیِ *فایل* رو به‌عنوان پیش‌فرض نشون می‌ده؛ رازها
  ماسک‌شده (`1234********ab`). Enter یعنی «همین بمونه»، و `-` یعنی «پاک کن»
  (برای غیراجباری‌ها).
- فقط چیزی که عوض کنی نوشته می‌شه؛ بقیه‌ی کلیدهای فایل (حتی کلیدهایی که
  این ویزارد نمی‌شناسه، مثل `protected_licences`) دست‌نخورده می‌مونن.
- اگه هیچی عوض نشده باشه، فایل اصلاً باز نوشته نمی‌شه.
- اگه متغیر محیطی (مثل `LICENSING_CARD_HOLDER`) جای مقدار فایل رو گرفته
  باشه، خلاصه بهت می‌گه. مقدارِ env هیچ‌وقت ناخواسته توی فایل نمی‌ریزه.
- فایل کانفیگِ خراب (JSON نامعتبر) هیچ‌وقت بازنویسی نمی‌شه؛ ویزارد
  می‌ایسته و می‌گه کجاش خرابه.
- ربات یا لایسنسِ موجود دست نمی‌خوره: `identity.json` و `shared_config.json`
  بازنویسی نمی‌شن و لایسنس مالک فقط یک‌بار صادر می‌شه.

---

## حالت بدون سؤال

`--non-interactive` هیچ‌وقت چیزی نمی‌پرسه. مقدارها از گزینه‌ها یا متغیر
محیطی می‌آن؛ چیزی که داده نشه همون‌طور می‌مونه.

| کلید | گزینه | متغیر محیطی |
|---|---|---|
| `sales_bot_token` | `--sales-token` | `LICENSING_BOT_TOKEN` |
| `proxy_url` | `--proxy-url` | `LICENSING_PROXY_URL` |
| `admin_ids` | `--admin-ids` | `LICENSING_ADMIN_IDS` |
| `card_number` | `--card-number` | `LICENSING_CARD_NUMBER` |
| `card_holder` | `--card-holder` | `LICENSING_CARD_HOLDER` |
| `card_bank` | `--card-bank` | `LICENSING_CARD_BANK` |
| `support_username` | `--support-username` | `LICENSING_SUPPORT_USERNAME` |
| `cloudflare_account_id` | `--cf-account-id` | `CF_ACCOUNT_ID` |
| `cloudflare_kv_namespace` | `--cf-kv-namespace` | `CF_KV_NAMESPACE` |
| `cloudflare_api_token` | `--cf-api-token` | `CF_API_TOKEN` |
| `crypto.address`، `crypto.trongrid_api_key`، `crypto.explorer_api_key` | `--set crypto.address=...` | `LICENSING_CRYPTO_ADDRESS`، `LICENSING_TRONGRID_API_KEY`، `LICENSING_EXPLORER_API_KEY` |
| هر کلیدِ دیگه | `--set کلید=مقدار` | `CONFIGURE_<کلید>` (نقطه می‌شه `_`، مثلاً `CONFIGURE_CRYPTO_API_SECRET`) |

مقدار رو هم‌نوعِ پیش‌فرضِ کلید می‌خونه: `--set grace_days=5`،
`--set reminder_days=7,3,1`، `--set hosting_enabled=false`.
`--set` با کلیدِ ناشناس خطای استفاده (کد ۲) می‌ده، به‌جز کلیدهای
`crypto.*` که اگه این نسخه نشناسه‌شون فقط نادیده گرفته می‌شن.

**رازها رو با متغیر محیطی بده، نه گزینه:** گزینه‌های خط فرمان توی لیست
پروسه‌ها و تاریخچه‌ی شل می‌مونن.

```bash
export LICENSING_BOT_TOKEN=123456:AA...
export LICENSING_ADMIN_IDS=123456789
python configure.py --non-interactive --proxy-url socks5://127.0.0.1:1080 \
    --card-number "6037 9975 1234 5678" --card-holder "Ali" --install-components default
```

| گزینه | کاربرد |
|---|---|
| `--install-components لیست` | کامپوننت‌هایی که نصب بشن: `python,teamtalk,ffmpeg,libmpv,pulseaudio_utils,js_runtime,tesseract`، یا `default` (همه‌ی ضروری‌ها) یا `all`. بدونش چیزی نصب نمی‌شه و فقط گزارش می‌ده. |
| `--skip-install` | اصلاً کامپوننت‌ها رو چک نکن. |
| `--skip-network` | توکن/Cloudflare رو تست نکن و همون‌طور ذخیره کن. |
| `--skip-check` | `license_server.py --check` رو آخرش اجرا نکن. |
| `--create-bot` + `--bot-host` ... | اولین ربات (`--bot-port`, `--bot-name`, `--bot-nickname`, `--bot-username`, `--bot-password`, `--bot-channel-id`, `--bot-channel-password`؛ env: `CONFIGURE_BOT_<نام>`). |
| `--self-license` | لایسنس مالک برای اولین ادمین. |

توکنی که `getMe` ردش کنه **ذخیره نمی‌شه** و کد خروج ۱ می‌شه (بقیه‌ی
مقدارها نوشته می‌شن). کدهای خروج: `0` همه‌چیز آماده، `1` مشکلی مونده
(یا `--check` مشکل گزارش کرد)، `2` گزینه‌ی اشتباه.

---

## امنیت

- رازها (توکن ربات فروش، توکن Cloudflare، و هر کلیدِ `crypto.*` که اسمش
  token/secret/password/seed/private/api_key داشته باشه) هیچ‌جا کامل چاپ
  نمی‌شن: نه توی پرامپت، نه توی تغییرها، نه توی خلاصه، نه توی پیام خطا.
  ورودیِ رازها موقع تایپ نمایش داده نمی‌شه.
- فایل کانفیگ اتمیک نوشته می‌شه و روی سیستم‌های POSIX `chmod 600` می‌گیره.
- آدرس پروکسی با `user:pass@` هم ماسک می‌شه.

## ربات اول

ویزارد فقط ساختار رو می‌سازه (`data/<host>_<port>/shared_config.json` و
`<ربات>/identity.json`، همون شکل ویزاردِ `bot.py`). دستگاه‌های صدا روی
پیش‌فرض می‌مونن؛ برای انتخاب دستگاه یا ساخت لاین اختصاصی
`python manage.py devices` و `line-add` (یا همون `bot.py`) رو ببین.
لایسنس مالک اگه قبلاً صادر شده باشه دوباره صادر نمی‌شه؛ فقط اگه
`license.json` کنار ربات نباشه، پیشنهاد نوشتنش داده می‌شه.

## Cloudflare

ساخت KV namespace و Worker کارِ `python manage.py deploy-worker` است (بعد از
`wrangler login`)؛ این ویزارد فقط شناسه‌ها و توکنِ به‌دست‌اومده رو توی
کانفیگ می‌ذاره و تستشون می‌کنه. توکن API رو با دسترسیِ
«Workers KV Storage: Edit» بساز -- جزئیات: [`RENTAL.md`](RENTAL.md).

## عیب‌یابی

| نشانه | راه‌حل |
|---|---|
| `getMe failed: ConnectError` | پروکسی رو درست بنویس (گزینه‌ی `p` توی منو)؛ روی سرور، پروکسیِ سیستم به حساب نمی‌آد. |
| `socks proxies need an extra package` | `pip install "python-telegram-bot[socks]"` |
| `is not valid JSON` | `data/licensing/config.json` رو درست کن (ویرگول/کوتیشن کم) یا پاکش کن و دوباره بزن. |
| `--check` می‌گه ffmpeg/libmpv نیست | `python install.py --components ffmpeg,libmpv` (یا همین ویزارد رو دوباره بزن و به سؤال نصب بله بگو). |
