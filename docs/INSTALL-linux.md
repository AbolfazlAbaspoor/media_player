# نصب روی لینوکس

ربات و پلتفرم لایسنس روی لینوکس و ویندوز با **یک کد یکسان** اجرا می‌شن.
تفاوت فقط در باینری‌های نیتیو و در ساختن «لاین صدا» است — که روی لینوکس
اتفاقاً ساده‌تر و کامل‌تره.

تست‌شده روی Ubuntu 22.04/24.04 و Debian 12. روی توزیع‌های دیگه فقط اسم
پکیج‌ها عوض می‌شه.

> **سریع‌ترین راه:** `bash deploy/install-linux.sh` (یا مستقیم
> `python3 install.py`) بیشترِ قدم‌های ۱ تا ۳ پایین رو خودکار انجام
> می‌ده -- ببین [`docs/INSTALL.md`](INSTALL.md). بخش‌های پایین برای
> وقتیه که می‌خوای دستی/مرحله‌به‌مرحله پیش بری، یا بفهمی خودِ
> اسکریپت‌ها پشتِ‌پرده چیکار می‌کنن.
>
> **تنظیم پروژه:** بعد از نصب، `python3 configure.py` توکن، پروکسی،
> ادمین‌ها و کارت رو می‌پرسه و آخرش `--check` می‌زنه --
> [`docs/CONFIGURE.md`](CONFIGURE.md).

---

## ۱. پیش‌نیازهای سیستم

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv \
    ffmpeg libmpv2 pulseaudio pulseaudio-utils \
    tesseract-ocr tesseract-ocr-fas
```

اگه `libmpv2` پیدا نشد (توزیع‌های قدیمی‌تر):

```bash
sudo apt install -y libmpv1
```

| پکیج | برای چی |
|---|---|
| `ffmpeg` | تبدیل به mp3 در دستور `dl` |
| `libmpv2` | خود پخش‌کننده |
| `pulseaudio` + `pulseaudio-utils` | لاین صدا (`pactl`) |
| `tesseract-ocr` + `-fas` | بررسی خودکار رسید (اختیاری) |

> روی سرورهایی که PipeWire دارن، `pipewire-pulse` جای `pulseaudio` کافیه؛
> `pactl` با هر دو کار می‌کنه و کد تفاوتی نمی‌بینه.

---

> این پکیج‌ها رو `python3 install.py --components ffmpeg,libmpv,pulseaudio_utils`
> هم می‌تونه نصب کنه (اول apt/dnf، بعد در صورت لزوم دانلود مستقیم) --
> جزئیات: [`docs/INSTALL.md`](INSTALL.md).

## ۲. TeamTalk SDK

این تنها چیزیه که pip یا apt نصبش نمی‌کنه، چون لایسنس خودش رو داره.
(`python3 install.py --components teamtalk` هم فقط همین رو چک می‌کنه و
همین راهنما رو چاپ می‌کنه -- دانلود خودکار این یکی امکان‌پذیر نیست.)

۱. از [bearware.dk](http://bearware.dk/teamtalksdk) نسخه‌ی لینوکس SDK رو
   دانلود کن (همون معماری سرورت: معمولاً `x86_64`).
۲. از داخل آرشیو، `libTeamTalk5.so` رو در بیار و بذار توی پوشه‌ی
   `core/teamtalk/` همین پروژه:

```bash
cp /path/to/sdk/Library/TeamTalk_DLL/libTeamTalk5.so core/teamtalk/
```

۳. چک کن پیدا می‌شه:

```bash
python3 manage.py doctor
```

> **چرا توی `core/teamtalk/`؟** روی لینوکس نمی‌شه بعد از استارت پروسه
> `LD_LIBRARY_PATH` رو عوض کرد، پس کد کتابخونه رو با *مسیر مطلق* از همون
> پوشه لود می‌کنه. اگه SDK رو سیستمی نصب کردی (`/usr/local/lib` +
> `ldconfig`) هم کار می‌کنه.

---

## ۳. پایتون

```bash
python3 -m venv .venv
source .venv/bin/activate

# فقط ربات:
pip install -r requirements.txt

# یا ربات + پلتفرم لایسنس:
pip install -r requirements-license.txt
```

یا معادلِ خودکارش: `python3 install.py --venv .venv [--with-licensing]`.

---

## ۴. لاین صدا — معادل Virtual Audio Cable

روی ویندوز با Virtual Audio Cable چند «Line» می‌سازی و هر ربات یکی
می‌گیره. روی لینوکس همین کار **بومی** انجام می‌شه و بهتر:

```bash
python3 manage.py line-add bot1
```

خروجی:

```
لاین 'bot1' آماده شد:
  خروجی (mpv):      pulse/ttline_bot1
  ورودی (TeamTalk): ttline_bot1.monitor
```

پشت پرده یه `module-null-sink` پالس‌اودیو ساخته می‌شه: خود sink دستگاه
*خروجی* است (mpv توش می‌نویسه) و مانیتورش دستگاه *ورودی* (تیم‌تاک ازش
می‌خونه). دقیقاً همون مفهوم یه کابل صوتی مجازی.

مزیت مهم نسبت به ویندوز: اینجا لاین‌ها **برنامه‌ای ساخته و حذف** می‌شن.
پس وقتی یه لایسنس فعال می‌شه یه لاین تازه ساخته می‌شه، و وقتی غیرفعال
می‌شه واقعاً حذف می‌شه — بدون هیچ کار دستی و بدون محدودیت تعداد.

دستورهای دیگه:

```bash
python3 manage.py lines          # لیست لاین‌ها و اینکه زنده‌ان یا نه
python3 manage.py line-del bot1  # حذف
python3 manage.py line-ensure    # بازسازی لاین‌های از بین رفته (بعد از ریبوت)
python3 manage.py devices        # همه‌ی دستگاه‌های صدای سیستم
```

### در کانفیگ ربات

توی `identity.json` به **اسم لاین** اشاره می‌شه، نه به شماره‌ی دستگاه:

```json
"audio": {
    "input_device": "line:bot1",
    "output_device": "line:bot1"
}
```

> **چرا اسم و نه شماره؟** شماره‌ی دستگاه‌های صدا روی لینوکس با هر
> ری‌استارت پالس‌اودیو عوض می‌شه. با شماره، ربات بعد از ریبوت به یه دستگاه
> کاملاً دیگه وصل می‌شد (و بی‌صدا بالا می‌آمد). با `line:` هم اسم پایدار
> می‌مونه و هم اگه sink وجود نداشته باشه، خودکار بازسازی می‌شه.

---

## ۵. مهم‌ترین نکته‌ی لینوکس: سشن صدا

یه سرویس systemd در **سطح سیستم** هیچ سشن صوتی نداره، و هر `pactl` با
«Connection refused» رد می‌شه. دو راه داری:

### راه اول (پیشنهادی): سرویس کاربری + linger

```bash
sudo loginctl enable-linger $USER
systemctl --user enable --now pulseaudio.socket pulseaudio.service
```

`enable-linger` باعث می‌شه سشن کاربر بعد از logout هم زنده بمونه، پس
پالس‌اودیو و ربات‌ها بدون لاگین بالا می‌مونن. بعد سرویس‌ها رو با
`systemctl --user` اجرا کن (فایل‌های آماده توی `deploy/`).

### راه دوم: پالس‌اودیو در حالت سیستمی

کار می‌کنه ولی خود پالس‌اودیو رسماً توصیه‌اش نمی‌کنه؛ فقط اگه راه اول
ممکن نبود.

بررسی این‌که درست شده:

```bash
pactl info                  # باید اطلاعات سرور رو بده، نه خطا
python3 manage.py doctor
```

---

## ۶. راه‌اندازی ربات

### حالت دستی (یه ربات)

```bash
python3 bot.py            # بار اول ویزارد می‌پرسه
```

توی بخش دستگاه صدا گزینه‌ی ۱ («ساخت/گرفتن لاین اختصاصی») رو انتخاب کن.

### چند ربات با هم

```bash
python3 launcher.py
```

هر ربات پروسه‌ی جدا می‌گیره. لاین‌های صدای از بین رفته هم قبل از استارت
خودکار بازسازی می‌شن.

### با پلتفرم لایسنس (سرور فروش)

```bash
python3 license_server.py --init      # فایل‌های کانفیگ نمونه
# توکن ربات و آیدی تلگرامت رو توی data/licensing/config.json بنویس
python3 license_server.py --check     # بررسی آمادگی
python3 license_server.py             # اجرا
```

این یکی خودش سوپروایزر ربات‌ها رو هم بالا می‌آره؛ لازم نیست `launcher.py`
جدا اجرا بشه.

---

## ۷. systemd

فایل‌های آماده توی پوشه‌ی `deploy/`:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/ttbot-license.service ~/.config/systemd/user/
cp deploy/ttbot-launcher.service ~/.config/systemd/user/

# مسیر پروژه رو توی فایل‌ها درست کن:
sed -i "s|/opt/ttbot|$PWD|g" ~/.config/systemd/user/ttbot-*.service

systemctl --user daemon-reload
systemctl --user enable --now ttbot-license.service
systemctl --user status ttbot-license.service
journalctl --user -u ttbot-license -f
```

> `--user` (نه `sudo systemctl`) و `enable-linger` بخش ۵ لازم‌ان، وگرنه
> صدا کار نمی‌کنه.

---

## ۸. بیلد (فایل اجرایی مستقل)

```bash
pip install pyinstaller
python3 build/build.py            # روی لینوکس یه باینری لینوکسی می‌سازه
```

PyInstaller کراس‌کامپایل نمی‌کنه: بیلد ویندوزی باید روی ویندوز و بیلد
لینوکسی روی لینوکس ساخته بشه. اسکریپت `build/build.py` روی هر دو
سیستم‌عامل کار می‌کنه و خودش باینری‌های درست رو بسته‌بندی می‌کنه.

جزئیات بیشتر: [`docs/BUILD.md`](BUILD.md)

---

## ۹. عیب‌یابی

| نشانه | علت و راه‌حل |
|---|---|
| `Cannot find libmpv` | `sudo apt install libmpv2` (یا `libmpv1`). کد خودش `libmpv.so.2` رو هم امتحان می‌کنه، پس پکیج `-dev` لازم نیست. |
| `libTeamTalk5.so: cannot open shared object file` | فایل SDK توی `core/teamtalk/` نیست — بخش ۲. |
| `pactl ... Connection refused` | سشن صدا نیست — بخش ۵. |
| ربات بالا میاد ولی صدا توی کانال نیست | `python3 manage.py lines` بزن؛ اگه لاین 🔴 بود `manage.py line-ensure`. بعد چک کن `identity.json` از `line:` استفاده کرده باشه نه شماره. |
| `Permission denied` روی ffmpeg | خودش درست می‌شه (بیت اجرا ست می‌شه)؛ اگه نه: `chmod +x bin/ffmpeg`. |
| بررسی رسید انجام نمی‌شه | `tesseract-ocr` و `tesseract-ocr-fas` نصب نیستن. بدونشون هم پلتفرم کار می‌کنه، فقط رسیدها مستقیم می‌رن برای بررسی دستی. |
| ربات با کد ۳ خارج می‌شه | لایسنسش منقضی/معلقه یا `license.json` نداره. `manage.py license <کلید>` رو ببین. |
