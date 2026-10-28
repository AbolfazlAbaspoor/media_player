"""
ویزارد ساخت و ویرایش ربات تیم‌تاک -- مشترک بین ربات فروش و ربات شخصی مشتری.

## چرا یه جا

قبلاً ویزارد فقط توی ربات فروش بود و ربات شخصیِ مشتری فقط می‌تونست ربات‌ها
رو ببینه و روشن/خاموش کنه. کپی‌کردنِ ویزارد توی ربات شخصی یعنی دو نسخه
از اعتبارسنجی (عدد بودن پورت، سقف اپراتورها، پاک‌کردنِ پیامِ پسورد) که
دیر یا زود یکی‌شون عقب می‌موند.

اینجا منطقِ خالص هست -- بدون هیچ وابستگی به یه ربات خاص -- و هر ربات فقط
پیام‌ها و دکمه‌ها رو خودش می‌فرسته. دکمه‌ها با یه `prefix` ساخته می‌شن
چون هر ربات قالب callback خودش رو داره.
"""

import sqlite3

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from core import logging_setup
from licensing import i18n
from licensing import licenses
from licensing import provisioning
from licensing.db import json_list

# هر چیزی که اینجا نباشه *پسورد واقعی* حساب می‌شه، پس لیست عمداً کوتاه و
# صریحه («no» هست، چون احتمال جواب‌دادن با «no» خیلی بیشتر از پسوردبودنشه).
NO_PASSWORD_MARKERS = {
    "-", "--", "no", "none", "null", "empty", "nothing", "skip",
    "ندارم", "نداره", "ندارد", "نداریم", "خالی", "هیچی", "هیچ", "بدون",
}

# سقفِ فنیِ تعداد اپراتور (نه سهمیه‌ی خریداری‌شده -- از تصمیم ۲۰۲۶-۰۹-۱۶
# اپراتورها دیگه قیمت/سهمیه ندارن و برای هر ربات نامحدودن). این عدد فقط
# جلوی یه لیست عملاً بی‌معنی (یا اشتباه تایپی با کاماهای زیاد) رو می‌گیره.
MAX_OPERATORS = 50

# (فیلد، کلیدِ پرسش، جوابِ پیش‌فرض، کلیدِ متنِ دکمه). پیش‌فرض None یعنی جواب
# اجباری و بدون دکمه -- آدرس سرور و یوزر/پسِ ربات رو نمی‌شه حدس زد.
STEPS = [
    ("host", "setup_ask_host", None, None),
    ("port", "setup_ask_port", "10333", "btn_setup_default"),
    ("nickname", "setup_ask_nickname", "Audio Player Bot", "btn_setup_default"),
    ("username", "setup_ask_username", None, None),
    ("password", "setup_ask_password", None, None),
    ("channel_id", "setup_ask_channel", "1", "btn_setup_default"),
    ("channel_password", "setup_ask_channel_password", "-", "btn_setup_no_password"),
    ("operators", "setup_ask_operators", "-", "btn_setup_no_operators"),
]


class WizardError(Exception):
    """پیامِ قابل‌نمایش به کاربر."""


# ------------------------------------------------------------------ وضعیت

def new_state(license_id):
    return {"license_id": int(license_id), "step": 0}


def state_from_instance(instance):
    return {
        "license_id": int(instance["license_id"]),
        "instance_id": int(instance["id"]),
        "step": 0,
        "host": instance["tt_host"],
        "port": int(instance["tt_port"]),
        "nickname": instance["tt_nickname"] or "",
        "username": instance["tt_username"] or "",
        "password": instance["tt_password"] or "",
        "channel_id": int(instance["tt_channel_id"] or 1),
        "channel_password": instance["tt_channel_password"] or "",
        "operators": json_list(instance["operators"]),
    }


def field_at(index):
    return STEPS[index][0]


def prompt(index):
    return i18n.t(STEPS[index][1])


def default_for(index, state=None):
    """
    جوابِ پیش‌فرضِ این مرحله، یا None اگه اجباریه. موقع *ویرایش* پیش‌فرض همون
    مقدار فعلیه، پس کاربر فقط چیزی رو تایپ می‌کنه که می‌خواد عوض کنه.
    """
    field, _prompt_key, default, _button_key = STEPS[index]
    if state and state.get("instance_id") and field in state:
        current = state[field]
        if field == "operators":
            return ", ".join(current) if current else "-"
        return str(current) if current not in (None, "") else "-"
    return default


def step_keyboard(index, state, prefix):
    field, _prompt_key, _default, button_key = STEPS[index]
    value = default_for(index, state)
    if value is None:
        return None
    label_key = button_key or "btn_setup_default"
    if state and state.get("instance_id") and value != "-":
        label_key = "btn_setup_keep"
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        i18n.t(label_key, value=value), callback_data=f"{prefix}def:{index}")]])


async def answer_step(update, state, text, prefix, cancel_callback):
    """
    جوابِ متنیِ یه مرحله‌ی ویزارد رو پردازش می‌کنه و مرحله‌ی بعد (یا مرور
    نهایی) رو می‌فرسته. مشترک بین ربات فروش و ربات شخصیِ مشتری؛ فقط
    prefixِ callbackها و دکمه‌ی انصراف فرق داره. True یعنی ویزارد تموم شد
    (فراخوان باید awaiting رو پاک کنه).
    """
    from licensing.telegram import texts as T

    message = update.effective_message
    was_password = asks_for_password(state)
    advanced, error_key, warning = answer(state, text)

    if was_password:
        # پسورد نباید توی تاریخچه‌ی چت بمونه.
        try:
            await message.delete()
        except TelegramError:
            pass
    if not advanced:
        await message.reply_text(i18n.t(error_key))
        return False
    if warning is not None:
        await message.reply_text(T.setup_operators_cap(warning), parse_mode=ParseMode.HTML)

    if not is_finished(state):
        index = int(state["step"])
        await update.effective_chat.send_message(
            prompt(index), parse_mode=ParseMode.HTML,
            reply_markup=step_keyboard(index, state, prefix))
        return False

    await update.effective_chat.send_message(
        T.setup_review(state), parse_mode=ParseMode.HTML,
        reply_markup=review_keyboard(int(state["license_id"]), prefix, cancel_callback))
    return True


def review_keyboard(license_id, prefix, cancel_callback):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(i18n.t("btn_setup_confirm"), callback_data=f"{prefix}apply:{license_id}")],
        [InlineKeyboardButton(i18n.t("btn_setup_restart"), callback_data=f"{prefix}start:{license_id}")],
        [InlineKeyboardButton(i18n.t("btn_cancel"), callback_data=cancel_callback)],
    ])


def answer(state, text):
    """
    جوابِ مرحله‌ی فعلی رو اعتبارسنجی و ذخیره می‌کنه.

    خروجی: (advanced, error_key, warning) --
      * advanced=False یعنی همین مرحله دوباره پرسیده بشه و error_key پیامشه؛
      * warning یه هشدار اضافه (اپراتورهای بیشتر از سقفِ فنیِ MAX_OPERATORS
        که بریده شدن -- این یه سهمیه‌ی خریداری‌شده نیست، هر لایسنسی همین
        سقف رو داره).
    """
    index = int(state["step"])
    field = field_at(index)
    warning = None
    text = "" if text is None else str(text)

    if field == "port":
        try:
            state["port"] = int(text)
        except ValueError:
            return False, "setup_port_must_be_number", None
    elif field == "channel_id":
        try:
            state["channel_id"] = int(text)
        except ValueError:
            return False, "setup_channel_must_be_number", None
    elif field == "channel_password":
        state["channel_password"] = "" if text.strip().lower() in NO_PASSWORD_MARKERS else text
    elif field == "operators":
        if text.strip().lower() in NO_PASSWORD_MARKERS:
            names = []
        else:
            names = [n.strip() for n in text.replace("،", ",").split(",") if n.strip()]
        if len(names) > MAX_OPERATORS:
            names = names[:MAX_OPERATORS]
            warning = MAX_OPERATORS
        state["operators"] = names
    elif field == "password":
        state["password"] = text
    else:
        state[field] = text.strip()

    state["step"] = index + 1
    return True, None, warning


def is_finished(state):
    return int(state.get("step", 0)) >= len(STEPS)


def asks_for_password(state):
    """مرحله‌ی فعلی پسورد می‌خواد؟ -- تا صداکننده پیامِ جواب رو از چت پاک کنه."""
    index = int(state.get("step", 0))
    return 0 <= index < len(STEPS) and field_at(index) == "password"


# ---------------------------------------------------------------- اجرا

def check_can_add(db, license_row):
    """WizardError اگه برای این لایسنس نمی‌شه ربات جدید ساخت."""
    if license_row is None:
        raise WizardError(i18n.t("license_not_yours"))
    if not licenses.is_valid(license_row):
        raise WizardError(i18n.t("license_inactive"))
    if len(db.instances_by_license(int(license_row["id"]))) >= int(license_row["max_bots"]):
        raise WizardError("quota")


def create(db, license_row, state, supervisor=None):
    """
    ربات جدید رو می‌سازه، provision می‌کنه و روشنش می‌کنه. خروجی: ردیف نمونه.

    اگه provision شکست بخوره ردیفش پاک می‌شه -- وگرنه یه ربات نیمه‌کاره سهمیه
    رو مصرف می‌کرد بدون اینکه هیچ‌وقت کار کنه.
    """
    from core import config_defaults

    check_can_add(db, license_row)
    license_id = int(license_row["id"])
    port = int(state.get("port", 10333))

    instance = None
    taken = set()
    for _attempt in range(5):
        slug = provisioning.free_instance_slug(db, license_row["key"], taken)
        try:
            instance = db.create_instance(
                license_id=license_id,
                slug=slug,
                tt_host=state["host"],
                tt_port=port,
                audio_line=slug,
                group_name=config_defaults.server_folder_name(state["host"], port),
                bot_name=config_defaults.safe_bot_folder_name(slug),
                **_instance_fields(state),
            )
            break
        except sqlite3.IntegrityError:
            # درخواست هم‌زمانِ دیگه‌ای همین slug رو همین لحظه گرفت؛ بعدی رو امتحان کن.
            taken.add(slug)
    if instance is None:
        raise RuntimeError("could not allocate a free instance slug")
    try:
        provisioning.provision_instance(db, license_row, instance)
    except Exception:
        db.delete_instance(int(instance["id"]))
        raise

    instance = db.get_instance(int(instance["id"]))
    if supervisor is not None:
        try:
            supervisor.start_instance(instance)
        except Exception:
            logging_setup.log_exception("starting provisioned instance")
    return instance


def _instance_fields(state):
    """ستون‌های ربات که از پاسخ‌های ویزارد میان (مشترکِ create و update)."""
    return dict(
        tt_nickname=state.get("nickname") or "Audio Player Bot",
        tt_username=state.get("username") or "",
        tt_password=state.get("password") or "",
        tt_channel_id=int(state.get("channel_id", 1)),
        tt_channel_password=state.get("channel_password") or "",
        operators=state.get("operators") or [],
    )


def update(db, license_row, state, supervisor=None):
    """
    مشخصات یه ربات موجود رو عوض می‌کنه و ری‌استارتش می‌کنه. slug و لاین صدا
    دست‌نخورده می‌مونن -- عوض‌کردنشون یعنی یه ربات جدید.
    """
    from core import config_defaults

    instance_id = int(state["instance_id"])
    instance = db.get_instance(instance_id)
    if instance is None or int(instance["license_id"]) != int(license_row["id"]):
        raise WizardError(i18n.t("bot_not_found"))

    host = state["host"]
    port = int(state.get("port", 10333))
    db.update_instance(
        instance_id,
        tt_host=host,
        tt_port=port,
        group_name=config_defaults.server_folder_name(host, port),
        **_instance_fields(state),
    )
    instance = db.get_instance(instance_id)

    # سرور عوض شده یعنی پوشه‌ی دیتا هم عوض می‌شه؛ قبل از نوشتن کانفیگ جدید
    # باید خاموش باشه وگرنه با کانفیگ قدیمی ادامه می‌ده.
    if supervisor is not None:
        try:
            supervisor.stop(instance["slug"])
        except Exception:
            logging_setup.log_exception("stopping instance before edit")

    provisioning.provision_instance(db, license_row, instance)
    instance = db.get_instance(instance_id)
    if supervisor is not None:
        try:
            supervisor.start_instance(instance)
        except Exception:
            logging_setup.log_exception("starting instance after edit")
    return instance
