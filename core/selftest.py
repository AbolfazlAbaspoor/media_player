"""
تست خودکار سلامت ربات موقع راه‌اندازی.

## چرا لازمه

بیشتر خرابی‌های این ربات «ساکت»ن: ربات بالا میاد، توی کانال دیده می‌شه، و
کاربر فکر می‌کنه همه‌چیز درسته -- ولی صدا هیچ‌جا نمی‌ره. دلایل رایج: لاین
صدا بعد از ریبوت از بین رفته، شماره‌ی دستگاه عوض شده، ffmpeg نصب نیست، یا
کوکی منقضی شده. هیچ‌کدوم خطا raise نمی‌کنن.

این ماژول موقع استارت همه‌ی این‌ها رو *واقعاً امتحان می‌کنه* و اگه چیزی
خراب بود، همون لحظه با یه پیام مشخص می‌گه -- نه اینکه نیم ساعت بعد کاربر
بگه «صدا نمیاد».

## تست واقعی، نه چک کانفیگ

تفاوت مهم: این فایل فقط نگاه نمی‌کنه که «آیا اسم دستگاه توی کانفیگ هست».
دستگاه خروجی رو **باز می‌کنه** و یه تُن کوتاه (۰.۳ ثانیه، تولیدشده‌ی
داخلی، بدون هیچ درخواست شبکه‌ای) پخش می‌کنه، و دستگاه ورودی رو واقعاً
initialize می‌کنه. یه کانفیگ درست که به دستگاه ازبین‌رفته اشاره می‌کنه،
اینجا گیر می‌افته.

## روی اشیای زنده کار می‌کنه

player و tt ای که پاس داده می‌شن، همون‌هایی هستن که ربات واقعاً استفاده
می‌کنه -- نه یه نمونه‌ی تازه. یعنی تست همون چیزی رو می‌سنجه که در عمل
اجرا می‌شه، و هیچ نمونه‌ی اضافه‌ای از mpv/SDK ساخته نمی‌شه (که هم کند بود
هم می‌تونست دستگاه رو قفل کنه).

## هیچ‌وقت جلوی استارت رو نمی‌گیره

خروجی این تست فقط گزارشه. تصمیم اینکه با یه خرابی ربات بالا بیاد یا نه،
کار صداکننده‌ست -- چون مثلاً نبودن ffmpeg فقط دستور dl رو از کار می‌اندازه
و دلیلی نیست کل ربات اجرا نشه.
"""

import os
import shutil
import subprocess
import time

from core import logging_setup

OK = "ok"
WARN = "warn"
FAIL = "fail"

_ICONS = {OK: "✅", WARN: "⚠️", FAIL: "❌"}


class Result:
    __slots__ = ("name", "status", "message", "hint", "duration")

    def __init__(self, name, status, message="", hint="", duration=0.0):
        self.name = name
        self.status = status
        self.message = message
        self.hint = hint
        self.duration = duration

    @property
    def icon(self):
        return _ICONS.get(self.status, "•")

    def line(self):
        text = f"{self.icon} {self.name}"
        if self.message:
            text += f": {self.message}"
        return text

    def full(self):
        text = self.line()
        if self.hint:
            text += f"\n     ↳ {self.hint}"
        return text


class Report:
    def __init__(self):
        self.results = []
        self.started_at = time.time()

    def add(self, name, status, message="", hint="", duration=0.0):
        self.results.append(Result(name, status, message, hint, duration))
        return self.results[-1]

    def count(self, status):
        return sum(1 for r in self.results if r.status == status)

    @property
    def failures(self):
        return [r for r in self.results if r.status == FAIL]

    @property
    def warnings(self):
        return [r for r in self.results if r.status == WARN]

    def ok(self):
        return not self.failures

    def summary(self):
        elapsed = time.time() - self.started_at
        parts = [f"{self.count(OK)} سالم"]
        if self.count(WARN):
            parts.append(f"{self.count(WARN)} هشدار")
        if self.count(FAIL):
            parts.append(f"{self.count(FAIL)} خطا")
        return "، ".join(parts) + f" ({elapsed:.1f}s)"

    def text(self, only_problems=False):
        lines = []
        for result in self.results:
            if only_problems and result.status == OK:
                continue
            lines.append(result.full())
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# تک‌تک تست‌ها
# ---------------------------------------------------------------------------

def _timed(fn, *args, **kwargs):
    start = time.time()
    try:
        return fn(*args, **kwargs), time.time() - start
    except Exception as e:
        return e, time.time() - start


def check_runtime(report):
    from core import platform_paths

    report.add("سیستم‌عامل و کتابخانه‌ها", OK, platform_paths.describe_runtime())

    problems = platform_paths.missing_runtime_requirements()
    for problem in problems:
        # نبودن ffmpeg فقط dl رو از کار می‌اندازه، ولی نبودن SDK/mpv یعنی
        # ربات اصلاً نمی‌تونه کار کنه.
        status = WARN if "ffmpeg" in problem else FAIL
        report.add("پیش‌نیاز", status, problem)
    if not problems:
        report.add("پیش‌نیازها", OK, "همه موجودن")


def check_ffmpeg(report):
    from core import platform_paths

    binary = platform_paths.ffmpeg_binary()
    if not binary:
        report.add("ffmpeg", WARN, "پیدا نشد",
                   "دستور dl بدون تبدیل به mp3 کار می‌کنه. نصب: apt install ffmpeg")
        return
    try:
        proc = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        report.add("ffmpeg", FAIL, f"اجرا نشد: {e}",
                   "روی لینوکس معمولاً بیت اجرا نداره: chmod +x " + binary)
        return
    if proc.returncode != 0:
        report.add("ffmpeg", FAIL, f"با کد {proc.returncode} خارج شد")
        return
    version = (proc.stdout or "").splitlines()[0] if proc.stdout else "نسخه نامشخص"
    report.add("ffmpeg", OK, version[:70])


def check_audio_output(report, player, configured, play_tone=True):
    """
    دستگاه خروجی رو *واقعاً باز می‌کنه* و یه تُن کوتاه پخش می‌کنه.

    تُن با av://lavfi ساخته می‌شه، یعنی داخل خود mpv تولید می‌شه و هیچ فایل
    یا درخواست شبکه‌ای لازم نداره.
    """
    from core import audio_lines

    if player is None:
        report.add("خروجی صدا", WARN, "پخش‌کننده در دسترس نیست")
        return

    try:
        resolved = audio_lines.resolve_output_device(configured)
    except Exception as e:
        report.add("خروجی صدا", FAIL, f"«{configured}» پیدا نشد: {e}",
                   "با «python manage.py devices» دستگاه‌های موجود رو ببین")
        return

    # اسم دستگاه باید واقعاً بین دستگاه‌های mpv باشه
    try:
        available = {name for name, _desc in audio_lines.list_output_devices() if name}
    except Exception:
        available = set()

    if available and isinstance(resolved, str) and resolved not in available:
        report.add("خروجی صدا", FAIL, f"دستگاه «{resolved}» بین دستگاه‌های mpv نیست",
                   "اگه لاین صداست: python manage.py line-ensure")
        return

    if not play_tone:
        report.add("خروجی صدا", OK, f"{resolved} (تُن تست نزدیم)")
        return

    outcome, elapsed = _timed(_play_test_tone, player)
    if isinstance(outcome, Exception):
        report.add("خروجی صدا", FAIL, f"{resolved} باز نشد: {outcome}",
                   "دستگاه ممکنه در اختیار برنامه‌ی دیگه‌ای باشه", duration=elapsed)
        return
    if outcome is False:
        report.add("خروجی صدا", WARN, f"{resolved} — تُن تست پخش نشد",
                   "معمولاً یعنی دستگاه مشغوله؛ خودِ پخش ممکنه بعداً کار کنه",
                   duration=elapsed)
        return
    report.add("خروجی صدا", OK, f"{resolved} — تُن تست پخش شد", duration=elapsed)


def _play_test_tone(player, seconds=0.3):
    """
    یه سینوسِ کم‌صدا روی دستگاه خروجی فعلی. True اگه واقعاً شروع به پخش کرد.

    lavfi داخل mpv اجرا می‌شه، پس نه فایلی لازمه نه شبکه‌ای. حجم صدا عمداً
    پایینه: اگه خروجی اسپیکر واقعی باشه (نصب شخصی)، یه بیپ آزاردهنده نباشه.
    """
    previous_volume = None
    try:
        previous_volume = player.volume
    except Exception:
        pass

    try:
        try:
            player.volume = 15
        except Exception:
            pass

        player.play(f"av://lavfi:sine=frequency=440:duration={seconds}")

        # منتظر می‌مونیم واقعاً شروع بشه، نه فقط دستور رفته باشه.
        deadline = time.time() + 4
        started = False
        while time.time() < deadline:
            try:
                if player.position_seconds is not None or player.duration_seconds is not None:
                    started = True
                    break
            except Exception:
                pass
            time.sleep(0.05)

        time.sleep(min(seconds, 0.4))
        return started
    finally:
        try:
            player.stop()
        except Exception:
            pass
        if previous_volume is not None:
            try:
                player.volume = previous_volume
            except Exception:
                pass


def check_audio_input(report, tt, configured, opened=None):
    """
    ورودی صدای ربات.

    `opened` همون چیزیه که خود ربات موقع استارت باز کرده: (device_id, name).
    اگه داشته باشیمش، *دوباره باز نمی‌کنیم*. تیم‌تاک اجازه نمی‌ده یه دستگاه
    ورودیِ باز، دوباره initialize بشه (initSoundInputDevice دومی false
    برمی‌گردونه) -- و همین باعث می‌شد تستِ سلامت روی رباتِ کاملاً سالم
    «❌ ورودی صدا ... Input device setup failed» بده. یه هشدار دروغ که
    دقیقاً همون چیزی رو بی‌اعتبار می‌کنه که این تست برای دیدنش ساخته شده.
    """
    from core import audio_lines

    if opened:
        dev_id, name = opened[0], opened[1]
        report.add("ورودی صدا", OK, f"[{dev_id}] {name} — باز و در حال استفاده‌ی ربات")
        return

    try:
        candidates = audio_lines.resolve_input_devices(configured)
    except Exception as e:
        report.add("ورودی صدا", FAIL, f"«{configured}» پیدا نشد: {e}",
                   "با «python manage.py devices» دستگاه‌های موجود رو ببین")
        return

    if tt is None:
        dev_id, name = candidates[0]
        report.add("ورودی صدا", OK,
                   f"[{dev_id}] {name} (تیم‌تاک در دسترس نیست، فقط اسم چک شد)")
        return

    # همون کاری که خود ربات می‌کنه: تا اولین دستگاهی که *واقعاً* باز بشه.
    # چک‌کردن فقط کاندید اول، یه شکستِ الکی گزارش می‌داد درحالی‌که ربات
    # با کاندید بعدی مشکلی نداشت (و برعکس).
    outcome, elapsed = _timed(audio_lines.open_input_device, tt.set_input_device, configured)
    if isinstance(outcome, Exception):
        listed = ", ".join(f"[{i}] {n}" for i, n in candidates)
        report.add("ورودی صدا", FAIL, f"هیچ‌کدوم باز نشد ({listed}): {outcome}",
                   "دستگاه ممکنه وجود نداشته باشه یا در اختیار برنامه‌ی دیگه‌ای باشه",
                   duration=elapsed)
        return

    dev_id, name, tried = outcome
    label = f"[{dev_id}] {name}"
    if tried:
        skipped = ", ".join(f"[{i}] {n}" for i, n, _e in tried)
        report.add("ورودی صدا", OK, f"{label} — آماده (باز نشدن و رد شدن: {skipped})",
                   duration=elapsed)
        return
    report.add("ورودی صدا", OK, f"{label} — آماده", duration=elapsed)


def check_audio_line(report, configured_input, configured_output):
    """
    اگه کانفیگ به یه لاین مدیریت‌شده اشاره می‌کنه، بررسی می‌کنه که لاین
    واقعاً روی سیستم زنده باشه. روی لینوکس بعد از ریبوت این همون چیزیه که
    از بین می‌ره.
    """
    from core import audio_lines

    slugs = set()
    for value in (configured_input, configured_output):
        if isinstance(value, str) and value.startswith("line:"):
            slugs.add(audio_lines.safe_line_slug(value[5:]))

    if not slugs:
        report.add("لاین صدا", OK, "استفاده نشده (دستگاه مستقیم)")
        return

    try:
        lines = {line["slug"]: line for line in audio_lines.list_lines()}
    except Exception as e:
        report.add("لاین صدا", WARN, f"وضعیت لاین‌ها خونده نشد: {e}")
        return

    for slug in sorted(slugs):
        line = lines.get(slug)
        if line is None:
            report.add(f"لاین صدا «{slug}»", FAIL, "ثبت نشده",
                       f"python manage.py line-add {slug}")
        elif not line.get("alive"):
            report.add(f"لاین صدا «{slug}»", FAIL, "ثبت شده ولی روی سیستم نیست",
                       "python manage.py line-ensure")
        else:
            report.add(f"لاین صدا «{slug}»", OK,
                       f"out={line.get('output_device')} in={line.get('input_device')}")


def check_services(report, services):
    if not services:
        report.add("سرویس‌ها", FAIL, "هیچ سرویسی لود نشد",
                   "پوشه‌ی core/services رو چک کن")
        return
    report.add("سرویس‌ها", OK, f"{len(services)} سرویس: {', '.join(sorted(services))}")


def check_commands(report, commands):
    if not commands:
        report.add("دستورها", FAIL, "هیچ دستوری لود نشد",
                   "پوشه‌ی commands رو چک کن")
        return
    report.add("دستورها", OK, f"{len(commands)} دستور فعال")


def check_language(report, i18n_module, language):
    try:
        available = [name for name, _label in i18n_module.available_languages()]
        if not available:
            # ممکنه تست قبل از load_languages اجرا شده باشه؛ خودمون یه بار
            # لودش می‌کنیم تا نتیجه به ترتیب فراخوانی وابسته نباشه.
            i18n_module.load_languages()
            available = [name for name, _label in i18n_module.available_languages()]
    except Exception as e:
        report.add("زبان", FAIL, f"فایل‌های زبان خونده نشدن: {e}")
        return
    if not available:
        report.add("زبان", FAIL, "هیچ فایل زبانی پیدا نشد",
                   "پوشه‌ی languages باید en.json داشته باشه")
        return
    if language not in available:
        report.add("زبان", WARN, f"«{language}» موجود نیست؛ از پیش‌فرض استفاده می‌شه",
                   f"موجود: {', '.join(available)}")
        return
    report.add("زبان", OK, f"{language} (موجود: {', '.join(available)})")


def check_writable(report, *directories):
    for directory in directories:
        if not directory:
            continue
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, ".write_probe")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
        except OSError as e:
            report.add("دسترسی نوشتن", FAIL, f"{directory}: {e}",
                       "ربات نمی‌تونه کانفیگ/دانلود/لاگ بنویسه")
            return
    report.add("دسترسی نوشتن", OK, "پوشه‌های دیتا قابل نوشتنن")


def check_disk_space(report, path, min_free_mb=200):
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        report.add("فضای دیسک", WARN, f"خونده نشد: {e}")
        return
    free_mb = usage.free // (1024 * 1024)
    if free_mb < min_free_mb:
        report.add("فضای دیسک", WARN, f"فقط {free_mb} مگابایت آزاد",
                   "دستور dl برای دانلود فایل به فضا نیاز داره")
        return
    report.add("فضای دیسک", OK, f"{free_mb // 1024} گیگابایت آزاد" if free_mb >= 1024
               else f"{free_mb} مگابایت آزاد")


def check_license(report, license_state):
    if license_state is None:
        return
    if license_state.unlicensed and not license_state.managed:
        report.add("لایسنس", OK, "بدون لایسنس (همه‌ی امکانات فعال)")
        return
    status = license_state.status_text()
    if license_state.blocks_startup():
        report.add("لایسنس", FAIL, status)
    elif license_state.is_expired() or license_state.in_grace():
        report.add("لایسنس", WARN, status, "برای تمدید به ربات تلگرام لایسنس برو")
    else:
        report.add("لایسنس", OK, status)


def check_cookies(report, bot):
    """
    کوکی‌ها فقط اگه فعال باشن چک می‌شن. فایل کوکیِ منقضی یکی از دلایل رایج
    «یوتیوب می‌گه ربات هستی»ه و بی‌صدا اتفاق می‌افته.
    """
    cfg = getattr(bot, "cfg", None) or {}
    if not cfg.get("cookies", {}).get("enabled", True):
        report.add("کوکی", OK, "خاموش")
        return

    getter = getattr(bot, "cookies_file_for", None)
    if not callable(getter):
        report.add("کوکی", OK, "تنظیم نشده")
        return

    found = []
    for service in ("youtube", "instagram"):
        try:
            path = getter(service)
        except Exception:
            path = None
        if path and os.path.isfile(path):
            age_days = (time.time() - os.path.getmtime(path)) / 86400
            found.append(f"{service} ({int(age_days)} روزه)")
            if age_days > 60:
                report.add(f"کوکی {service}", WARN,
                           f"{int(age_days)} روز از آخرین به‌روزرسانیش گذشته",
                           "کوکی قدیمی باعث «Sign in to confirm you're not a bot» می‌شه")

    if found:
        report.add("کوکی", OK, "، ".join(found))
    else:
        report.add("کوکی", OK, "فایلی گذاشته نشده (اختیاری)")


def check_documentary(report, bot):
    """
    فقط الگوی آدرس رو اعتبارسنجی می‌کنه؛ هیچ درخواستی به منبع زده نمی‌شه.
    """
    from core import documentary

    state = getattr(bot, "license", None)
    if state is not None and not state.allows_service("documentary"):
        return
    try:
        sample = documentary.url_for(bot, documentary.min_number(bot))
    except Exception:
        # متنِ خطا خودش ممکنه الگوی آدرس رو داشته باشه؛ جزئیات فقط توی لاگ.
        logging_setup.log_exception("documentary url pattern")
        report.add("مستند", FAIL, "الگوی آدرس خرابه (جزئیات توی لاگ خطا)")
        return
    # آدرس نشون داده نمی‌شه: dg رو ادمینِ ربات می‌زنه، و روی ربات اجاره‌ای یا
    # میزبانی‌شده ادمین خودِ مشتریه. با الگوی آدرس، هر مستندِ پولی رو مستقیم
    # دانلود می‌کرد. «الگو سالمه» برای عیب‌یابی کافیه.
    report.add("مستند", OK, f"از شماره {documentary.min_number(bot)} — الگوی آدرس سالمه"
               if sample else f"از شماره {documentary.min_number(bot)}")


def check_iptv(report, bot):
    """
    فقط شکلِ تنظیمات رو اعتبارسنجی می‌کنه (منبع‌ها آدرس http(s) معتبر
    دارن)؛ هیچ درخواستی به هیچ منبعی زده نمی‌شه، دقیقاً مثل check_documentary.
    """
    from core import iptv

    state = getattr(bot, "license", None)
    if state is not None and not state.allows_service(iptv.SERVICE_NAME):
        return
    srcs = iptv.sources(bot)
    if not srcs:
        report.add("IPTV", WARN, "هیچ منبعی تنظیم نشده")
        return
    bad = [s.get("name") or "?" for s in srcs if not iptv.looks_like_source_url(s.get("url"))]
    if bad:
        # اسمِ منبع نشون داده می‌شه، نه آدرسش -- همون قاعده‌ی همیشگیِ IPTV.
        report.add("IPTV", FAIL, "آدرس نامعتبر توی منبع(های): " + "، ".join(bad))
        return
    report.add("IPTV", OK, f"{len(srcs)} منبع تنظیم شده")


# ---------------------------------------------------------------------------
# اجرای کامل
# ---------------------------------------------------------------------------

def run(bot=None, player=None, tt=None, play_tone=True, include_slow=True):
    """
    همه‌ی تست‌ها. هیچ استثنایی بیرون نمی‌ده -- خودِ تست سلامت نباید باعث
    بالا نیامدن ربات بشه.
    """
    report = Report()
    cfg = (getattr(bot, "cfg", None) or {}) if bot is not None else {}
    audio = cfg.get("audio", {}) if isinstance(cfg.get("audio"), dict) else {}

    steps = [
        (check_runtime, (report,)),
        (check_services, (report, getattr(bot, "services", None) or {})),
        (check_commands, (report, getattr(bot, "commands", None) or {})),
    ]

    for fn, args in steps:
        try:
            fn(*args)
        except Exception as e:
            report.add(fn.__name__, WARN, f"خود تست خطا داد: {e}")

    optional = []
    if bot is not None:
        from core import i18n
        optional += [
            (check_language, (report, i18n, cfg.get("language", "en"))),
            (check_license, (report, getattr(bot, "license", None))),
            (check_cookies, (report, bot)),
            (check_documentary, (report, bot)),
            (check_iptv, (report, bot)),
        ]
        data_dir = getattr(bot, "data_dir", None)
        bot_dir = getattr(bot, "bot_dir", None)
        optional.append((check_writable, (report, data_dir, bot_dir)))
        if data_dir:
            optional.append((check_disk_space, (report, data_dir)))

    optional.append((check_audio_line, (report, audio.get("input_device"), audio.get("output_device"))))
    optional.append((check_audio_input, (report, tt, audio.get("input_device"),
                                         getattr(bot, "audio_input", None))))
    optional.append((check_audio_output, (report, player, audio.get("output_device"), play_tone)))

    if include_slow:
        optional.append((check_ffmpeg, (report,)))

    for fn, args in optional:
        try:
            fn(*args)
        except Exception as e:
            report.add(getattr(fn, "__name__", "test"), WARN, f"خود تست خطا داد: {e}")

    return report


def print_report(report, only_problems=False):
    print("── تست سلامت ربات ──")
    text = report.text(only_problems=only_problems)
    if text:
        print(text)
    print(f"── {report.summary()} ──")
