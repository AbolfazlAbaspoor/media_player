"""
راه‌اندازی تعاملی اولین اجرا. یه بار قبل از bot.py اجراش کن:

    python setup.py

برخلاف حدس زدن کورکورانه‌ی شماره‌ی دستگاه، اینجا دستگاه‌های واقعی صدا با
اسم‌شون لیست می‌شن (از همون کتابخانه‌های تیم‌تاک/mpv که خود ربات استفاده
می‌کنه) و می‌شه با خیال راحت انتخاب کرد -- یا مستقیم یه «لاین صدا»ی
اختصاصی برای این ربات ساخت.

روی ویندوز و لینوکس یکسان کار می‌کنه؛ تنها تفاوت اینه که روی لینوکس لاین
صدا به‌صورت بومی ساخته می‌شه (null-sink پالس‌اودیو) و روی ویندوز از
لاین‌های Virtual Audio Cable نصب‌شده یکی گرفته می‌شه.
"""

import json
import os

from core import audio_setup
from core import config_defaults
from core import platform_paths
from core.paths import get_base_dir

BASE_DIR = get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")


def main():
    print(f"سیستم‌عامل: {platform_paths.system_name()}")
    print(f"وضعیت اجرا: {platform_paths.describe_runtime()}\n")
    audio_setup.print_runtime_warnings()

    print("--- سرور ---")
    host = audio_setup.ask("آدرس سرور تیم‌تاک")
    port = audio_setup.ask("پورت (tcp=udp)", 10333, int)

    server_dir = os.path.join(DATA_DIR, config_defaults.server_folder_name(host, port))
    config_file = os.path.join(server_dir, "config.json")

    if os.path.exists(config_file):
        overwrite = audio_setup.ask(f"{config_file} از قبل وجود داره. بازنویسی بشه؟ (y/n)", "n")
        if overwrite.lower() != "y":
            print("لغو شد.")
            return

    cfg = {
        "server": {
            "host": host,
            "port": port,
            "nickname": audio_setup.ask("نیک‌نیم ربات", "Audio Player Bot"),
            "username": audio_setup.ask("یوزرنیم لاگین"),
            "password": audio_setup.ask("پسورد لاگین"),
        },
        "channel": {
            "id": audio_setup.ask("آیدی کانال پیش‌فرض", 1, int),
            "password": audio_setup.ask("پسورد کانال (اگه نداره خالی بذار)", ""),
        },
    }

    cfg["audio"] = audio_setup.choose_audio_devices(
        audio_setup.ask,
        line_slug_hint=config_defaults.server_folder_name(host, port),
        owner=config_defaults.server_folder_name(host, port),
    )

    print("\n--- اختیاری ---")
    proxy_enabled = audio_setup.ask("پروکسی فعال باشه؟ (y/n)", "n").lower() == "y"
    proxy_url = audio_setup.ask("لینک پروکسی", "") if proxy_enabled else ""
    cfg["proxy"] = {"enabled": proxy_enabled, "url": proxy_url or None}

    admins_raw = audio_setup.ask("یوزرنیم مدیرها، با کاما جدا کن (اختیاری)", "")
    cfg["admins"] = [a.strip() for a in admins_raw.split(",") if a.strip()]

    yt_api_key = audio_setup.ask("YouTube Data API key (اختیاری، Enter برای رد شدن)", "")
    cfg["youtube_api"] = {"enabled": bool(yt_api_key), "key": yt_api_key}

    cfg["status"] = {"visible": True, "idle_text": audio_setup.ask("متن استاتوس idle", "Idle")}
    cfg["audio_normalize"] = False
    cfg["language"] = "en"
    cfg["channel_messages_enabled"] = True
    cfg["roaming"] = {"enabled": True}
    cfg["access"] = {"mode": "all"}
    cfg["idle_channel"] = {"enabled": True, "pause_after_seconds": 60, "stop_after_seconds": 300}
    cfg["seek_default_seconds"] = 15
    cfg["reconnect_wait_ms"] = 5000
    cfg["cookies"] = {"enabled": True}

    os.makedirs(server_dir, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)

    print(f"\nذخیره شد: {config_file}. حالا می‌تونی bot.py رو اجرا کنی.")
    print("اختیاری: برای استفاده از کوکی یوتیوب (کمک می‌کنه گیر bot-detection نیفتی) یه فایل cookies.txt اینجا بذار:")
    print(f"  {os.path.join(server_dir, 'cookies.txt')}")
    print("(هر وقت خواستی توی چت با 'ck true'/'ck false' خاموش/روشنش کن، پیش‌فرض روشنه)")


if __name__ == "__main__":
    main()
