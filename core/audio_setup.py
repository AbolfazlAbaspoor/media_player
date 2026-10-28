"""
انتخاب تعاملی دستگاه صدا موقع ساخت یه ربات جدید (ویزارد bot.py و setup.py).

این فایل عمداً از core.audio_lines جداست: اون‌یکی منطق خالصِ ساخت/حذف لاینه
و هیچ input()ای نداره، پس هم ربات لایسنس و هم سرویس‌های خودکار می‌تونن
ازش استفاده کنن. اینجا فقط لایه‌ی «پرسیدن از کاربر»ه.

سه راه به کاربر داده می‌شه:

  ۱. لاین صدای مدیریت‌شده (پیشنهادی) -- روی لینوکس یه null-sink تازه ساخته
     می‌شه، روی ویندوز یکی از لاین‌های آزاد Virtual Audio Cable گرفته می‌شه.
     مقدار ذخیره‌شده "line:<slug>" است، پس ربات بعد از ریبوت خودش لاین رو
     بازمی‌سازه.
  ۲. انتخاب دستی از لیست دستگاه‌های واقعی سیستم (با اسم، نه شماره).
  ۳. وارد کردن مستقیم مقدار (برای حالت‌های خاص).
"""

import sys

from core import audio_lines
from core import platform_paths


def ask(prompt, default=None, cast=str):
    """سؤالِ کنسولیِ ویزاردهای راه‌اندازی (bot.py و setup.py)؛ مشترک."""
    try:
        raw = input(f"{prompt}" + (f" [{default}]" if default is not None else "") + ": ").strip()
    except EOFError:
        # ورودی تعاملی نیست (دابل‌کلیک روی exe، اجرا از سرویس، یا pipe).
        # traceback خام اینجا برای کاربر نهایی هیچ معنایی نداره.
        print()
        print("این ویزارد ورودی تعاملی لازم داره.")
        print("از داخل ترمینال (cmd یا PowerShell) اجراش کن، نه با دابل‌کلیک.")
        sys.exit(1)
    if not raw:
        if default is not None:
            return default
        raw = ""
    try:
        return cast(raw) if raw != "" else default
    except ValueError:
        print("مقدار نامعتبره، دوباره امتحان کن.")
        return ask(prompt, default, cast)


def _print_line_backend_hint():
    mode = audio_lines.backend()
    if mode == "pulse":
        if audio_lines.pulse_available():
            print("لاین صدا روی این سیستم به‌صورت بومی ساخته می‌شه (null-sink پالس‌اودیو/پایپ‌وایر).")
        else:
            print("pactl نصبه ولی به سرور صدا وصل نشدیم؛ اگه با systemd اجرا می‌کنی یه سرویس کاربری بساز")
            print("و برای اون کاربر linger رو فعال کن: sudo loginctl enable-linger <user>")
    elif mode == "windows":
        print("روی ویندوز لاین جدید ساخته نمی‌شه؛ از لاین‌های Virtual Audio Cable نصب‌شده یکی گرفته می‌شه.")
    else:
        print("این سیستم هیچ راهی برای لاین صدای مجازی نداره (روی لینوکس pulseaudio-utils نصب کن).")


def _pick_from_list(ask, label, items):
    """
    items: [(value, display)]. مقدار انتخاب‌شده برگردونده می‌شه، یا None اگه
    لیست خالی بود.
    """
    if not items:
        print(f"هیچ دستگاه {label}ی پیدا نشد.")
        return None

    print(f"\nدستگاه‌های {label} موجود:")
    for i, (_value, display) in enumerate(items, start=1):
        print(f"  {i}. {display}")

    choice = ask(f"یکی از دستگاه‌های {label} رو انتخاب کن (شماره)", 1, int)
    try:
        choice = int(choice)
    except (TypeError, ValueError):
        choice = 1
    choice = max(1, min(len(items), choice))
    value, display = items[choice - 1]
    print(f"-> انتخاب شد: {display}")
    return value


def _input_device_items():
    preferred = audio_lines.preferred_sound_system()
    items = []
    for dev_id, name, sound_system, dev_id_str in audio_lines.list_input_devices():
        # مقدار ذخیره‌شده اسمه نه شماره، چون شماره بین ری‌استارت‌ها عوض می‌شه.
        tag = ""
        if preferred is not None and sound_system == preferred:
            tag = " *"
        items.append((name, f"{name}{tag}"))
    # دستگاه‌های سیستم صوتی «درست» اول لیست، چون همون‌ها معمولاً جواب می‌دن.
    return items


def _output_device_items():
    items = []
    for name, description in audio_lines.list_output_devices():
        if not name:
            continue
        items.append((name, f"{description}  [{name}]"))
    return items


def choose_audio_devices(ask, line_slug_hint="bot", owner=None):
    """
    خروجی: dict با کلیدهای input_device و output_device، آماده برای
    نوشتن توی identity.json.

    ask همون تابع پرسشِ خود ویزاره (prompt, default, cast) -- عمداً پاس
    داده می‌شه تا این فایل به input() مستقیم وابسته نباشه و بشه توی تست
    جایگزینش کرد.
    """
    print("\n--- دستگاه صدا ---")
    _print_line_backend_hint()
    print("۱) ساخت/گرفتن یه لاین صدای اختصاصی برای همین ربات (پیشنهادی)")
    print("۲) انتخاب دستی از دستگاه‌های سیستم")
    print("۳) وارد کردن مستقیم مقدار")

    mode = ask("کدوم روش؟", 1, int)
    try:
        mode = int(mode)
    except (TypeError, ValueError):
        mode = 1

    if mode == 1:
        slug = audio_lines.safe_line_slug(
            ask("یه اسم کوتاه برای این لاین", audio_lines.safe_line_slug(line_slug_hint))
        )
        try:
            line = audio_lines.create_line(slug, description=f"TeamTalk bot: {slug}", owner=owner)
        except audio_lines.AudioLineError as e:
            print(f"ساخت لاین صدا نشد: {e}")
            print("برو به روش دستی.")
            mode = 2
        else:
            print(f"-> لاین '{line['slug']}' آماده‌ست:")
            print(f"   خروجی (mpv توش می‌نویسه): {line['output_device']}")
            print(f"   ورودی (تیم‌تاک ازش می‌خونه): {line['input_device']}")
            return {"input_device": f"line:{line['slug']}", "output_device": f"line:{line['slug']}"}

    if mode == 2:
        output_value = _pick_from_list(ask, "خروجی", _output_device_items())
        input_value = _pick_from_list(ask, "ورودی", _input_device_items())
        return {
            "input_device": input_value if input_value is not None else 0,
            "output_device": output_value if output_value is not None else 0,
        }

    print("مقدار می‌تونه اسم دستگاه، شماره‌ی خام، یا line:<slug> باشه.")
    return {
        "input_device": ask("دستگاه ورودی صدا", 0),
        "output_device": ask("دستگاه خروجی صدا", 0),
    }


def print_runtime_warnings():
    """
    قبل از هر چیزی به کاربر می‌گه چی کم داره. روی لینوکس این معمولاً تنها
    چیزیه که بین «کار نمی‌کنه» و «کار می‌کنه» فاصله‌ست.
    """
    problems = platform_paths.missing_runtime_requirements()
    if not problems:
        return True
    print("\n[!] چند چیز لازم برای اجرا پیدا نشد:")
    for problem in problems:
        print(f"    - {problem}")
    print()
    return False
