#!/bin/sh
# ۱) سرور صدا (pulseaudio) رو بدون systemd بالا می‌آره
# ۲) فایل‌های پلتفرم رو (اگه نیستن) می‌سازه
# ۳) license_server.py رو اجرا می‌کنه -- همین یه پروسه همه‌چیز رو بالا می‌آره
set -e

export HOME=/home/bot
export XDG_RUNTIME_DIR=/tmp/runtime-bot
mkdir -p "$XDG_RUNTIME_DIR"
chmod 700 "$XDG_RUNTIME_DIR"

start_pulse() {
    pulseaudio -n --daemonize=yes --exit-idle-time=-1 --disable-shm=yes \
        --use-pid-file=no --log-target=stderr \
        --load="module-native-protocol-unix" >/dev/null 2>&1 || true
}

start_pulse
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pactl info >/dev/null 2>&1 && break
    sleep 1
done
pactl info >/dev/null 2>&1 || echo "[start] WARNING: pulseaudio is not answering; audio lines will not work"

# اگه pulseaudio وسط کار مُرد، دوباره بالا بیارش (کد برنامه خودش لاین‌ها رو بازسازی می‌کنه)
(
    while sleep 30; do
        pactl info >/dev/null 2>&1 || start_pulse
    done
) &

cd /app
python license_server.py --init >/dev/null
exec python license_server.py "$@"
