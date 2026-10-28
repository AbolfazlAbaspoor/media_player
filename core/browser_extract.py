"""
استخراج لینک m3u8 از صفحات وب عمومی (سایت‌های استریم که لینک مستقیم پخش
نمی‌دن) با استفاده از Playwright به‌صورت headless.

نکته مهم: این ماژول هیچ ویدیویی رندر نمی‌کنه و پنجره‌ای باز نمی‌شه؛ فقط
درخواست‌های شبکه‌ی صفحه رو زیر نظر می‌گیره تا اولین لینک m3u8 رو پیدا کنه.
بعدش دقیقاً مثل هر لینک دیگه‌ای دست mpv داده می‌شه (فقط صدا پخش می‌شه).

پیش‌نیاز:
    pip install playwright
    playwright install chromium
"""

import time

_UNAVAILABLE_COOLDOWN_SECONDS = 600
_unavailable_until = 0.0
_unavailable_reason = None

# پسوندهای رسانه‌ای که موقع sniff کردن ترافیک شبکه‌ی صفحه دنبالشون می‌گردیم.
# قبلاً فقط m3u8 چک می‌شد؛ خیلی از پلیرهای ساده مستقیم mp4/mp3 لود می‌کنن نه HLS.
_MEDIA_URL_MARKERS = (".m3u8", ".mp4", ".mp3", ".m4a", ".webm", ".ogg", ".aac", ".flac", ".wav")


def is_available():
    """True یعنی احتمالاً می‌شه امتحان کرد (یا هنوز امتحان نکردیم، یا قبلاً موفق بوده)."""
    return time.time() >= _unavailable_until


def _looks_like_media_request(url: str) -> bool:
    lowered = url.lower().split("?", 1)[0]
    return any(lowered.endswith(ext) for ext in _MEDIA_URL_MARKERS) or ".m3u8" in url.lower()


def _looks_like_media_response(content_type: str) -> bool:
    """پاسخِ صدا/تصویر یا لیستِ HLS -- استریمِ بی‌پسوند (icecast) رو هم می‌گیره."""
    ctype = (content_type or "").split(";")[0].strip().lower()
    return ctype.startswith(("audio/", "video/")) or ctype in (
        "application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml", "application/ogg")


# بعضی پلیرها تا کاربر play نزنه هیچ درخواستی نمی‌فرستن: بی‌صدا (muted) شروعشون
# می‌کنیم تا autoplay-policy جلوش رو نگیره.
_PLAY_MEDIA_JS = "document.querySelectorAll('audio,video').forEach(m => { m.muted = true; m.play().catch(() => {}); })"


def extract_stream(url: str, wait_seconds: float = 7.0, timeout_ms: int = 20000):
    """
    صفحه رو headless باز می‌کنه، تا wait_seconds صبر می‌کنه تا استریم لود
    بشه، و اولین درخواست شبکه‌ای که به یه فایل رسانه‌ای شناخته‌شده اشاره
    کنه (m3u8/mp4/mp3/...) رو برمی‌گردونه. اگه چیزی پیدا نشه None برمی‌گردونه.

    raise می‌کنه اگه پکیج/مرورگر playwright نصب نباشه یا لود نشه، تا صدا
    زننده پیام روشنی به کاربر بده (و توی چت هم چیزی جز یه پیام امن درز نکنه).
    """
    global _unavailable_until, _unavailable_reason

    if not is_available():
        raise RuntimeError(_unavailable_reason or "Browser-based link extraction is temporarily unavailable.")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _unavailable_reason = "Playwright is not installed (pip install playwright)."
        _unavailable_until = time.time() + _UNAVAILABLE_COOLDOWN_SECONDS
        raise RuntimeError(_unavailable_reason)

    found = {"url": None}

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception:
                _unavailable_reason = "Playwright browser is not installed (playwright install chromium)."
                _unavailable_until = time.time() + _UNAVAILABLE_COOLDOWN_SECONDS
                raise RuntimeError(_unavailable_reason)
            try:
                page = browser.new_page()

                def on_request(request):
                    if found["url"] is None and _looks_like_media_request(request.url):
                        found["url"] = request.url

                def on_response(response):
                    if found["url"] is None and _looks_like_media_response(response.headers.get("content-type")):
                        found["url"] = response.url

                page.on("request", on_request)
                page.on("response", on_response)
                try:
                    page.goto(url, timeout=timeout_ms)
                except Exception:
                    # صفحه‌ای که هیچ‌وقت کامل لود نمی‌شه ولی استریمش رو فرستاده.
                    if found["url"] is None:
                        raise
                for frame in page.frames:
                    try:
                        frame.evaluate(_PLAY_MEDIA_JS)
                    except Exception:
                        pass
                page.wait_for_timeout(int(wait_seconds * 1000))
            finally:
                browser.close()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Browser-based extraction failed: {e}")

    return found["url"]


# سازگاری با کد قدیمی که هنوز extract_m3u8 صدا می‌زنه.
extract_m3u8 = extract_stream
