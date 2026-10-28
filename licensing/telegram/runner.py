"""
اجرای هم‌زمان چند ربات تلگرام توی یه پروسه.

ربات فروش یکیه، ولی هر مشتری می‌تونه ربات شخصی خودش رو داشته باشه. همه‌شون
توی همون حلقه‌ی asyncio اجرا می‌شن — یعنی صدها ربات هم چند مگابایت بیشتر
مصرف نمی‌کنن، برخلاف حالتی که هرکدوم پروسه‌ی جدا داشته باشن.

## چرا هر ربات مشتری «جدا» مدیریت می‌شه

توکن یه مشتری ممکنه باطل بشه (از BotFather revoke کنه)، یا تلگرام
موقتاً محدودش کنه. اگه همه توی یه Application بودن، یه توکن خراب کل
polling رو می‌خوابوند. پس هر کدوم Application خودش رو داره و شکستش فقط
خودش رو زمین می‌زنه — وضعیتش هم توی دیتابیس ثبت می‌شه تا ادمین ببینه.

## نکته‌ی مهم درباره‌ی polling

هر ربات polling مستقل خودش رو داره. تلگرام اجازه نمی‌ده دو پروسه هم‌زمان
یه توکن رو poll کنن، پس اگه یه توکن قبلاً جای دیگه‌ای در حال اجرا باشه،
استارتش با خطا برمی‌گرده و همون خطا به مشتری نشون داده می‌شه.
"""

import asyncio

from telegram import Bot
from telegram.error import Forbidden, InvalidToken, TelegramError

from core import logging_setup
from licensing import config
from licensing import i18n
from licensing import telegram as telegram_layer
from licensing.telegram import customer_bot

#: این خطاها یعنی توکن دیگه هیچ‌وقت کار نمی‌کنه (باطل شده یا ربات بلاک/حذف
#: شده) -- نه یه مشکل موقتِ شبکه. فقط این‌ها باعث "dead" می‌شن؛ NetworkError،
#: TimedOut، RetryAfter و بقیه باید دوباره امتحان بشن، نه برای همیشه خاموش.
_DEAD_TOKEN_ERRORS = (InvalidToken, Forbidden)


def _is_dead_token_error(exc):
    return isinstance(exc, _DEAD_TOKEN_ERRORS)


class BotRunner:
    """
    مدیریت ربات‌های شخصی مشتری‌ها. ربات فروش خودش جدا و توسط
    license_server.py اجرا می‌شه.
    """

    def __init__(self, db, supervisor=None):
        self.db = db
        self.supervisor = supervisor
        self._apps = {}       # owner_id -> Application
        self._lock = asyncio.Lock()
        # ربات فروش، برای خبردادن به مالکِ توکنی که دیگه کار نمی‌کنه --
        # چون خودِ ربات شخصیِ اون آدم دیگه جواب نمی‌ده. با set_sales_bot
        # ست می‌شه (بعد از ساختنِ Application ربات فروش).
        self._sales_bot = None

    # ------------------------------------------------------------ اعتبار

    async def validate_token(self, token):
        """
        (ok, detail). detail یوزرنیم ربات است اگه ok، وگرنه متن خطا.
        عمداً فقط getMe صدا زده می‌شه: سبکه و بدون اینکه polling شروع بشه
        می‌گه توکن معتبره یا نه.
        """
        token = (token or "").strip()
        if ":" not in token or len(token) < 20:
            return False, i18n.t("personal_bot_token_shape")
        try:
            bot = Bot(token, **telegram_layer.request_kwargs())
            me = await bot.get_me()
        except TelegramError as e:
            return False, str(e)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        return True, me.username or str(me.id)

    # ------------------------------------------------------------ اجرا

    def set_sales_bot(self, bot):
        """Bot ربات فروش. license_server.py این رو بعد از ساختنِ Application
        ربات فروش صدا می‌زنه، قبل از start_all."""
        self._sales_bot = bot

    async def start_customer_bot(self, owner_id, token):
        """
        (started, error_text, dead).

        dead=True یعنی خطا InvalidToken/Forbidden بود -- توکن باطل یا
        لغوشده، نه یه مشکلِ موقتِ شبکه. صداکننده (start_all یا
        personal_bot.py) باید این حالت رو "dead" ثبت کنه، نه "failed"
        (که با هر ری‌استارت دوباره امتحان می‌شه).
        """
        owner_id = int(owner_id)
        async with self._lock:
            await self._stop_unlocked(owner_id)

            application = customer_bot.build_application(
                token, owner_id, self.db, self.supervisor, runner=self)
            try:
                await application.initialize()
                await application.start()
                await application.updater.start_polling(
                    drop_pending_updates=True, timeout=config.poll_timeout())
            except Exception as e:
                logging_setup.log_exception(f"starting customer bot for {owner_id}")
                try:
                    await application.shutdown()
                except Exception:
                    pass
                return False, f"{type(e).__name__}: {e}", _is_dead_token_error(e)

            self._apps[owner_id] = application
            return True, "", False

    async def mark_dead(self, owner_id, reason=""):
        """
        توکنِ این مشتری دیگه کار نمی‌کنه (باطل/لغوشده). اپش متوقف می‌شه،
        وضعیت توی دیتابیس دائمی ثبت می‌شه -- start_all بعد از این هیچ‌وقت
        دوباره امتحانش نمی‌کنه، حتی بعد از ری‌استارتِ کامل پلتفرم -- و
        صاحبش، از طریق ربات فروش (چون ربات خودش دیگه جواب نمی‌ده)، *فقط
        یک‌بار* خبردار می‌شه.

        از دلِ هندلر خطای خودِ همون اپلیکیشن هم صدا زده می‌شه (customer_bot.
        on_error) -- اونجا با asyncio.create_task فراخوانی می‌شه تا
        stop-کردنِ اپ از داخلِ تسکِ پردازشِ خودش قفل نکنه.
        """
        owner_id = int(owner_id)
        async with self._lock:
            await self._stop_unlocked(owner_id)

        row = self.db.get_user(owner_id)
        if row is None or not row["personal_bot_token"]:
            return
        already_dead = row["personal_bot_status"] == "dead"
        self.db.set_personal_bot(owner_id, row["personal_bot_token"],
                                 row["personal_bot_username"], status="dead")
        self.db.log_event("personal_bot_dead", user_id=owner_id, detail={"reason": reason})
        if already_dead:
            return
        await self._notify_owner_dead(owner_id)

    async def _notify_owner_dead(self, owner_id):
        if self._sales_bot is None:
            return
        try:
            from licensing.telegram import keyboards as kb

            row = self.db.get_user(owner_id)
            i18n.set_language(row["lang"] if row else None)
            await self._sales_bot.send_message(
                owner_id, i18n.t("personal_bot_token_dead"),
                parse_mode="HTML", reply_markup=kb.personal_bot(True))
        except TelegramError as e:
            logging_setup.log_debug(f"telling {owner_id} about a dead personal bot token failed: {e}")
        except Exception:
            logging_setup.log_exception(f"notifying {owner_id} about a dead personal bot token")

    async def stop_customer_bot(self, owner_id):
        async with self._lock:
            return await self._stop_unlocked(int(owner_id))

    async def _stop_unlocked(self, owner_id):
        application = self._apps.pop(owner_id, None)
        if application is None:
            return False
        try:
            if application.updater and application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()
        except Exception:
            logging_setup.log_exception(f"stopping customer bot for {owner_id}")
        return True

    async def start_all(self):
        """
        همه‌ی ربات‌های شخصیِ ثبت‌شده رو بالا می‌آره. موقع استارتِ سرور صدا
        زده می‌شه. ربات‌هایی که قبلاً "dead" علامت خوردن (توکن باطل/لغوشده)
        اصلاً امتحان نمی‌شن -- دقیقاً همون چیزی که E11 می‌خواد: یه توکنِ
        مرده حتی بعد از ری‌استارتِ کامل پلتفرم دوباره retry نمی‌شه.

        بقیه‌ی شکست‌ها (مشکل موقتِ شبکه و مثل آن) توی دیتابیس failed
        علامت می‌خورن و به ادمین گزارش می‌شن (نه اینکه بی‌صدا رد بشن) --
        این‌ها دفعه‌ی بعد دوباره امتحان می‌شن.
        """
        started, failed = 0, []
        for row in self.db.personal_bots():
            if row["personal_bot_status"] == "dead":
                continue
            token = row["personal_bot_token"]
            if not token:
                continue
            ok, error, dead = await self.start_customer_bot(int(row["telegram_id"]), token)
            if ok:
                started += 1
                self.db.set_personal_bot(int(row["telegram_id"]), token,
                                         row["personal_bot_username"], status="running")
            elif dead:
                await self.mark_dead(int(row["telegram_id"]), reason=error)
                failed.append((int(row["telegram_id"]), error))
            else:
                failed.append((int(row["telegram_id"]), error))
                self.db.set_personal_bot(int(row["telegram_id"]), token,
                                         row["personal_bot_username"], status="failed")
        if started or failed:
            logging_setup.log_debug(
                f"customer bots: {started} started, {len(failed)} failed")
        return started, failed

    async def stop_all(self):
        async with self._lock:
            for owner_id in list(self._apps):
                await self._stop_unlocked(owner_id)

    def running_owners(self):
        return sorted(self._apps)

    def status(self):
        return [
            {"owner_id": owner_id, "running": app.running}
            for owner_id, app in sorted(self._apps.items())
        ]
