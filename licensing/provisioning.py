"""
ساخت و حذف واقعیِ یه نمونه‌ی ربات روی سرور.

«فعال‌سازی لایسنس» در عمل یعنی این چند کار، به همین ترتیب:

    ۱. یه لاین صدای اختصاصی ساخته می‌شه (null-sink روی لینوکس).
    ۲. پوشه‌ی دیتا و shared_config.json/identity.json نوشته می‌شن.
    ۳. license.json کنارشون نوشته می‌شه (همون چیزی که امکانات رو قفل می‌کنه).
    ۴. پروسه‌ی ربات استارت می‌شه و از این به بعد سوپروایزر نگهش می‌داره.

«غیرفعال‌سازی» دقیقاً برعکس، و **با همین ترتیب اهمیت**:

    ۱. پروسه بسته می‌شه (اول این، وگرنه ربات با یه لاینِ حذف‌شده کار می‌کنه).
    ۲. لاین صدا حذف می‌شه.
    ۳. دیتای اون سرور پاک می‌شه.

قدم ۳ برگشت‌ناپذیره، پس پیش‌فرض `purge_data=False` است: تا مهلت تمدید
تموم نشده، دیتا می‌مونه. licensing/expiry.py بعد از پایان مهلت با
purge_data=True صداش می‌زنه.
"""

import json
import os
import shutil
import time

from core import paths
from core import audio_lines
from core import config_defaults
from core import license_gate
from core import logging_setup
from licensing import i18n
from core.paths import get_base_dir
from licensing import licenses
from licensing.db import json_list

DATA_DIR = os.path.join(get_base_dir(), "data")


class ProvisioningError(Exception):
    pass


def instance_slug(license_key, index):
    """
    اسم یکتای هر نمونه: از کلید لایسنس + شماره‌ی ربات ساخته می‌شه. هم کوتاهه
    (پالس‌اودیو روی اسم sink سخت‌گیره) هم از روی اسمش می‌شه فهمید مال کیه.
    """
    short = (license_key or "").replace("TT-", "").replace("-", "").lower()[:12]
    return audio_lines.safe_line_slug(f"{short}_{index}")


def free_instance_slug(db, license_key, taken=()):
    """
    اولین slugِ آزاد برای یه ربات جدیدِ این لایسنس.

    قبلاً شماره «تعداد ربات‌های موجود + ۱» بود. اگه مشتری ربات ۱ رو از بین
    ۲ ربات پاک می‌کرد، ربات بعدی دوباره شماره‌ی ۲ می‌گرفت و با ربات زنده‌ی
    شماره ۲ تصادم می‌کرد (UNIQUE constraint failed: instances.slug). حالا
    کوچک‌ترین شماره‌ای که توی دیتابیس نیست انتخاب می‌شه؛ taken برای
    شماره‌هایی است که همین الان توسط یه درخواست هم‌زمانِ دیگه گرفته شدن.
    """
    index = 1
    while True:
        slug = instance_slug(license_key, index)
        if slug not in taken and db.get_instance_by_slug(slug) is None:
            return slug
        index += 1


def _write_json(path, data):
    paths.write_json_atomic(path, data, makedirs=True)


def _ensure_shared_config(group_dir, host, port, operators, extras=None):
    """
    shared_config.json سرور. اگه از قبل هست دست‌کاریِ کاملش نمی‌کنیم و فقط
    لیست ادمین‌ها رو به‌روز می‌کنیم -- چون ممکنه مشتری خودش تنظیمات دیگه
    (زبان، پروکسی، تایمرها) رو عوض کرده باشه و نباید با هر تمدید پاک بشن.
    """
    path = os.path.join(group_dir, "shared_config.json")
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                shared = json.load(f)
        except (ValueError, OSError):
            shared = config_defaults.default_shared_config(host, port)
    else:
        shared = config_defaults.default_shared_config(host, port)

    shared.setdefault("server", {})
    shared["server"]["host"] = host
    shared["server"]["port"] = int(port)
    shared["admins"] = list(operators or [])
    for key, value in (extras or {}).items():
        shared[key] = value

    _write_json(path, shared)
    return path


def provision_instance(db, license_row, instance_row):
    """
    یه نمونه‌ی ثبت‌شده در دیتابیس رو روی دیسک و روی سیستم صدا پیاده می‌کنه.
    idempotent است: اجرای دوباره چیزی رو خراب نمی‌کنه.

    خروجی: (group_dir, bot_dir)
    """
    slug = instance_row["slug"]
    group_name = instance_row["group_name"] or config_defaults.server_folder_name(
        instance_row["tt_host"], instance_row["tt_port"])
    bot_name = instance_row["bot_name"] or config_defaults.safe_bot_folder_name(slug)

    group_dir = os.path.join(DATA_DIR, group_name)
    bot_dir = os.path.join(group_dir, bot_name)

    # ۱) لاین صدا
    line_slug = instance_row["audio_line"] or slug
    try:
        line = audio_lines.create_line(
            line_slug,
            description=f"TeamTalk bot {slug} ({license_row['key']})",
            owner=f"{group_name}/{bot_name}",
        )
    except audio_lines.AudioLineError as e:
        raise ProvisioningError(i18n.t("provision_line_failed", error=e)) from e

    # ۲) کانفیگ‌ها
    operators = json_list(instance_row["operators"])
    _ensure_shared_config(group_dir, instance_row["tt_host"], instance_row["tt_port"], operators)

    identity_path = os.path.join(bot_dir, "identity.json")
    if os.path.isfile(identity_path):
        try:
            with open(identity_path, "r", encoding="utf-8") as f:
                identity = json.load(f)
        except (ValueError, OSError):
            identity = config_defaults.default_identity()
    else:
        identity = config_defaults.default_identity()

    identity.setdefault("server", {})
    identity["server"]["nickname"] = instance_row["tt_nickname"] or "Audio Player Bot"
    identity["server"]["username"] = instance_row["tt_username"] or ""
    identity["server"]["password"] = instance_row["tt_password"] or ""
    identity.setdefault("channel", {})
    identity["channel"]["id"] = int(instance_row["tt_channel_id"] or 1)
    identity["channel"]["password"] = instance_row["tt_channel_password"] or ""
    # همیشه به اسم لاین اشاره می‌کنیم، نه به شماره‌ی دستگاه: شماره بعد از
    # ری‌استارت سیستم صدا عوض می‌شه و ربات به دستگاه اشتباه وصل می‌شد.
    identity["audio"] = {
        "input_device": f"line:{line['slug']}",
        "output_device": f"line:{line['slug']}",
    }
    identity["bot_admins"] = list(operators or [])
    # پرچم «مدیریت‌شده»: بدون این، پاک‌کردن license.json باعث می‌شد ربات
    # به‌جای بسته‌شدن، کامل و بدون قفل بالا بیاد (core/license_gate.py).
    identity[license_gate.MANAGED_FLAG] = True
    _write_json(identity_path, identity)

    try:
        os.chmod(identity_path, 0o600)
    except OSError:
        pass

    # ۳) فایل لایسنس
    licenses.write_license_file(bot_dir, license_row, instance_row)

    db.update_instance(int(instance_row["id"]),
                       audio_line=line["slug"],
                       group_name=group_name,
                       bot_name=bot_name,
                       status="created")
    db.log_event("instance_provisioned", user_id=int(license_row["user_id"]),
                 license_id=int(license_row["id"]),
                 detail={"slug": slug, "line": line["slug"], "bot_dir": bot_dir})

    return group_dir, bot_dir


def sync_unlimited(db):
    """
    لایسنس‌های نامحدودِ مالک/ادمین رو با کلِ کاتالوگ هم‌تراز می‌کنه و فایلِ
    لایسنسِ ربات‌هاشون رو تازه می‌کنه (licenses.sync_unlimited_features).
    موقعِ بالا اومدنِ license_server و توی جاروی شبانه صدا زده می‌شه.
    """
    updated = licenses.sync_unlimited_features(db)
    for row in updated:
        refresh_license_files(db, row)
    return updated


def refresh_license_files(db, license_row):
    """
    license.json همه‌ی نمونه‌های یه لایسنس رو دوباره می‌نویسه. بعد از
    تمدید یا اضافه‌کردن امکانات صدا زده می‌شه؛ ربات دفعه‌ی بعد که بالا بیاد
    (یا با rs) امکانات جدید رو می‌بینه.
    """
    updated = []
    for instance in db.instances_by_license(int(license_row["id"])):
        bot_dir = instance_dirs(instance)[1]
        if not os.path.isdir(bot_dir):
            continue
        licenses.write_license_file(bot_dir, license_row, instance)
        updated.append(instance["slug"])
    return updated


def instance_dirs(instance_row):
    group_name = instance_row["group_name"] or config_defaults.server_folder_name(
        instance_row["tt_host"], instance_row["tt_port"])
    bot_name = instance_row["bot_name"] or config_defaults.safe_bot_folder_name(instance_row["slug"])
    group_dir = os.path.join(DATA_DIR, group_name)
    return group_dir, os.path.join(group_dir, bot_name)


def deprovision_instance(db, instance_row, purge_data=False, supervisor=None):
    """
    نمونه رو خاموش می‌کنه و لاین صداش رو حذف می‌کنه.

    purge_data=True: پوشه‌ی دیتای این ربات هم پاک می‌شه (و اگه آخرین ربات
    اون سرور بود، پوشه‌ی سرور هم). برگشت‌ناپذیره -- فقط بعد از پایان مهلت
    تمدید یا با درخواست صریح.

    خروجی: dict از کارهایی که انجام شد، برای گزارش به ادمین.
    """
    done = {"stopped": False, "line_removed": False, "data_removed": False, "errors": []}
    instance_id = int(instance_row["id"])

    # ۱) خاموش کردن پروسه -- قبل از حذف لاین، وگرنه ربات با یه دستگاه
    # ناموجود ادامه می‌ده و لاگ رو پر می‌کنه.
    if supervisor is not None:
        try:
            done["stopped"] = supervisor.stop(instance_row["slug"])
        except Exception as e:
            # safe_error_text خودش log_exception رو صدا می‌زنه و traceback
            # کامل توی errors.log می‌مونه؛ چیزی که توی پیام می‌ره فقط یه
            # خلاصه‌ی امنه (نه مسیر فایل یا جزئیات داخلی).
            done["errors"].append(i18n.t(
                "provision_stop_failed",
                error=logging_setup.safe_error_text(e, f"stopping instance {instance_row['slug']}")))

    # ۲) لاین صدا
    line_slug = instance_row["audio_line"] or instance_row["slug"]
    try:
        done["line_removed"] = audio_lines.destroy_line(line_slug)
    except Exception as e:
        done["errors"].append(i18n.t(
            "provision_line_remove_failed",
            error=logging_setup.safe_error_text(e, f"destroying line for {instance_row['slug']}")))

    group_dir, bot_dir = instance_dirs(instance_row)

    # فایل لایسنس: وقتی دیتا می‌مونه (مهلت تمدید)، فایل رو *به‌روز* می‌کنیم
    # نه پاک -- تا وضعیت «منقضی، N روز مهلت» توی خود ربات دیده بشه و
    # دستورهای مهلت کار کنن. فقط وقتی دیتا پاک می‌شه، فایل هم می‌ره.
    if purge_data:
        try:
            licenses.remove_license_file(bot_dir)
        except OSError:
            pass
    else:
        try:
            license_row = db.get_license(int(instance_row["license_id"]))
            if license_row is not None and os.path.isdir(bot_dir):
                licenses.write_license_file(bot_dir, license_row, instance_row)
        except OSError:
            logging_setup.log_exception(f"updating license file for {instance_row['slug']}")

    # ۳) دیتا
    if purge_data:
        try:
            if os.path.isdir(bot_dir):
                shutil.rmtree(bot_dir, ignore_errors=False)
                done["data_removed"] = True
            _remove_group_if_empty(group_dir)
        except OSError as e:
            done["errors"].append(i18n.t(
                "provision_data_remove_failed",
                error=logging_setup.safe_error_text(e, f"purging data for {instance_row['slug']}")))

    db.update_instance(instance_id,
                       status="removed" if purge_data else "stopped",
                       pid=None,
                       removed_at=int(time.time()) if purge_data else None)
    db.log_event("instance_deprovisioned", license_id=int(instance_row["license_id"]),
                 detail={"slug": instance_row["slug"], "purge": bool(purge_data), **done})
    return done


def _remove_group_if_empty(group_dir):
    """
    اگه بعد از حذف یه ربات، هیچ رباتی توی اون سرور نمونده، پوشه‌ی سرور هم
    پاک می‌شه. چک «هیچ زیرپوشه‌ی رباتی نمونده» لازمه، وگرنه با حذف یه ربات
    از یه سرور دو-رباته، ربات دومی هم بی‌کانفیگ می‌شد.
    """
    if not os.path.isdir(group_dir):
        return False
    for name in os.listdir(group_dir):
        if os.path.isfile(os.path.join(group_dir, name, "identity.json")):
            return False
    shutil.rmtree(group_dir, ignore_errors=True)
    return True


def deactivate_license(db, license_id, purge_data=False, supervisor=None, reason=""):
    """
    غیرفعال‌سازی کامل یه لایسنس: همه‌ی نمونه‌هاش خاموش، لاین‌هاشون حذف، و
    (اگه purge_data) دیتاشون پاک می‌شه.
    """
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ProvisioningError(f"licence {license_id} not found")

    results = []
    for instance in db.instances_by_license(license_id, include_removed=False):
        results.append({
            "slug": instance["slug"],
            **deprovision_instance(db, instance, purge_data=purge_data, supervisor=supervisor),
        })

    db.log_event("license_deactivated", user_id=int(license_row["user_id"]),
                 license_id=license_id,
                 detail={"reason": reason, "purge": bool(purge_data), "instances": results})
    return results


def delete_license_completely(db, license_id, supervisor=None, reason="", by=None):
    """
    پاک‌کردنِ کاملِ یه لایسنس: ربات‌ها خاموش، لاین آزاد، دیتا پاک، بعد ردیف‌های
    دیتابیس. هم دکمه‌ی «🗑 حذف لایسنس» ادمین هم پاکسازی (gc) همین رو صدا می‌زنن.

    خروجی: (license_row, results, errors). جدول events دست‌نخورده می‌مونه.
    """
    license_row = db.get_license(license_id)
    if license_row is None:
        raise ProvisioningError(f"licence {license_id} not found")
    results = deactivate_license(db, license_id, True, supervisor, reason or "deleted")
    errors = [e for item in results for e in item.get("errors", [])]
    db.log_event("license_deleted", user_id=int(license_row["user_id"]), license_id=license_id,
                 detail={"by": by, "key": license_row["key"], "instances": len(results),
                         "errors": errors, "reason": reason})
    db.delete_license(license_id)
    return license_row, results, errors


def capacity_report(db):
    """
    چقدر جا داریم؟ برای پاسخ به «الان می‌تونم ربات جدید بفروشم یا نه».
    """
    lines = audio_lines.list_lines()
    report = {
        "backend": audio_lines.backend(),
        "manageable": audio_lines.backend_is_manageable(),
        "lines_total": len(lines),
        "lines_dead": sum(1 for line in lines if not line.get("alive")),
        "instances": db.stats()["instances_total"],
        "running": db.stats()["instances_running"],
        "free_windows_lines": None,
    }
    if report["backend"] == "windows":
        taken = {line.get("cable_key") for line in lines if line.get("cable_key")}
        keys = set()
        for name, description in audio_lines.list_output_devices():
            key = audio_lines._windows_cable_key(description) or audio_lines._windows_cable_key(name)
            if key:
                keys.add(key)
        report["free_windows_lines"] = len(keys - taken)
    return report
