#!/bin/sh
# به‌عنوان root شروع می‌شه تا مالکیتِ Volume رو درست کنه (Railway اون رو با
# مالک root سوار می‌کنه)، بعد با کاربر عادیِ «bot» ادامه می‌ده -- pulseaudio
# به‌عنوان root اجرا نمی‌شه.
set -e

mkdir -p /app/data /app/errors
for dir in /app/data /app/errors; do
    if [ "$(stat -c %U "$dir")" != "bot" ]; then
        chown -R bot:bot "$dir"
    fi
done

exec gosu bot /app/docker/start.sh "$@"
