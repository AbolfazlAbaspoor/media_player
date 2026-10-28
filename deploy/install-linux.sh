#!/usr/bin/env bash
# نصب یک‌مرحله‌ای روی اوبونتو/دبیان. از پوشه‌ی خود پروژه اجراش کن:
#   bash deploy/install-linux.sh
#
# قدم‌های مشترک با ویندوز (وابستگی‌های پایتون، ffmpeg، libmpv، SDK
# تیم‌تاک، جاوااسکریپت‌رانتایمِ yt-dlp، pulseaudio-utils) رو install.py
# انجام می‌ده (E9؛ ببین docs/INSTALL.md) -- این اسکریپت فقط چیزهایی که
# واقعاً مخصوصِ سرویس/سشنِ لینوکسه رو اضافه می‌کنه: پکیج‌های پایه‌ای که
# خودِ install.py برای اجرا لازمشون داره، سشن صدا، و systemd.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==> پکیج‌های پایه (پیش‌نیازِ خودِ install.py)"
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv \
    pulseaudio tesseract-ocr tesseract-ocr-fas

echo "==> وابستگی‌های پایتون + ffmpeg/libmpv/SDK تیم‌تاک/جاوااسکریپت‌رانتایم"
WITH_LICENSING_FLAG=""
if [ "${WITH_LICENSING:-1}" = "1" ]; then
    WITH_LICENSING_FLAG="--with-licensing"
fi
python3 install.py --venv .venv $WITH_LICENSING_FLAG

echo "==> سشن صدا (linger)"
# بدون این، سرویس بعد از logout می‌خوابه و pactl کار نمی‌کنه.
sudo loginctl enable-linger "$USER"
systemctl --user enable --now pulseaudio.socket pulseaudio.service 2>/dev/null || true

./.venv/bin/python manage.py doctor || true

echo
echo "==> تمام. قدم بعدی:"
echo "   source .venv/bin/activate"
echo "   python manage.py line-add bot1     # ساخت لاین صدا"
echo "   python bot.py                     # ساخت اولین ربات"
echo "   # یا برای پلتفرم فروش:"
echo "   python license_server.py --init"
