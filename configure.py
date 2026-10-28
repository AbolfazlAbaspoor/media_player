"""
ویزارد راه‌اندازیِ کل پروژه. یه بار بعد از clone اجراش کن:

    python configure.py                      # تعاملی، قدم‌به‌قدم
    python configure.py --non-interactive --sales-token ... --admin-ids ... --card-number ...

کارهایی که می‌کنه (هر قدم جدا و قابل‌رد‌کردنه، و هر قدم اول می‌پرسه):

    ۱. چک پایتون، و اجرای install.py برای چیزهایی که نصب نیست
    ۲. پروکسیِ تلگرام (اول)، بعد توکن ربات فروش با getMe
    ۳. آیدی ادمین‌ها، کارت/پرداخت و بقیه‌ی کلیدهای اجباریِ کانفیگ
    ۴. اختیاری: Cloudflare (لایسنس اجاره‌ای)، پرداخت کریپتو
    ۵. اختیاری: اولین ربات تیم‌تاک و لایسنس مالک
    ۶. نوشتن کانفیگ، خلاصه (با ماسکِ رازها) و `license_server.py --check`

idempotent: اجرای دوباره مقدارهای فعلی رو پیش‌فرض نشون می‌ده (رازها
ماسک‌شده) و فقط چیزی رو که تو عوض کنی می‌نویسه. رازها هیچ‌وقت کامل چاپ
نمی‌شن.

این فایل عمداً نازکه: منطق کانفیگ (نوشتن، ماسک، اعتبارسنجیِ ورودی) توی
licensing/config.py و کارِ نصب توی install.py می‌مونه؛ اینجا فقط
پرسیدن و به‌هم‌وصل‌کردنه.

زبان: پرامپت‌ها دوزبانه‌ان (اول انگلیسی، بعد فارسی)، بدون رنگ و
ASCII-art تا با صفحه‌خوان راحت خونده بشن.
"""

import argparse
import contextlib
import getpass
import importlib.util
import io
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from core import paths  # noqa: E402

paths.force_utf8_console()

from core import config_defaults  # noqa: E402
from licensing import config  # noqa: E402

#: پروژه از سینتکس `X | None` توی امضای تابع‌ها استفاده می‌کنه (core/proxy_state.py)
MIN_PYTHON = (3, 10)

#: ماژول‌هایی که بدونشون پلتفرم لایسنس بالا نمی‌آد؛ نبودشون = install.py
REQUIRED_MODULES = ("telegram", "cryptography")

#: کامپوننت‌های نیتیوِ install.py. دومی: پیش‌فرضِ سؤال (tesseract اختیاریه).
NATIVE_COMPONENTS = (
    ("teamtalk", True),
    ("ffmpeg", True),
    ("libmpv", True),
    ("pulseaudio_utils", True),
    ("js_runtime", True),
    ("tesseract", False),
)

#: قابلیت قدیمیِ self-host که بازنشسته شده؛ توی «تنظیمات پیشرفته» نمی‌پرسیمش.
_RETIRED_PREFIXES = ("selfhost_", "license_api_")

#: کلید -> (اسم گزینه‌ی خط فرمان). متغیر محیطی از config.env_name می‌آد،
#: و برای هر کلیدی CONFIGURE_<KEY> هم کار می‌کنه.
NAMED_FLAGS = {
    "sales_bot_token": "--sales-token",
    "proxy_url": "--proxy-url",
    "admin_ids": "--admin-ids",
    "card_number": "--card-number",
    "card_holder": "--card-holder",
    "card_bank": "--card-bank",
    "support_username": "--support-username",
    "cloudflare_account_id": "--cf-account-id",
    "cloudflare_kv_namespace": "--cf-kv-namespace",
    "cloudflare_api_token": "--cf-api-token",
}

CLOUDFLARE_KEYS = ("cloudflare_account_id", "cloudflare_kv_namespace", "cloudflare_api_token")

SUMMARY_KEYS = ("sales_bot_token", "proxy_url", "admin_ids", "card_number", "card_holder",
                "card_bank", "support_username") + CLOUDFLARE_KEYS

BOT_FLAGS = ("host", "port", "name", "nickname", "username", "password",
             "channel_id", "channel_password")


class WizardAbort(Exception):
    """ورودی تموم شد یا کاربر خارج شد؛ چیزی که نوشته نشده، نوشته نمی‌شه."""


# ------------------------------------------------------------- ورودی/خروجی

class Prompter:
    """
    تنها جایی که input/print رو لمس می‌کنه، تا تست‌ها با ورودیِ ساختگی اجراش
    کنن. پرامپت‌ها ساده‌ان: یه خط سؤال، جواب توی همون خط.
    """

    def __init__(self, input_fn=input, secret_fn=getpass.getpass, out=print):
        self._input = input_fn
        self._secret = secret_fn
        self._out = out

    def say(self, en="", fa=None):
        self._out(en)
        if fa:
            self._out(fa)

    def ask(self, label, shown="", secret=False):
        suffix = f" [{shown}]" if shown else ""
        prompt = f"{label}{suffix}: "
        try:
            answer = (self._secret if secret else self._input)(prompt)
        except (EOFError, KeyboardInterrupt) as e:
            raise WizardAbort("input ended") from e
        return (answer or "").strip()

    def confirm(self, label, default=False):
        hint = "Y/n" if default else "y/N"
        while True:
            answer = self.ask(f"{label} ({hint})").lower()
            if not answer:
                return default
            if answer in ("y", "yes", "بله", "آره"):
                return True
            if answer in ("n", "no", "نه", "خیر"):
                return False
            self.say("Please answer y or n. / لطفاً y یا n بنویس.")

    def choose(self, label, options, default):
        """options: [(کلید، توضیح)]. حرف اول کلیدها یکتا فرض می‌شه."""
        for key, text in options:
            self.say(f"  {key}) {text}")
        valid = {key for key, _ in options}
        while True:
            answer = self.ask(label, default).lower() or default
            if answer in valid:
                return answer
            self.say(f"Choose one of: {', '.join(sorted(valid))} / یکی از این‌ها: {', '.join(sorted(valid))}")


def _both(en, fa):
    return f"{en} / {fa}"


# ------------------------------------------------------------- اعتبارسنجی ورودی
# هر parse_* (مقدار، خطا) برمی‌گردونه؛ دقیقاً یکی‌شون None است.

def parse_text(raw):
    return raw.strip(), None


def parse_token(raw):
    import re
    token = raw.strip()
    if not re.fullmatch(r"\d{5,}:[A-Za-z0-9_-]{30,}", token):
        return None, _both("That does not look like a bot token (expected 123456789:AA...; get one from @BotFather).",
                           "شکلش به توکن ربات نمی‌خوره (مثل 123456789:AA... ؛ از @BotFather بگیر).")
    return token, None


def parse_proxy(raw):
    from core import proxy_state, xray_proxy
    text = raw.strip()
    if xray_proxy.is_share_link(text):
        return None, _both("The sales bot needs an http:// or socks5:// proxy; vless/vmess links are not supported here.",
                           "ربات فروش پروکسی http:// یا socks5:// می‌خواد؛ لینک vless/vmess اینجا پشتیبانی نمی‌شه.")
    url, error = proxy_state.validate(text)
    if error:
        return None, error
    if url.startswith("socks") and importlib.util.find_spec("socksio") is None:
        return None, _both('socks proxies need an extra package: pip install "python-telegram-bot[socks]"',
                           'پروکسی socks یه پکیج اضافه می‌خواد: pip install "python-telegram-bot[socks]"')
    return url, None


def parse_admin_ids(raw):
    ids = config.parse_admin_ids(raw)
    if not ids:
        return None, _both("Enter at least one numeric Telegram id (@userinfobot shows yours).",
                           "حداقل یه آیدی عددی تلگرام بنویس (@userinfobot آیدی تو رو نشون می‌ده).")
    return ids, None


def parse_card(raw):
    card = config.normalize_card_number(raw)
    if card is None:
        return None, _both("A card number has 12 to 19 digits.", "شماره کارت ۱۲ تا ۱۹ رقمه.")
    return card, None


def parse_by_default(default):
    """مقدار رو هم‌نوعِ پیش‌فرضِ کلید درمی‌آره (bool/int/float/لیست/متن)."""
    def parse(raw):
        text = raw.strip()
        try:
            if isinstance(default, bool):
                lowered = text.lower()
                if lowered in ("1", "true", "yes", "y", "on"):
                    return True, None
                if lowered in ("0", "false", "no", "n", "off"):
                    return False, None
                raise ValueError
            if isinstance(default, int):
                return int(text), None
            if isinstance(default, float):
                return float(text), None
            if isinstance(default, list):
                items = [part.strip() for part in text.replace("،", ",").split(",") if part.strip()]
                if default and all(isinstance(item, int) for item in default):
                    return [int(item) for item in items], None
                return items, None
        except ValueError:
            return None, _both("That value has the wrong type.", "نوع مقدار درست نیست.")
        return text, None
    return parse


# ------------------------------------------------------------- شبکه

def _http_get_json(url, proxy=None, timeout=20):
    """
    تنها تابعی که به شبکه می‌ره. پروکسی *صریح* می‌گیره و هیچ‌وقت پروکسیِ
    سیستم/محیط رو نمی‌خونه (trust_env=False): روی شبکه‌ای که تلگرام فیلتره،
    «کار کرد چون پروکسیِ سیستم بود» یعنی سرور بعداً بدون اون نمی‌تونه.
    """
    import httpx
    try:
        client = httpx.Client(proxy=proxy or None, trust_env=False, timeout=timeout)
    except TypeError:  # httpx قدیمی‌تر از 0.26: اسمش proxies بود
        client = httpx.Client(proxies=proxy or None, trust_env=False, timeout=timeout)
    with client:
        return client.get(url).json()


def probe_bot(token, proxy=None, timeout=20):
    """(ok, detail) -- getMe روی توکن، از مسیر پروکسیِ صریح. توکن هیچ‌وقت توی detail نمی‌آد."""
    try:
        data = _http_get_json(f"https://api.telegram.org/bot{token}/getMe", proxy, timeout)
    except Exception as e:
        detail = f"{type(e).__name__}: {e}".replace(token, "***")
        return False, detail[:200]
    if isinstance(data, dict) and data.get("ok"):
        result = data.get("result") or {}
        return True, "@" + str(result.get("username") or result.get("id"))
    description = (data or {}).get("description", "unknown error") if isinstance(data, dict) else "bad response"
    return False, str(description).replace(token, "***")[:200]


@contextlib.contextmanager
def _temp_env(values):
    """متغیرهای محیطی رو موقتاً می‌ذاره (همون ترفندِ manage.py cf-token برای تست قبل از ذخیره)."""
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


# ------------------------------------------------------------- ویزارد

class Wizard:

    def __init__(self, args, prompter, data_dir=None):
        self.args = args
        self.p = prompter
        self.interactive = not args.non_interactive
        self.data_dir = data_dir or os.path.join(paths.get_base_dir(), "data")
        self.pending = {}     # تغییرهایی که هنوز روی دیسک نرفتن
        self.written = []     # کلیدهایی که نوشته شدن
        self.errors = []      # مشکل‌هایی که کد خروج رو غیرصفر می‌کنن
        self.warnings = []
        self.created = []     # فایل‌های تازه‌ساخته
        self.required = set(config.missing_required_keys())

    # -- خوندن مقدار --------------------------------------------------

    def current(self, key):
        """مقدارِ *فایل* (یا پیش‌فرض). env عمداً نه: نباید ناخواسته بریزیمش توی فایل."""
        value = config.get_path(config.file_values(), key, None)
        return config.default_for(key) if value is None else value

    def effective(self, key):
        return self.pending[key] if key in self.pending else self.current(key)

    def in_use(self, key):
        """مقداری که ربات واقعاً می‌بینه: تغییرِ در انتظار، وگرنه env/فایل."""
        if key in self.pending:
            return self.pending[key]
        return config.load().get(key)

    def supplied(self, key):
        """مقدار از خط فرمان یا محیط (فقط non-interactive): --set، گزینه‌ی اسم‌دار، env."""
        if key in self.args.set_values:
            return self.args.set_values[key]
        flag = NAMED_FLAGS.get(key)
        if flag:
            value = getattr(self.args, flag.lstrip("-").replace("-", "_"), None)
            if value not in (None, ""):
                return value
        names = [config.env_name(key), "CONFIGURE_" + key.upper().replace(".", "_")]
        for name in names:
            if name and os.environ.get(name):
                return os.environ[name]
        return None

    def say(self, en="", fa=None):
        self.p.say(en, fa)

    def heading(self, en, fa):
        self.say()
        self.say(f"== {en} ==", f"== {fa} ==")

    def confirm(self, en, fa, default=False, noninteractive=False):
        """سؤال بله/خیر. توی non-interactive جوابِ ثابتِ noninteractive رو می‌ده."""
        if not self.interactive:
            return noninteractive
        return self.p.confirm(_both(en, fa), default)

    # -- یه فیلد --------------------------------------------------------

    def set(self, key, value):
        if value == self.current(key):
            self.pending.pop(key, None)
        else:
            self.pending[key] = value

    def field(self, key, en, fa, parse, secret=False):
        """
        یه کلید رو می‌پرسه (یا از flag/env می‌گیره) و اگه عوض شده بود
        pending می‌کنه. Enter = نگه‌دار؛ «-» = پاک کن (برای اختیاری‌ها).
        """
        shown = config.mask_value(key, self.effective(key))
        label = _both(en, fa)
        required = key in self.required and not self.effective(key)
        cleared = [] if isinstance(config.default_for(key), list) else ""

        if not self.interactive:
            raw = self.supplied(key)
            if raw is None:
                return None
            value, error = parse(raw)
            if error:
                self.errors.append(f"{key}: {error}")
                return None
            self.set(key, value)
            return value

        while True:
            raw = self.p.ask(label, shown, secret)
            if not raw:
                if required:
                    self.say("This one is required. / این یکی اجباریه.")
                    continue
                return None
            if raw == "-":
                if required:
                    self.say("This one is required. / این یکی اجباریه.")
                    continue
                self.set(key, cleared)
                return cleared
            value, error = parse(raw)
            if error:
                self.say(error)
                continue
            self.set(key, value)
            return value

    # -- ۱) پایتون و نصب ---------------------------------------------

    def step_python(self):
        self.heading("Python", "پایتون")
        version = ".".join(str(part) for part in sys.version_info[:3])
        if sys.version_info < MIN_PYTHON:
            need = ".".join(str(part) for part in MIN_PYTHON)
            self.errors.append(f"Python {need}+ is required, this is {version}. "
                               f"پایتون {need} یا بالاتر لازمه.")
            self.say(f"Python {version} is too old; {need}+ is required.",
                     f"پایتون {version} قدیمیه؛ {need} یا بالاتر لازمه.")
            return False
        self.say(f"Python {version}: OK", f"پایتون {version}: مناسبه")
        return True

    def _install_wanted(self, name, default):
        """کاربر تعاملی: می‌پرسه. non-interactive: فقط اگه توی --install-components اومده باشه."""
        if self.interactive:
            return self.p.confirm(_both(f"Install {name} now?", f"{name} الان نصب بشه؟"), default)
        chosen = self.args.install_components
        if "all" in chosen:
            return True
        if "default" in chosen:
            return default
        return name in chosen

    def step_components(self):
        self.heading("Components", "کامپوننت‌ها")
        if self.args.skip_install:
            self.say("Skipped (--skip-install).", "رد شد (--skip-install).")
            return
        import install

        missing_modules = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
        if not missing_modules:
            self.say("Python packages: OK", "پکیج‌های پایتون: آماده")
        else:
            self.say(f"Missing Python packages: {', '.join(missing_modules)}",
                     f"پکیج‌های پایتونِ نصب‌نشده: {', '.join(missing_modules)}")
            if self._install_wanted("python", True):
                self._run_install(install, "python")
            else:
                self.warnings.append("python packages missing: " + ", ".join(missing_modules))

        for name, default in NATIVE_COMPONENTS:
            label = install.COMPONENT_LABELS.get(name, name)
            # dry-run: فقط می‌پرسه «نصبه یا نه»؛ خروجیِ پلنش رو چاپ نمی‌کنیم.
            with contextlib.redirect_stdout(io.StringIO()):
                status = install.run([name], True, True, None)[name]
            if status == install.Status.OK:
                self.say(f"{name}: OK", f"{name}: آماده")
                continue
            self.say(f"{name} is not installed ({label}).", f"{name} نصب نیست ({label}).")
            if self._install_wanted(name, default):
                self._run_install(install, name)
            elif default:
                self.warnings.append(f"{name} is not installed")

    def _run_install(self, install, name):
        status = install.run([name], False, True, None)[name]
        if status == install.Status.FAILED:
            self.warnings.append(f"installing {name} failed")
        elif status == install.Status.MANUAL:
            self.warnings.append(f"{name} needs a manual step (see above)")

    def step_init_files(self):
        """فایل‌های کانفیگ/کلید/دیتابیس: همون `license_server.py --init`."""
        import license_server
        try:
            created = license_server.init_files()
        except Exception as e:
            self.errors.append(f"could not prepare the platform files: {type(e).__name__}: {e}")
            return
        self.created.extend(created)
        for path in created:
            self.say(f"Created: {path}", f"ساخته شد: {path}")

    # -- ۲) تلگرام -----------------------------------------------------

    def step_telegram(self):
        self.heading("Telegram sales bot", "ربات فروش تلگرام")
        self.say("api.telegram.org is blocked on many networks. Enter the proxy first; "
                 "the system proxy is never used. Blank keeps the current value, - clears it.",
                 "api.telegram.org روی خیلی از شبکه‌ها بسته‌ست. اول پروکسی رو بنویس؛ "
                 "پروکسی سیستم هیچ‌وقت استفاده نمی‌شه. خالی = نگه‌دار، - = پاک کن.")
        proxy_args = ("proxy_url", "Proxy for Telegram (http://host:port or socks5://host:port)",
                      "پروکسی تلگرام (http://host:port یا socks5://host:port)", parse_proxy)
        token_args = ("sales_bot_token", "Sales bot token from @BotFather",
                      "توکن ربات فروش از @BotFather", parse_token)
        self.field(*proxy_args)
        self.field(*token_args, secret=True)

        while True:
            token = self.in_use("sales_bot_token")
            if not token:
                return  # اجباریه؛ آخرِ کار توی check گزارش می‌شه
            if self.args.skip_network:
                self.say("Token validation skipped (--skip-network).", "اعتبارسنجی توکن رد شد (--skip-network).")
                return
            proxy = config.proxy_url() if "proxy_url" not in self.pending else (self.pending["proxy_url"] or None)
            ok, detail = probe_bot(token, proxy)
            if ok:
                self.say(f"getMe succeeded: the token belongs to {detail}.", f"getMe موفق بود: توکن مال {detail} است.")
                return
            self.say(f"getMe failed: {detail}", f"getMe شکست خورد: {detail}")
            if not self.interactive:
                self.pending.pop("sales_bot_token", None)
                self.errors.append(f"the bot token could not be validated ({detail}); not saved. "
                                   "Use --proxy-url, or --skip-network to save it unchecked.")
                return
            choice = self.p.choose(
                _both("What now?", "حالا چی؟"),
                [("r", "retry / تلاش دوباره"), ("t", "enter a different token / توکن دیگه"),
                 ("p", "change the proxy / عوض‌کردن پروکسی"),
                 ("k", "keep it anyway, unchecked / همین رو نگه‌دار"),
                 ("s", "discard this change / این تغییر رو کنار بذار")], "r")
            if choice == "t":
                self.field(*token_args, secret=True)
            elif choice == "p":
                self.field(*proxy_args)
            elif choice == "k":
                return
            elif choice == "s":
                self.pending.pop("sales_bot_token", None)
                return

    # -- ۳) ادمین و پرداخت ---------------------------------------------

    def step_admin_payment(self):
        self.heading("Admins and payment", "ادمین‌ها و پرداخت")
        self.say("Admin ids are numeric Telegram ids, comma separated; the first is the main admin. "
                 "Enter the full list: it replaces the current one.",
                 "آیدی ادمین‌ها عددی‌ان و با کاما جدا می‌شن؛ اولی ادمین اصلیه. "
                 "کل لیست رو بنویس: جای لیست فعلی می‌شینه.")
        self.field("admin_ids", "Admin Telegram ids", "آیدی تلگرام ادمین‌ها", parse_admin_ids)
        self.field("card_number", "Card number shown to customers", "شماره کارتی که به مشتری نشون داده می‌شه", parse_card)
        self.field("card_holder", "Card holder name", "نام صاحب کارت", parse_text)
        self.field("card_bank", "Bank name", "نام بانک", parse_text)
        self.field("support_username", "Support username for 'contact support'", "یوزرنیم پشتیبانی", parse_text)

    # -- ۴) اختیاری: Cloudflare و کریپتو --------------------------------

    def step_cloudflare(self):
        self.heading("Cloudflare rental licences (optional)", "لایسنس اجاره‌ای با Cloudflare (اختیاری)")
        configured = any(self.effective(k) for k in CLOUDFLARE_KEYS)
        if self.interactive:
            if not self.p.confirm(_both("Configure Cloudflare?", "Cloudflare تنظیم بشه؟"), configured):
                return
        elif not any(self.supplied(k) for k in CLOUDFLARE_KEYS):
            self.say("Nothing supplied; skipped.", "چیزی داده نشد؛ رد شد.")
            return

        if self.interactive and not self.effective("cloudflare_kv_namespace"):
            self.say("No KV namespace yet? Run 'wrangler login' and then 'python manage.py deploy-worker' "
                     "(it creates one); or make the token with Workers KV Storage: Edit permission.",
                     "هنوز KV نداری؟ 'wrangler login' بزن و بعد 'python manage.py deploy-worker' "
                     "(خودش می‌سازه)؛ توکن رو با دسترسی Workers KV Storage: Edit بساز.")
        while True:
            self.field("cloudflare_account_id", "Cloudflare account id", "شناسه حساب Cloudflare", parse_text)
            self.field("cloudflare_kv_namespace", "KV namespace id", "شناسه KV namespace", parse_text)
            self.field("cloudflare_api_token", "Cloudflare API token", "توکن API کلادفلر", parse_text, secret=True)
            values = {k: self.in_use(k) for k in CLOUDFLARE_KEYS}
            if not all(values.values()):
                missing = ", ".join(k for k, v in values.items() if not v)
                self.say(f"Incomplete, rental licences stay off until these are set: {missing}",
                         f"ناقصه؛ صدور لایسنس اجاره‌ای تا تنظیم‌شدنِ این‌ها خاموشه: {missing}")
                return
            if self.args.skip_network:
                return
            if not self.interactive and not any(k in self.pending for k in CLOUDFLARE_KEYS):
                return  # چیزی عوض نشده؛ --check خودش وضعیت رو می‌گه
            ok, detail = self._check_cloudflare(values)
            if ok:
                self.say(f"Cloudflare: {detail}", f"Cloudflare: {detail}")
                return
            self.say(f"Cloudflare check failed: {detail}", f"تست Cloudflare شکست خورد: {detail}")
            if not self.interactive:
                for key in CLOUDFLARE_KEYS:
                    self.pending.pop(key, None)
                self.errors.append(f"Cloudflare settings could not be validated ({detail}); not saved.")
                return
            choice = self.p.choose(_both("What now?", "حالا چی؟"),
                                   [("r", "re-enter the values / دوباره وارد می‌کنم"),
                                    ("k", "keep them anyway / همین‌ها بمونه"),
                                    ("s", "discard the changes / کنار بذار")], "r")
            if choice == "k":
                return
            if choice == "s":
                for key in CLOUDFLARE_KEYS:
                    self.pending.pop(key, None)
                return

    def _check_cloudflare(self, values):
        from licensing import cloudflare
        env = {"CF_ACCOUNT_ID": values["cloudflare_account_id"],
               "CF_KV_NAMESPACE": values["cloudflare_kv_namespace"],
               "CF_API_TOKEN": values["cloudflare_api_token"]}
        with _temp_env(env):
            ok, detail = cloudflare.check_connection()
        return ok, str(detail).replace(values["cloudflare_api_token"], "***")

    def _crypto_module(self):
        """licensing/crypto_pay.py، یا None اگه این نسخه نداره -- اعتبارسنجی آدرس/شبکه از همون‌جاست، کپی نمی‌شه."""
        try:
            from licensing import crypto_pay
        except ImportError:
            return None
        return crypto_pay

    def _parse_crypto_network(self, raw):
        code = raw.strip().lower()
        module = self._crypto_module()
        if module is not None and code not in module.NETWORKS:
            return None, _both(f"Choose one of: {', '.join(sorted(module.NETWORKS))}",
                               f"یکی از این‌ها: {', '.join(sorted(module.NETWORKS))}")
        return code, None

    def _parse_crypto_address(self, raw):
        address = raw.strip()
        module = self._crypto_module()
        network = module.NETWORKS.get(str(self.effective("crypto.network")).lower()) if module else None
        if network is not None and not network.valid_address(address):
            return None, _both(f"That is not a valid {network.label} address (check for typos).",
                               f"این آدرسِ معتبرِ {network.label} نیست (غلط تایپی رو چک کن).")
        return address, None

    def step_crypto(self):
        self.heading("Crypto payments (optional)", "پرداخت کریپتو (اختیاری)")
        # فقط کلیدهایی که ماژول کانفیگ *می‌شناسه*؛ نسخه‌ای که crypto.* نداره
        # بی‌سروصدا رد می‌شه، نه خطا.
        known = config.known_keys("crypto.")
        if not known:
            self.say("This version has no crypto.* settings; skipped.",
                     "این نسخه تنظیمات crypto.* نداره؛ رد شد.")
            return
        if self.interactive:
            if not self.p.confirm(_both("Configure crypto (USDT) payments?", "پرداخت کریپتو (USDT) تنظیم بشه؟"),
                                  bool(self.effective("crypto.enabled"))):
                return
            self.say("The bot only watches your public wallet address; it never holds a private key.",
                     "ربات فقط آدرس عمومی کیف‌پولت رو می‌پاییده؛ هیچ‌وقت کلید خصوصی نداره.")
        elif not any(self.supplied(k) for k in known):
            self.say("Nothing supplied; skipped.", "چیزی داده نشد؛ رد شد.")
            return

        # ترتیبِ پرسیدن: شبکه قبل از آدرس، چون اعتبارسنجیِ آدرس به شبکه بستگی داره.
        parsers = {
            "crypto.network": ("Network (trc20 = USDT on TRON, bep20 = USDT on BSC)",
                               "شبکه (trc20 = تتر روی ترون، bep20 = تتر روی BSC)", self._parse_crypto_network),
            "crypto.address": ("Your receiving wallet address (public)", "آدرس دریافتِ کیف‌پولت (عمومی)",
                               self._parse_crypto_address),
        }
        order = [k for k in ("crypto.network", "crypto.address") if k in known]
        order += [k for k in known if k not in order and k != "crypto.enabled"]
        for key in order:
            if self.interactive:
                # هر کلید API فقط برای شبکه‌ی خودش معنی داره
                network = str(self.effective("crypto.network")).lower()
                if (key == "crypto.trongrid_api_key" and network != "trc20") or \
                        (key == "crypto.explorer_api_key" and network != "bep20"):
                    continue
            en, fa, parse = parsers.get(key) or (
                key, key, parse_by_default(config.default_for(key)))
            self.field(key, en, fa, parse, secret=config.is_secret_key(key))

        if "crypto.enabled" in known:
            if self.interactive:
                self.set("crypto.enabled", self.p.confirm(
                    _both("Enable crypto payments now?", "پرداخت کریپتو الان فعال بشه؟"), True))
            else:
                self.field("crypto.enabled", "crypto.enabled", "crypto.enabled",
                           parse_by_default(config.default_for("crypto.enabled")))

        module = self._crypto_module()
        if module is not None and self.effective("crypto.enabled"):
            settings = {k[len("crypto."):]: self.effective(k) for k in known}
            reason = module.unavailable_reason(settings)
            if reason:
                self.warnings.append(f"crypto payments are enabled but not usable yet ({reason})")
                self.say(f"Crypto payments would not work yet: {reason}",
                         f"پرداخت کریپتو هنوز کار نمی‌کنه: {reason}")

    def step_extras(self):
        """هر کلید دیگه‌ی کانفیگ: تعاملی فقط اگه بخوای؛ non-interactive فقط اگه --set/env داده باشی."""
        handled = set(NAMED_FLAGS)
        keys = [k for k in config.known_keys()
                if k not in handled and not k.startswith("crypto.")
                and not k.startswith(_RETIRED_PREFIXES)
                and not isinstance(config.default_for(k), dict)]
        if self.interactive:
            if not self.p.confirm(_both("Edit advanced settings (timeouts, grace days, ...)?",
                                        "تنظیمات پیشرفته (تایم‌اوت، مهلت تمدید، ...) ویرایش بشه؟"), False):
                return
            self.heading("Advanced settings", "تنظیمات پیشرفته")
        for key in keys:
            self.field(key, key, key, parse_by_default(config.default_for(key)),
                       secret=config.is_secret_key(key))

    # -- نوشتن --------------------------------------------------------

    def step_write(self):
        self.heading("Saving", "ذخیره")
        if not self.pending:
            self.say("No changes; the config file was left as it is.",
                     "تغییری نبود؛ فایل کانفیگ دست‌نخورده موند.")
            return
        self.say("Changes:", "تغییرها:")
        for key, value in self.pending.items():
            old = config.mask_value(key, self.current(key)) or "(empty)"
            new = config.mask_value(key, value) or "(empty)"
            self.say(f"  {key}: {old} -> {new}")
        if not self.confirm(f"Write these changes to {config.CONFIG_FILE}?",
                            f"این تغییرها توی {config.CONFIG_FILE} نوشته بشه؟", True, True):
            self.say("Not written.", "نوشته نشد.")
            self.pending.clear()
            return
        try:
            config.save_values(self.pending)
        except (config.ConfigWriteError, OSError) as e:
            self.errors.append(f"could not write the config: {e}")
            return
        self.written = list(self.pending)
        self.pending.clear()
        self.say(f"Saved: {config.CONFIG_FILE}", f"ذخیره شد: {config.CONFIG_FILE}")
        for key in self.written:
            env = config.env_overrides().get(key)
            if env:
                self.warnings.append(f"{env} is set in the environment and overrides {key} from the file")

    # -- ۵) ربات اول و لایسنس مالک --------------------------------------

    def find_bots(self):
        """[(پوشه‌ی سرور، اسم ربات، مسیر)] برای رباتِ‌های ساخته‌شده زیر data/."""
        found = []
        if not os.path.isdir(self.data_dir):
            return found
        for group in sorted(os.listdir(self.data_dir)):
            group_dir = os.path.join(self.data_dir, group)
            if not (config_defaults.is_server_group_name(group)
                    and os.path.isfile(os.path.join(group_dir, "shared_config.json"))):
                continue
            for bot in sorted(os.listdir(group_dir)):
                if os.path.isfile(os.path.join(group_dir, bot, "identity.json")):
                    found.append((group, bot, os.path.join(group_dir, bot)))
        return found

    def _bot_value(self, name, en, fa, default="", secret=False, kind=str):
        """یه مقدار برای ربات: تعاملی می‌پرسه، non-interactive از --bot-*/env."""
        if not self.interactive:
            raw = getattr(self.args, "bot_" + name, None)
            if raw is None:
                raw = os.environ.get("CONFIGURE_BOT_" + name.upper())
            return kind(raw) if raw not in (None, "") else default
        while True:
            raw = self.p.ask(_both(en, fa), str(default) if default not in ("", None) and not secret else "", secret)
            if not raw:
                if default == "" and name in ("host",):
                    self.say("This one is required. / این یکی اجباریه.")
                    continue
                return default
            try:
                return kind(raw)
            except ValueError:
                self.say("Enter a number. / یه عدد بنویس.")

    def step_bot_and_licence(self):
        self.heading("First bot and owner licence (optional)", "اولین ربات و لایسنس مالک (اختیاری)")
        bots = self.find_bots()
        if bots:
            self.say("Bots found: " + ", ".join(f"{g}/{b}" for g, b, _ in bots),
                     "ربات‌های موجود: " + ", ".join(f"{g}/{b}" for g, b, _ in bots))

        bot_dir = None
        if self.interactive:
            want_bot = self.p.confirm(_both("Create a TeamTalk bot now?", "یه ربات تیم‌تاک الان ساخته بشه؟"), not bots)
        else:
            want_bot = self.args.create_bot
        if want_bot:
            bot_dir = self._create_bot()
        elif len(bots) == 1:
            bot_dir = bots[0][2]

        owner = (config.admin_ids() or [None])[0]
        if owner is None:
            self.say("No admin configured; skipping the owner licence.", "ادمینی تنظیم نشده؛ لایسنس مالک رد شد.")
            return
        if not self.confirm(f"Create the owner's own licence for admin {owner}?",
                            f"لایسنس مالک برای ادمین {owner} ساخته بشه؟", True, self.args.self_license):
            return
        self._owner_licence(owner, bot_dir)

    def _create_bot(self):
        host = self._bot_value("host", "TeamTalk server address", "آدرس سرور تیم‌تاک")
        if not host:
            self.errors.append("--create-bot needs --bot-host")
            return None
        port = self._bot_value("port", "Port (tcp=udp)", "پورت (tcp=udp)", 10333, kind=int)
        name = self._bot_value("name", "Short bot name (folder name)", "اسم کوتاه ربات (اسم پوشه)", "bot1")
        nickname = self._bot_value("nickname", "Bot nickname", "نیک‌نیم ربات", "Audio Player Bot")
        username = self._bot_value("username", "TeamTalk login username", "یوزرنیم لاگین")
        password = self._bot_value("password", "TeamTalk login password", "پسورد لاگین", secret=True)
        channel_id = self._bot_value("channel_id", "Default channel id", "آیدی کانال پیش‌فرض", 1, kind=int)
        channel_password = self._bot_value("channel_password", "Channel password (blank if none)",
                                           "پسورد کانال (اگه نداره خالی)", secret=True)
        try:
            group_dir, bot_dir, created = config_defaults.write_bot_files(
                self.data_dir, host, port, name, nickname, username, password, channel_id, channel_password)
        except OSError as e:
            self.errors.append(f"could not create the bot: {e}")
            return None
        if created:
            self.created.extend(created)
            self.say(f"Bot created: {bot_dir}", f"ربات ساخته شد: {bot_dir}")
            self.say("Audio devices are left on the default; see 'python manage.py devices' and 'line-add'.",
                     "دستگاه‌های صدا روی پیش‌فرضن؛ 'python manage.py devices' و 'line-add' رو ببین.")
        else:
            self.say(f"That bot already exists, left untouched: {bot_dir}",
                     f"این ربات از قبل هست، دست‌نخورده موند: {bot_dir}")
        return bot_dir

    def _owner_licence(self, owner, bot_dir):
        import manage
        from licensing import db as db_module
        from licensing import licenses

        existing = [row for row in db_module.get_db().licenses_by_user(owner)
                    if (row["notes"] or "").startswith("owner")]
        if existing:
            row = existing[0]
            self.say(f"The owner already has a licence: {row['key']}", f"مالک از قبل لایسنس داره: {row['key']}")
            if bot_dir and not os.path.isfile(os.path.join(bot_dir, licenses.LICENSE_FILE_NAME)):
                if self.confirm(f"Write license.json into {bot_dir}?", f"license.json توی {bot_dir} نوشته بشه؟", True, True):
                    licenses.write_license_file(bot_dir, row)
                    self.say("license.json written.", "license.json نوشته شد.")
            return
        args = [str(owner)]
        if bot_dir:
            args.append(bot_dir)
        if manage.cmd_self_license(args):
            self.errors.append("the owner licence could not be created")

    # -- خلاصه و چک نهایی ---------------------------------------------

    def summary(self):
        self.heading("Summary", "خلاصه")
        self.say(f"Config file: {config.CONFIG_FILE}", f"فایل کانفیگ: {config.CONFIG_FILE}")
        loaded = config.reload()
        keys = list(SUMMARY_KEYS) + config.known_keys("crypto.")
        for key in keys:
            value = config.get_path(loaded, key, None)
            text = config.mask_value(key, value) if value not in (None, "", []) else "(not set)"
            self.say(f"  {key}: {text}")
        for key, env in config.env_overrides().items():
            self.say(f"  note: {env} overrides {key} from the file")
        bots = self.find_bots()
        self.say("Bots: " + (", ".join(f"{g}/{b}" for g, b, _ in bots) if bots else "(none)"),
                 "ربات‌ها: " + (", ".join(f"{g}/{b}" for g, b, _ in bots) if bots else "(هیچ)"))
        for warning in self.warnings:
            self.say(f"Warning: {warning}")
        for error in self.errors:
            self.say(f"Problem: {error}")

    def step_check(self):
        if self.args.skip_check:
            return 0
        self.heading("Final check (license_server.py --check)", "چک نهایی (license_server.py --check)")
        import license_server
        return license_server.cmd_check()

    # -- اجرای کل ---------------------------------------------------------

    def run(self):
        self.say("Configuration wizard for the TeamTalk bot platform.",
                 "ویزارد راه‌اندازی پلتفرم ربات تیم‌تاک.")
        config.file_values()
        if config.file_error():
            self.say(f"{config.CONFIG_FILE} is not valid JSON: {config.file_error()}",
                     "فایل کانفیگ JSON معتبر نیست؛ اول درستش کن یا پاکش کن.")
            return 1
        if not self.step_python():
            return 1
        self.step_components()
        self.step_init_files()
        self.step_telegram()
        self.step_admin_payment()
        self.step_cloudflare()
        self.step_crypto()
        self.step_extras()
        self.step_write()
        self.step_bot_and_licence()
        self.summary()
        check_code = self.step_check()
        return 1 if (self.errors or check_code) else 0


# ------------------------------------------------------------- خط فرمان

def _set_option(text):
    key, sep, value = text.partition("=")
    if not sep or not key.strip():
        raise argparse.ArgumentTypeError("use KEY=VALUE")
    return key.strip(), value


def build_parser():
    parser = argparse.ArgumentParser(
        description="Configure the whole project / راه‌اندازی کل پروژه. "
                    "Secrets are better passed by environment variable than by flag "
                    "(see docs/CONFIGURE.md).")
    parser.add_argument("--non-interactive", action="store_true",
                        help="never prompt; take values from flags and environment variables")
    parser.add_argument("--set", action="append", default=[], type=_set_option, metavar="KEY=VALUE",
                        help="any config key (e.g. grace_days=5, crypto.x=...); repeatable")
    for key, flag in NAMED_FLAGS.items():
        parser.add_argument(flag, default=None, metavar="VALUE",
                            help=f"{key} (env: {config.env_name(key) or 'CONFIGURE_' + key.upper()})")
    parser.add_argument("--install-components", default="", metavar="LIST",
                        help="non-interactive: comma list of python,teamtalk,ffmpeg,libmpv,"
                             "pulseaudio_utils,js_runtime,tesseract; or 'default' / 'all'")
    parser.add_argument("--skip-install", action="store_true", help="do not check or install components")
    parser.add_argument("--skip-network", action="store_true",
                        help="do not validate the bot token / Cloudflare (saves them unchecked)")
    parser.add_argument("--skip-check", action="store_true", help="do not run license_server.py --check at the end")
    parser.add_argument("--self-license", action="store_true",
                        help="non-interactive: create the owner's licence for the first admin")
    parser.add_argument("--create-bot", action="store_true",
                        help="non-interactive: create a first bot (needs --bot-host)")
    for name in BOT_FLAGS:
        parser.add_argument("--bot-" + name.replace("_", "-"), default=None, metavar="VALUE",
                            help=f"first bot: {name} (env: CONFIGURE_BOT_{name.upper()})")
    return parser


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.install_components = {part.strip() for part in args.install_components.split(",") if part.strip()}

    values = {}
    for key, value in args.set:
        if not config.knows(key):
            if key.startswith("crypto."):
                # crypto.* رو یه نفر دیگه داره اضافه می‌کنه؛ کلیدِ ناشناس نباید کل اجرا رو بخوابونه.
                print(f"Note: {key} is not a setting in this version; ignored. / "
                      f"{key} توی این نسخه نیست؛ نادیده گرفته شد.")
                continue
            parser.error(f"unknown config key: {key}")
        values[key] = value
    args.set_values = values
    return args


def main(argv=None, prompter=None, data_dir=None):
    args = parse_args(argv)
    wizard = Wizard(args, prompter or Prompter(), data_dir=data_dir)
    try:
        return wizard.run()
    except WizardAbort:
        print("\nInput ended; nothing more was written. Run again to continue. / "
              "ورودی تموم شد؛ چیز دیگه‌ای نوشته نشد. دوباره اجرا کن تا ادامه بدی.")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelled. / لغو شد.")
        sys.exit(130)
