"""
هر فایل .py توی پوشه‌ی commands/ می‌تونه یک یا چند دستور جدید به ربات
اضافه کنه، بدون این‌که لازم باشه bot.py رو دست بزنی. با دستور
"rs commands" هم می‌شه بدون ری‌استارت کامل، فایل‌های جدید/تغییرکرده رو
دوباره لود کرد.

فرمت هر فایل توی commands/:
    NAME = "mycmd"                    # یا یه tuple: ("mycmd", "alias2") برای چند اسم هم‌زمان
    REQUIRED_ROLE = "normal"          # اختیاری؛ یکی از "normal" (پیش‌فرض)،
                                      # "channel_operator"، "admin_bot"، "admin_server"
                                      # (توضیح کامل توی core/roles.py)
    USAGE = "mycmd <args>"            # اختیاری، برای help/ah

    def run(ctx):
        # ctx شامل: uid, nickname, username, raw, args, cmd
        # ctx["bot"] هم دسترسی به اشیای اصلی ربات می‌ده: bot.t, bot.player,
        # bot.cfg, bot.i18n, bot.load_and_play, بغیره (از core.bot_context)
        ...

برای سازگاری با فایل‌های قدیمی/بیرونی: اگه REQUIRED_ROLE نباشه ولی
ADMIN_ONLY = True باشه، همون معادلِ "admin_server" در نظر گرفته می‌شه.
"""

import importlib.util
import inspect
import os

from core import logging_setup
from core.paths import resource_dir

# resource_dir (نه get_base_dir): بعد از بیلد با PyInstaller، پوشه‌ی
# commands/ داخل باندل باز می‌شه، ولی نسخه‌ی کنار فایل اجرایی -- اگه کاربر
# گذاشته باشه -- اولویت داره تا بشه بدون بیلد مجدد دستور اضافه/عوض کرد.
DEFAULT_COMMANDS_DIR = resource_dir("commands")

_VALID_ROLES = ("normal", "channel_operator", "admin_bot", "admin_server")

class CommandManager:
    def __init__(self, folder=None):
        # مسیر مطلق، نه نسبی (مثل ServiceManager): اجرا از پوشه‌ی دیگه نباید
        # باعث بشه ربات هیچ دستوری نداشته باشه.
        self.folder = folder or DEFAULT_COMMANDS_DIR
        if not os.path.exists(self.folder):
            os.makedirs(self.folder)

    def load_commands(self):
        """
        {name: {"handler": func, "role": str, "usage": str}} برمی‌گردونه
        برای هر دستوری که توی فایل‌های commands/ پیدا کنه.
        """
        result = {}
        if not os.path.isdir(self.folder):
            return result

        for filename in sorted(os.listdir(self.folder)):
            if not filename.endswith(".py") or filename.startswith("_"):
                continue

            module_name = f"plugin_cmd_{filename[:-3]}"
            path = os.path.join(self.folder, filename)

            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                run_func = getattr(module, "run", None)
                if not callable(run_func):
                    logging_setup.log_warning(f"'{filename}' has no callable run(ctx), skipping.", context="loading commands")
                    continue

                names = getattr(module, "NAME", None)
                if not names:
                    logging_setup.log_warning(f"'{filename}' has no NAME, skipping.", context="loading commands")
                    continue
                if isinstance(names, str):
                    names = (names,)

                role = getattr(module, "REQUIRED_ROLE", None)
                if role not in _VALID_ROLES:
                    if role is not None:
                        logging_setup.log_warning(
                            f"'{filename}' has an invalid REQUIRED_ROLE ({role!r}); falling back.",
                            context="loading commands",
                        )
                    role = "admin_server" if getattr(module, "ADMIN_ONLY", False) else "normal"

                entry = {
                    "handler": run_func,
                    "role": role,
                    "usage": getattr(module, "USAGE", None),
                }
                for name in names:
                    result[name.lower()] = entry
            except Exception:
                logging_setup.log_exception(f"loading command file '{filename}'")
                continue

        return result
