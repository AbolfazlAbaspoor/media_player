"""
پیام همگانی (C1): فرستادنِ یه پیام دلخواه (متن/عکس/ویدیو/صدا/فایل) به همه‌ی
کاربرها یا زیرمجموعه‌ای ازشون.

## چرا copy_message

با copy_message فرستاده می‌شه، نه با خوندنِ نوع پیام و ساختنِ دوباره‌ش:
هر فرمت‌بندی (bold/italic/لینک) و هر رسانه‌ای (عکس/ویدیو/صدا/فایل) دقیقاً
همون‌طور که ادمین فرستاده به مقصد می‌رسه، بدون این‌که این ماژول لازم باشه
بدونه پیام از چه نوعیه.

## چرا یه‌بار در یک زمان

پیام همگانیِ بعدی تا تمومِ قبلی صبر می‌کنه (bot_data["broadcast"] توی
لایه‌ی هندلرها) -- اجرای هم‌زمانِ دوتا فقط ترتیب رو قاطی می‌کنه و سریع‌تر
به سقفِ نرخِ تلگرام می‌رسه، بدون هیچ فایده‌ای.

## نرخ ارسال

زیرِ سقفِ تقریبیِ تلگرام برای چت‌های خصوصی (~۳۰/ثانیه) نگه داشته می‌شه، و
RetryAfter همیشه رعایت می‌شه -- نادیده گرفتنش یعنی محدودشدنِ کاملِ ربات،
نه فقط پیامِ همگانی.
"""

import asyncio

from telegram.error import Forbidden, RetryAfter, TelegramError

from core import logging_setup

AUDIENCE_ALL = "all"
AUDIENCE_ACTIVE = "active"
AUDIENCE_INACTIVE = "inactive"

#: ترتیبِ نمایش توی دکمه‌ها هم همینه.
AUDIENCES = (AUDIENCE_ALL, AUDIENCE_ACTIVE, AUDIENCE_INACTIVE)

#: پیام در ثانیه -- زیرِ سقفِ تقریبیِ ۳۰/ثانیه‌ی تلگرام برای چت خصوصی.
RATE_PER_SECOND = 25


def recipients(db, audience):
    """آیدی تلگرامِ گیرنده‌های این مخاطب؛ بلاک‌کننده‌های ربات همیشه حذفن."""
    if audience == AUDIENCE_ACTIVE:
        return db.broadcast_recipients(active_only=True)
    if audience == AUDIENCE_INACTIVE:
        return db.broadcast_recipients(active_only=False)
    return db.broadcast_recipients()


class BroadcastJob:
    """
    وضعیتِ یه پیام همگانیِ در حال اجرا یا تمام‌شده: قابل لغو، و در آخر
    گزارشِ (فرستاده/بلاک‌شده/ناموفق) می‌ده.
    """

    def __init__(self, admin_id, audience, from_chat_id, message_id, total):
        self.admin_id = int(admin_id)
        self.audience = audience
        self.from_chat_id = from_chat_id
        self.message_id = message_id
        self.total = int(total)
        self.sent = 0
        self.failed = 0
        self.blocked = 0
        self.cancelled = False
        self.task = None
        self._cancel = asyncio.Event()

    def cancel(self):
        self._cancel.set()

    @property
    def cancel_requested(self):
        return self._cancel.is_set()

    @property
    def done(self):
        return self.task is not None and self.task.done()

    @property
    def processed(self):
        return self.sent + self.failed + self.blocked


async def run(bot, db, job, recipient_ids):
    """
    حلقه‌ی اصلیِ ارسال. جدا از بقیه‌ی هندلرها اجرا می‌شه (به‌عنوان یه
    asyncio task که خودِ صداکننده می‌سازه)، پس بقیه‌ی ربات موقعِ فرستادنِ
    چند صد پیام هنگ نمی‌کنه.
    """
    delay = 1.0 / RATE_PER_SECOND
    for user_id in recipient_ids:
        if job.cancel_requested:
            job.cancelled = True
            break
        await _send_one(bot, db, job, user_id)
        await asyncio.sleep(delay)
    return job


async def _send_one(bot, db, job, user_id, retried=False):
    try:
        await bot.copy_message(chat_id=user_id, from_chat_id=job.from_chat_id,
                               message_id=job.message_id)
        job.sent += 1
    except Forbidden:
        # کاربر ربات رو بلاک کرده (یا هیچ‌وقت استارت نزده) -- تا دوباره
        # خودش با ربات حرف نزنه، از گیرنده‌های بعدی هم حذفه.
        db.mark_bot_blocked(user_id)
        job.blocked += 1
    except RetryAfter as e:
        # سقفِ نرخِ تلگرام -- هر چقدر گفته صبر می‌کنیم، بعد *همین* گیرنده
        # رو یه بار دیگه امتحان می‌کنیم. نادیده گرفتنش یعنی کل ربات
        # موقتاً مسدود بشه، نه فقط این پیام همگانی.
        await asyncio.sleep(e.retry_after + 0.1)
        if not retried:
            await _send_one(bot, db, job, user_id, retried=True)
        else:
            job.failed += 1
    except TelegramError as e:
        logging_setup.log_debug(f"broadcast to {user_id} failed: {e}")
        job.failed += 1
    except Exception:
        logging_setup.log_exception(f"broadcast to {user_id}")
        job.failed += 1
