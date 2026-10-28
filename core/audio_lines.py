"""
مدیریت «لاین صدا» (کابل صوتی مجازی) روی ویندوز و لینوکس، با یه API واحد.

## لاین صدا یعنی چی

هر ربات باید صدایی که mpv پخش می‌کنه رو به میکروفون تیم‌تاک بده. برای این
کار یه دستگاه صوتی مجازی لازمه که یه سر «خروجی» باشه (mpv توش می‌نویسه) و
سر دیگه‌ش «ورودی» (تیم‌تاک ازش می‌خونه). روی ویندوز این کار با برنامه‌ی
Virtual Audio Cable انجام می‌شه و هر «Line» یکی از همین‌هاست.

## چرا لینوکس بهتره

روی لینوکس دقیقاً همین مفهوم به‌صورت *بومی* و بدون هیچ نرم‌افزار تجاری‌ای
وجود داره: یه null-sink پالس‌اودیو. هر null-sink یه دستگاه خروجیه و
مانیتورش (<sink>.monitor) یه دستگاه ورودی. تفاوت مهم با ویندوز اینه که
اینجا لاین‌ها رو می‌شه *برنامه‌ای* ساخت و پاک کرد -- یعنی وقتی یه لایسنس
فعال می‌شه یه لاین جدید ساخته می‌شه و وقتی غیرفعال می‌شه واقعاً حذف
می‌شه، بدون هیچ دخالت دستی. روی ویندوز فقط می‌شه لاین‌های *از قبل ساخته‌شده*
رو بین ربات‌ها تقسیم کرد (چون ساختن لاین جدید توی VAC نیاز به درایور/کنترل
پنل خودش داره).

## ذخیره‌ی وضعیت

چون ماژول‌های پالس‌اودیو با ری‌استارت سرویس/سیستم از بین می‌رن، لیست
لاین‌ها توی data/_audio_lines.json نگه داشته می‌شه و ensure_line() هر بار
که لازم باشه دوباره می‌سازدشون. یعنی بعد از ریبوت، ربات‌ها بدون کار دستی
بالا میان.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time

from core import paths
from core import logging_setup
from core import platform_paths
from core.paths import get_base_dir

STATE_FILE = os.path.join(get_base_dir(), "data", "_audio_lines.json")

# پیشوند اسم sink ها. عمداً کوتاه و بدون کاراکتر خاص، چون پالس‌اودیو روی
# اسم sink سخت‌گیره و تیم‌تاک هم همین اسم رو به‌عنوان device id می‌بینه.
LINE_PREFIX = "ttline_"

_state_lock = threading.RLock()

# --- سیستم صوتی تیم‌تاک (همون اعداد داخل TeamTalk5.SoundSystem) ---
SOUNDSYSTEM_WINMM = 1
SOUNDSYSTEM_DSOUND = 2
SOUNDSYSTEM_ALSA = 3
SOUNDSYSTEM_WASAPI = 5
SOUNDSYSTEM_PULSEAUDIO = 10


class AudioLineError(Exception):
    pass


# --------------------------------------------------------------- وضعیت

def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return {"lines": {}}
    if not isinstance(data, dict) or not isinstance(data.get("lines"), dict):
        return {"lines": {}}
    return data


def _save_state(state):
    paths.write_json_atomic(STATE_FILE, state, indent=2, makedirs=True)


def safe_line_slug(raw):
    """اسم لاین رو به چیزی که پالس‌اودیو قبول می‌کنه تبدیل می‌کنه."""
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(raw)).strip("_").lower()
    slug = re.sub(r"_+", "_", slug)
    return slug[:40] or "line"


# ------------------------------------------------------------- backend

def backend():
    """«pulse» روی لینوکسِ دارای pactl، «windows» روی ویندوز، وگرنه «none»."""
    if platform_paths.IS_WINDOWS:
        return "windows"
    if shutil.which("pactl"):
        return "pulse"
    return "none"


def backend_is_manageable():
    """آیا این سیستم می‌تونه لاین *جدید* بسازه (نه فقط لاین موجود رو بگیره)؟"""
    return backend() == "pulse"


# --------------------------------------------------------- پالس‌اودیو

def _pactl(*args, check=True, timeout=15):
    cmd = ["pactl"] + list(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise AudioLineError("pactl نصب نیست. روی دبیان/اوبونتو: sudo apt install pulseaudio-utils")
    except subprocess.TimeoutExpired:
        raise AudioLineError("دستور pactl جواب نداد (timeout): " + " ".join(cmd))
    if check and proc.returncode != 0:
        raise AudioLineError(
            "pactl شکست خورد ({0}): {1}\n{2}".format(
                proc.returncode, " ".join(cmd), (proc.stderr or "").strip()
            )
        )
    return proc


def pulse_available():
    """
    آیا یه سرور پالس‌اودیو/پایپ‌وایر در دسترسه؟ صرفاً نصب‌بودن pactl کافی
    نیست -- روی سرویس‌های systemd سطح سیستم معمولاً هیچ سشن صوتی‌ای وجود
    نداره و همه‌ی دستورها با «Connection refused» رد می‌شن.
    """
    if backend() != "pulse":
        return False
    try:
        return _pactl("info", check=False, timeout=8).returncode == 0
    except AudioLineError:
        return False


def _pulse_sinks():
    """مجموعه‌ی اسم همه‌ی sink های فعلی."""
    proc = _pactl("list", "short", "sinks", check=False)
    sinks = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            sinks.add(parts[1])
    return sinks


def _pulse_null_sink_modules():
    """{module_id: argument_string} برای ماژول‌های null-sink بارگذاری‌شده."""
    proc = _pactl("list", "short", "modules", check=False)
    modules = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] == "module-null-sink":
            modules[parts[0]] = parts[2] if len(parts) > 2 else ""
    return modules


def _pulse_create_sink(sink_name, description):
    args = [
        "load-module", "module-null-sink",
        "sink_name=" + sink_name,
        "sink_properties=device.description=" + _quote_pulse_value(description),
    ]
    proc = _pactl(*args)
    module_id = (proc.stdout or "").strip()
    if not module_id.isdigit():
        raise AudioLineError("ساخت لاین صدا جواب غیرمنتظره داد: " + repr(module_id))
    return module_id


def _quote_pulse_value(value):
    """
    پالس‌اودیو مقدارِ property رو با فاصله می‌شکنه، پس باید داخل کوتیشن
    باشه. کوتیشن‌های خود متن هم حذف می‌شن تا آرگومان خراب نشه.
    """
    cleaned = str(value).replace("'", "").replace('"', "")
    return "'" + cleaned + "'"


def _pulse_destroy_sink(sink_name, module_id=None):
    # اول با شناسه‌ی ماژول (دقیق‌ترین راه)، بعد به‌عنوان fallback با
    # جستجوی خود sink بین ماژول‌ها -- چون بعد از ری‌استارت پالس، شناسه‌ی
    # ذخیره‌شده‌ی ما دیگه معتبر نیست و ممکنه ماژولِ کس دیگه‌ای رو ببنده.
    modules = _pulse_null_sink_modules()
    if module_id and str(module_id) in modules and ("sink_name=" + sink_name) in modules[str(module_id)]:
        _pactl("unload-module", str(module_id), check=False)
        return True
    for mid, args in modules.items():
        if ("sink_name=" + sink_name) in args:
            _pactl("unload-module", mid, check=False)
            return True
    return False


# ------------------------------------------------------- لاین‌های ویندوز

def _windows_cable_key(device_name):
    """
    اسم دستگاه رو به یه «کلید لاین» تبدیل می‌کنه تا سر خروجی و سر ورودی
    یه کابل به هم وصل بشن. VAC هر دو سر رو با یه اسم نشون می‌ده («Line 1»)
    ولی VB-CABLE با دو اسم («CABLE Input» برای پخش، «CABLE Output» برای
    ضبط) -- پس کلمه‌ی input/output از کلید حذف می‌شه.

    اگه اسم دستگاه هیچ نشونه‌ای از کابل مجازی نداشته باشه None برمی‌گرده،
    یعنی این یه کارت صدای واقعیه و نباید به رباتی داده بشه.
    """
    name = (device_name or "").lower()

    # ویندوز برای *هر* دستگاه خروجی یه نسخه‌ی «[Loopback]» هم به‌عنوان
    # ورودی نشون می‌ده. برای یه کابل مجازی این نسخه‌ی بدلیه: سر ورودیِ
    # واقعی کابل جداگانه وجود داره و باید همون انتخاب بشه، وگرنه دو ربات
    # ممکنه بدون این‌که بفهمیم به یه سر کابل وصل بشن.
    if "[loopback]" in name:
        return None

    match = re.search(r"\bline\s*(\d+)\b", name)
    if match and "virtual audio cable" in name:
        return "vac:line" + str(int(match.group(1)))

    if "cable" in name and ("vb-audio" in name or "vb audio" in name or "virtual" in name):
        match = re.search(r"\bcable[- ]?([a-d])\b", name)
        letter = match.group(1) if match else ""
        return "vbcable:" + (letter or "main")

    return None


# ------------------------------------------- شمارش دستگاه‌ها

def list_output_devices():
    """
    دستگاه‌های *خروجی* از دید mpv: [(name, description)].
    اسم (نه ایندکس) برگردونده می‌شه، چون mpv خروجی رو با اسم انتخاب می‌کنه
    و ایندکس‌ها بین ری‌استارت‌ها جابه‌جا می‌شن.
    """
    try:
        from core.mpv.mpv import MPV
    except Exception as e:
        logging_setup.log_debug("mpv unavailable for device listing: {0}".format(e))
        return []

    player = None
    try:
        player = MPV(vo="null")
        return [(d.get("name"), d.get("description") or d.get("name")) for d in (player.audio_device_list or [])]
    except Exception as e:
        logging_setup.log_debug("listing mpv output devices failed: {0}".format(e))
        return []
    finally:
        if player is not None:
            try:
                player.terminate()
            except Exception:
                pass


def _raw_sound_devices():
    """
    همه‌ی دستگاه‌های صوتی از دید SDK تیم‌تاک، *بدون* ساختن یه نمونه‌ی
    TeamTalk.

    چرا مستقیم TT_GetSoundDevices صدا زده می‌شه: این تابع توی SDK سراسریه و
    اصلاً به instance کاری نداره (خود متد getSoundDevices هم از self._tt
    استفاده نمی‌کنه). در عوض ساختن یه نمونه‌ی TeamTalk فقط برای «لیست
    گرفتن» گرونه و روی بعضی سیستم‌ها ثانیه‌ها طول می‌کشه -- در حالی که
    این لیست ممکنه وسط کار ربات لایسنس یا موقع ساخت لاین جدید لازم بشه.
    """
    from core.teamtalk.TeamTalk5 import SoundDevice, _GetSoundDevices
    from ctypes import c_int, byref

    count = c_int()
    _GetSoundDevices(None, byref(count))
    devices = (SoundDevice * count.value)()
    _GetSoundDevices(devices, byref(count))
    return devices


def list_sound_devices():
    """
    همه‌ی دستگاه‌های صوتی: [{id, name, device_id, sound_system, inputs, outputs}].
    """
    try:
        from core.teamtalk.TeamTalk5 import ttstr
        raw = _raw_sound_devices()
    except Exception as e:
        logging_setup.log_debug("TeamTalk SDK unavailable for device listing: {0}".format(e))
        return []

    result = []
    for dev in raw:
        result.append({
            "id": int(dev.nDeviceID),
            "name": ttstr(dev.szDeviceName),
            "device_id": ttstr(dev.szDeviceID),
            "sound_system": int(dev.nSoundSystem),
            "inputs": int(dev.nMaxInputChannels),
            "outputs": int(dev.nMaxOutputChannels),
        })
    return result


def list_input_devices():
    """
    دستگاه‌های *ورودی* از دید تیم‌تاک: [(device_id, name, sound_system, device_id_string)].

    device_id همون عددیه که initSoundInputDevice می‌خواد، ولی چون بین
    ری‌استارت‌ها عوض می‌شه، اسم و رشته‌ی شناسه هم برگردونده می‌شن تا
    resolve_input_device بتونه با اسم دوباره پیداش کنه.
    """
    return [
        (dev["id"], dev["name"], dev["sound_system"], dev["device_id"])
        for dev in list_sound_devices()
        if dev["inputs"] > 0
    ]


def preferred_sound_system():
    """کدوم سیستم صوتی برای این OS «درست» حساب می‌شه."""
    if platform_paths.IS_WINDOWS:
        return SOUNDSYSTEM_WASAPI
    if platform_paths.IS_LINUX:
        return SOUNDSYSTEM_PULSEAUDIO
    return None


# ------------------------------------------------------------- API اصلی

def line_names(slug):
    """
    اسم دو سر لاین: (اسم خروجی برای mpv، اسم ورودی برای تیم‌تاک).
    روی لینوکس از روی slug هم قابل ساختنه؛ روی ویندوز فقط از state خونده
    می‌شه، چون اونجا لاین‌ها از قبل وجود دارن و صرفاً تخصیص داده می‌شن.
    """
    rec = _load_state()["lines"].get(safe_line_slug(slug))
    if rec:
        return rec.get("output_device"), rec.get("input_device")
    if backend() == "pulse":
        sink = LINE_PREFIX + safe_line_slug(slug)
        return "pulse/" + sink, sink + ".monitor"
    return None, None


def list_lines():
    """همه‌ی لاین‌های ثبت‌شده: [{slug, owner, output_device, input_device, alive}]."""
    state = _load_state()
    alive_sinks = _pulse_sinks() if (backend() == "pulse" and pulse_available()) else set()
    result = []
    for slug, rec in sorted(state["lines"].items()):
        item = dict(rec)
        item["slug"] = slug
        item["alive"] = ((LINE_PREFIX + slug) in alive_sinks) if rec.get("backend") == "pulse" else True
        result.append(item)
    return result


def create_line(slug, description=None, owner=None):
    """
    یه لاین صدای جدید می‌سازه (لینوکس) یا یکی از لاین‌های آزاد رو تخصیص
    می‌ده (ویندوز). اگه از قبل وجود داشته باشه، همون برگردونده می‌شه.

    خروجی: dict شامل output_device (برای mpv) و input_device (برای تیم‌تاک).
    """
    slug = safe_line_slug(slug)
    description = description or ("TeamTalk bot line (" + slug + ")")

    with _state_lock:
        state = _load_state()
        if slug in state["lines"]:
            if state["lines"][slug].get("backend") == "pulse":
                ensure_line(slug)
                state = _load_state()
            return dict(state["lines"][slug], slug=slug)

        mode = backend()
        if mode == "pulse":
            if not pulse_available():
                raise AudioLineError(
                    "به سرور پالس‌اودیو/پایپ‌وایر وصل نشدیم. اگه ربات رو با systemd اجرا می‌کنی، "
                    "باید یه سرویس *کاربری* باشه و برای اون کاربر linger فعال باشه: "
                    "sudo loginctl enable-linger <user>"
                )
            sink = LINE_PREFIX + slug
            record = {
                "backend": "pulse",
                "sink": sink,
                "module_id": _pulse_create_sink(sink, description),
                "output_device": "pulse/" + sink,
                "input_device": sink + ".monitor",
                "description": description,
                "owner": owner,
                "created_at": int(time.time()),
            }
        elif mode == "windows":
            record = _windows_allocate_line(state, description, owner)
        else:
            raise AudioLineError(
                "این سیستم هیچ راهی برای لاین صدای مجازی نداره. روی لینوکس pulseaudio-utils "
                "نصب کن، روی ویندوز Virtual Audio Cable یا VB-CABLE."
            )

        state["lines"][slug] = record
        _save_state(state)
        return dict(record, slug=slug)


def _windows_allocate_line(state, description, owner):
    """
    روی ویندوز لاین ساخته نمی‌شه؛ از بین کابل‌های مجازیِ نصب‌شده یکی که
    هنوز به هیچ رباتی تخصیص داده نشده انتخاب می‌شه.
    """
    taken = set(rec.get("cable_key") for rec in state["lines"].values() if rec.get("cable_key"))

    outputs = {}
    for name, desc in list_output_devices():
        key = _windows_cable_key(desc) or _windows_cable_key(name)
        if key and key not in outputs:
            outputs[key] = name

    inputs = {}
    for _dev_id, name, _sound_system, _dev_id_str in list_input_devices():
        key = _windows_cable_key(name)
        if key and key not in inputs:
            inputs[key] = name

    available = sorted(k for k in outputs if k in inputs and k not in taken)
    if not available:
        installed = sorted(set(outputs) | set(inputs))
        if not installed:
            raise AudioLineError(
                "هیچ کابل صوتی مجازی‌ای روی این ویندوز پیدا نشد. Virtual Audio Cable یا VB-CABLE نصب کن."
            )
        raise AudioLineError(
            "همه‌ی {0} لاین صدای این سیستم قبلاً به ربات‌های دیگه داده شدن. "
            "توی کنترل‌پنل Virtual Audio Cable تعداد لاین‌ها رو زیاد کن.".format(len(installed))
        )

    key = available[0]
    return {
        "backend": "windows",
        "cable_key": key,
        "output_device": outputs[key],
        "input_device": inputs[key],
        "description": description,
        "owner": owner,
        "created_at": int(time.time()),
    }


def ensure_line(slug):
    """
    مطمئن می‌شه لاین واقعاً *الان* روی سیستم وجود داره. روی لینوکس بعد از
    ری‌استارت پالس‌اودیو یا ریبوت، sink از بین رفته و اینجا دوباره ساخته
    می‌شه (با همون اسم، پس کانفیگ ربات‌ها نیازی به تغییر نداره).
    """
    slug = safe_line_slug(slug)
    with _state_lock:
        state = _load_state()
        rec = state["lines"].get(slug)
        if not rec:
            return None
        if rec.get("backend") != "pulse" or not pulse_available():
            return dict(rec, slug=slug)

        sink = rec.get("sink") or (LINE_PREFIX + slug)
        if sink in _pulse_sinks():
            return dict(rec, slug=slug)

        rec["module_id"] = _pulse_create_sink(sink, rec.get("description") or sink)
        state["lines"][slug] = rec
        _save_state(state)
        logging_setup.log_debug("audio line '{0}' recreated after pulseaudio restart".format(slug))
        return dict(rec, slug=slug)


def ensure_all_lines():
    """همه‌ی لاین‌های ثبت‌شده رو بعد از بوت دوباره می‌سازه؛ تعداد بازسازی‌شده‌ها رو برمی‌گردونه."""
    if backend() != "pulse" or not pulse_available():
        return 0
    restored = 0
    existing = _pulse_sinks()
    for slug in list(_load_state()["lines"]):
        try:
            if (LINE_PREFIX + slug) in existing:
                continue
            if ensure_line(slug):
                restored += 1
        except Exception:
            logging_setup.log_exception("restoring audio line '{0}'".format(slug))
    return restored


def destroy_line(slug):
    """
    لاین رو کامل حذف می‌کنه. روی لینوکس sink واقعاً از بین می‌ره؛ روی
    ویندوز فقط تخصیصش آزاد می‌شه تا ربات بعدی بتونه ازش استفاده کنه.
    """
    slug = safe_line_slug(slug)
    with _state_lock:
        state = _load_state()
        rec = state["lines"].pop(slug, None)
        if rec is None:
            return False
        _save_state(state)

    if rec.get("backend") == "pulse" and pulse_available():
        try:
            _pulse_destroy_sink(rec.get("sink") or (LINE_PREFIX + slug), rec.get("module_id"))
        except Exception:
            logging_setup.log_exception("destroying audio line '{0}'".format(slug))
    return True


# --------------------------------------------- وصل‌کردن لاین به یه ربات

def resolve_output_device(configured):
    """
    مقدار audio.output_device توی کانفیگ ربات رو به چیزی که mpv قبول
    می‌کنه تبدیل می‌کنه.

    سه حالت پشتیبانی می‌شه:
      - "line:<slug>"  -> لاین مدیریت‌شده‌ی خودمون (پیشنهادی)
      - اسم دستگاه     -> مستقیم به mpv داده می‌شه
      - عدد            -> ایندکس، فقط برای سازگاری با کانفیگ‌های قدیمی
    """
    if isinstance(configured, str) and configured.startswith("line:"):
        slug = safe_line_slug(configured[5:])
        ensure_line(slug)
        output, _input = line_names(slug)
        if not output:
            raise AudioLineError("لاین صدای '{0}' توی این سیستم ثبت نشده.".format(slug))
        return output
    return configured


def resolve_input_device(configured):
    """
    مقدار audio.input_device رو به *شناسه‌ی عددی* فعلیِ تیم‌تاک تبدیل می‌کنه.

    چرا لازمه: شناسه‌ی عددی دستگاه‌ها روی لینوکس با هر ری‌استارت پالس‌اودیو
    عوض می‌شه، پس ذخیره‌ی خود عدد توی کانفیگ (کاری که نسخه‌ی قبلی می‌کرد)
    باعث می‌شه ربات بعد از ریبوت به یه دستگاه کاملاً دیگه وصل بشه. حالا
    اسم ذخیره می‌شه و اینجا به عدد ترجمه می‌شه.

    حالت‌ها:
      - "line:<slug>"  -> سر ورودیِ لاین مدیریت‌شده
      - اسم دستگاه     -> بین دستگاه‌های ورودی دنبالش می‌گرده
      - عدد            -> همون‌طور برگردونده می‌شه (سازگاری با قدیم)
    """
    if isinstance(configured, bool):
        raise AudioLineError("مقدار input_device نامعتبره: " + repr(configured))
    if isinstance(configured, int):
        return configured
    if isinstance(configured, str) and configured.strip().isdigit():
        return int(configured.strip())

    wanted = configured
    if isinstance(configured, str) and configured.startswith("line:"):
        slug = safe_line_slug(configured[5:])
        ensure_line(slug)
        _output, wanted = line_names(slug)
        if not wanted:
            raise AudioLineError("لاین صدای '{0}' توی این سیستم ثبت نشده.".format(slug))

    if not wanted:
        return 0

    return resolve_input_devices(configured)[0][0]


def resolve_input_devices(configured):
    """
    *همه‌ی* دستگاه‌های ورودی که به این اسم می‌خورن، به ترتیب اولویت:
    [(device_id, name)].

    یه دستگاه معمولاً زیر چند سیستم صوتی دیده می‌شه (WinMM، DirectSound،
    WASAPI روی ویندوز؛ ALSA و PulseAudio روی لینوکس) و *همه‌شون باز
    نمی‌شن*. مثال واقعی: کارت مجازی Virtual Audio Cable زیر WASAPI با
    «Input device setup failed» رد می‌شه ولی زیر WinMM بی‌مشکل کار می‌کنه.

    برای همین اینجا لیست برمی‌گرده نه یه عدد: صداکننده باید تا اولین
    دستگاهی که *واقعاً* باز می‌شه جلو بره (open_input_device).
    """
    if isinstance(configured, int) and not isinstance(configured, bool):
        return [(configured, "")]
    if isinstance(configured, str) and configured.strip().isdigit():
        return [(int(configured.strip()), "")]

    wanted = configured
    if isinstance(configured, str) and configured.startswith("line:"):
        slug = safe_line_slug(configured[5:])
        ensure_line(slug)
        _output, wanted = line_names(slug)
        if not wanted:
            raise AudioLineError("لاین صدای '{0}' توی این سیستم ثبت نشده.".format(slug))

    if not wanted:
        return [(0, "")]

    devices = list_input_devices()
    preferred = preferred_sound_system()
    wanted_lower = str(wanted).lower()

    # ترتیب مهمه: اول تطبیق دقیق روی سیستم صوتیِ «درستِ» این OS، بعد بقیه.
    # روی لینوکس یه دستگاه هم زیر ALSA و هم زیر PulseAudio دیده می‌شه و فقط
    # نسخه‌ی پالس‌اودیوش null-sink ما رو درست می‌خونه -- پس اون اول امتحان
    # می‌شه، ولی اگه باز نشد بقیه هم شانس دارن.
    ordered = []
    seen = set()
    for match_exact in (True, False):
        for require_preferred in (True, False):
            for dev_id, name, sound_system, dev_id_str in devices:
                if dev_id in seen:
                    continue
                if require_preferred and preferred is not None and sound_system != preferred:
                    continue
                for candidate in (dev_id_str, name):
                    if not candidate:
                        continue
                    candidate_lower = candidate.lower()
                    hit = (candidate_lower == wanted_lower if match_exact
                           else wanted_lower in candidate_lower)
                    if hit:
                        ordered.append((dev_id, name))
                        seen.add(dev_id)
                        break

    if not ordered:
        raise AudioLineError(
            "دستگاه ورودی صدا با اسم '{0}' پیدا نشد. دستگاه‌های موجود: {1}".format(
                wanted, ", ".join(n for _i, n, _s, _d in devices) or "(هیچی)"
            )
        )
    return ordered


def open_input_device(opener, configured):
    """
    دستگاه ورودی رو *واقعاً* باز می‌کنه و اولین کاندیدی که جواب داد
    برمی‌گردونه: (device_id, name, tried).

    `opener` همون تابعیه که دستگاه رو initialize می‌کنه (مثلاً
    TTBot.set_input_device). اگه هیچ‌کدوم باز نشد، خطای آخری بالا می‌ره.

    قبلاً فقط «بهترین» کاندید امتحان می‌شد و اگه اون یکی باز نمی‌شد ربات
    با میکروفون پیش‌فرض بالا می‌آمد: توی کانال دیده می‌شد، ولی صدای پخش
    هیچ‌وقت نمی‌رفت -- خرابیِ ساکتی که دیباگش سخته.
    """
    candidates = resolve_input_devices(configured)
    tried = []
    last_error = None
    for dev_id, name in candidates:
        try:
            opener(dev_id)
            return dev_id, name, tried
        except Exception as e:
            tried.append((dev_id, name, e))
            last_error = e
    raise last_error or AudioLineError(
        "هیچ دستگاه ورودی‌ای برای '{0}' باز نشد.".format(configured))
