# ایمیج Railway: فقط `python license_server.py` رو اجرا می‌کنه (ربات فروش +
# سوپروایزر ربات‌های تیم‌تاک + ربات‌های شخصی). راهنمای کامل: docs/RAILWAY.md
#
# چیزهای سنگین (ffmpeg، libmpv، pulseaudio، tesseract) با apt نصب می‌شن، نه از
# ریپو -- برای همین فایل‌های .dll/.exe ویندوزی (که بعضی‌شون بالای ۱۰۰ مگن)
# نباید توی گیت یا این ایمیج باشن.
FROM python:3.11-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        ffmpeg libmpv2 pulseaudio pulseaudio-utils \
        tesseract-ocr tesseract-ocr-fas \
        gosu ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --shell /bin/bash bot

WORKDIR /app

# وابستگی‌های پایتون اول (کش لایه: با عوض‌شدن کد دوباره نصب نمی‌شن)
COPY requirements.txt requirements-license.txt ./
RUN pip install -r requirements-license.txt

COPY . .

# SDK لینوکسیِ تیم‌تاک باید توی ریپو باشه (دانلود خودکار نداره -- docs/RAILWAY.md)
RUN test -f core/teamtalk/libTeamTalk5.so || { \
      echo "ERROR: core/teamtalk/libTeamTalk5.so is missing. Put the Linux x86_64 build of the TeamTalk 5 SDK there (see docs/RAILWAY.md)."; \
      exit 1; } \
 && { ldd core/teamtalk/libTeamTalk5.so | grep "not found" && { echo "ERROR: libTeamTalk5.so needs the libraries listed above"; exit 1; } || true; }

# جاوااسکریپت‌رانتایم yt-dlp (deno) -- اگه دانلودش نشد فقط هشدار می‌دیم
RUN python install.py --components js_runtime || echo "WARNING: deno was not installed; some yt-dlp sites may not work"

RUN chmod +x docker/entrypoint.sh docker/start.sh \
 && mkdir -p /app/data /app/errors \
 && chown -R bot:bot /app

# نکته: دستور VOLUME اینجا نیست چون Railway ازش پشتیبانی نمی‌کنه؛ Volume رو
# توی داشبورد به /app/data وصل کن (docs/RAILWAY.md).

ENTRYPOINT ["/app/docker/entrypoint.sh"]
