# آماده‌سازی سورس برای ارسال به سرور

قبل از فرستادن پروژه به سرور، `tools/reset_project.py` همه‌ی وضعیتِ اجرا
(دیتای ربات‌ها، دیتابیس لایسنس، رسیدها، لاگ‌ها، کش، خروجی بیلد و
فایل‌های موقتی مثل `token.txt`) رو پاک می‌کنه. فقط کتابخانه‌ی استاندارد
پایتون می‌خواد و روی ویندوز و لینوکس یکسانه.

```bash
python tools/reset_project.py                  # گزارش (dry-run): چی پاک می‌شه، با حجم
python tools/reset_project.py --apply          # بکاپ + تأیید تایپی (RESET) + پاک‌کردن
python tools/reset_project.py --apply --yes    # همون، بدون سؤال (برای اسکریپت)
python tools/reset_project.py --check-clean    # آماده‌ی ارسال هست؟ کد خروج ۰ = بله، ۱ = نه
```

**قبل از `--apply`، سرور لایسنس و ربات‌ها رو خاموش کن** (دیتابیس در حال
استفاده نباشه).

## دسته‌ها

| دسته | چی پاک می‌شه |
|---|---|
| `bots` | `data/<host>_<port>/…` (پوشه‌ی ربات‌ها)، `_machine_id`، حساب‌های سراسری، لاین‌های صدا در `_audio_lines.json` |
| `licensing-db` | ردیف‌های دیتابیس لایسنس: لایسنس، نمونه، سفارش، کاربر، تیکت، رویداد، تخفیف، تنظیمات |
| `receipts` | عکس رسیدهای `data/licensing/receipts/` |
| `config` | `data/licensing/config.json` (توکن‌ها) و `catalog.json` (قیمت‌های سفارشی) |
| `logs` | همه‌ی فایل‌های `errors/` |
| `caches` | `__pycache__`، `*.pyc`، `.pytest_cache` |
| `build` | `dist/`، `build/_work/`، `*.spec`، `.wrangler` |
| `leftovers` | `token.txt`، `create_and_push.bat`، `e2esrv/`، `.env`، `*.tmp/*.bak/*.log` در ریشه |
| `bin` | `bin/` و `tesseract/` — **فقط** با `--include-bin` |

گزینه‌ها: `--only a,b` (فقط این دسته‌ها)، `--keep-config`،
`--keep-licensing-db`، `--include-bin`، `--root DIR`.

## چی هیچ‌وقت لمس نمی‌شه

- `goldenFriends/` (رباتِ فروخته‌شده) و لایسنس `TT-EQ4F-2V6D-AWFF`.
- لایسنس‌های محافظت‌شده (`protected_licences` در کانفیگ + منطق
  `licensing/gc.py`): ردیف لایسنس، نمونه‌ها، سفارش‌ها، کاربر صاحب، پوشه‌ی
  ربات و لاین صدای اون‌ها سالم می‌مونه. لیست `protected_licences` موقع
  پاک‌شدن `config.json` توی یه فایل حداقلی نگه داشته می‌شه.
- فایل‌های tracked گیت، `.git/`، `.claude/`، `_reset_backups/`.
- `data/licensing/keys/` (کلید امضا). اگه لایسنس‌های صادرشده باید معتبر
  بمونن همین کلید رو با پروژه ببر؛ اگه نه، خودت دستی پاکش کن.

## بکاپ

قبل از هر پاک‌کردن، یه zip در `_reset_backups/reset-<زمان>.zip` ساخته و
مسیرش چاپ می‌شه (پوشه‌ی بکاپ در `.gitignore` هست و خودش ریست نمی‌شه؛
**شامل توکن‌ها و کلیدهاست، همراه پروژه نفرست**). کش، خروجی بیلد و `bin`
چون دوباره ساخته/دانلود می‌شن توی بکاپ نیستن.

## ریشه‌ی پروژه

اسکریپت فقط اگه `manage.py`، `licensing/gc.py` و `core/paths.py` کنار هم
باشن اجرا می‌شه؛ وگرنه با کد خروج ۲ رد می‌کنه.
