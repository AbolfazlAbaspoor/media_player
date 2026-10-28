"""
پاکسازی (garbage collect) پسماندِ ربات‌ها و لایسنس‌ها.

دو فاز جدا:
  scan()  فقط می‌خونه و گزارشِ «کاندیدها» رو می‌سازه (هیچ‌چیز پاک نمی‌شه).
  apply() انتخاب رو می‌گیره، *دوباره* اسکن می‌کنه و فقط کاندیدهایی رو پاک
          می‌کنه که هم انتخاب شدن هم هنوز امنِ پاک‌کردنن -- پس یه شناسه‌ی
          دستکاری‌شده یا کهنه هیچ‌وقت چیزِ اضافه‌ای پاک نمی‌کنه.

هم manage.py هم ربات فروش همین ماژول رو صدا می‌زنن.

قاعده‌های ثابت (هیچ گزینه‌ای اون‌ها رو خاموش نمی‌کنه):
  * لایسنسِ محافظت‌شده (`protected_licences`، و TT-EQ4F که فروخته شده)،
    لایسنسِ owner و «admin unlimited» و هر لایسنسِ active/paused/suspended
    هیچ‌وقت کاندید نمی‌شن.
  * هر مسیر قبل از پاک‌شدن باید زیرِ ریشه‌ی مجازش باشه (resolve) و
    symlink نباشه.
  * keys/، config.json، خودِ دیتابیس و _machine_id هیچ‌وقت لمس نمی‌شن.
"""

import os
import re
import shutil
import time
from dataclasses import dataclass, field

from core import audio_lines
from core import config_defaults
from core import logging_setup
from licensing import config
from licensing import licenses
from licensing import provisioning

DAY = 86400

#: ترتیبِ نمایش دسته‌ها.
CATEGORIES = ("instances", "folders", "lines", "licenses", "orders",
              "receipts", "events", "logs", "temp", "downloads")

#: لایسنسِ فروخته‌شده؛ حتی اگه کانفیگ محلی گم بشه، پاک نمی‌شه.
_HARD_PROTECTED = {"TT-EQ4F-2V6D-AWFF"}

_STALE_ORDER_STATUSES = ("pending", "awaiting_receipt", "rejected", "cancelled", "expired")
_LIVE_LICENCE_STATUSES = ("active", "paused", "suspended")
_GROUP_RE = re.compile(r"^.+_\d+$")


@dataclass
class Options:
    retention_days: int = 30          # نمونه‌ی حذف‌شده/گم‌شده
    license_days: int = 90            # لایسنس بعد از مهلت / لغو
    order_days: int = 30
    event_days: int = 180
    delete_events: bool = False       # audit trail: پیش‌فرض فقط گزارش
    log_days: int = 30
    download_days: int = 7
    orphan_min_age_days: int = 1      # پوشه‌ی تازه‌ساخته دست نمی‌خوره
    errors_dir: str = None
    receipts_dir: str = None
    categories: tuple = None          # None = همه


@dataclass
class Candidate:
    id: str
    category: str
    label: str
    size: int
    reason: str
    deletable: bool = True
    meta: dict = field(default_factory=dict)


@dataclass
class Report:
    items: dict            # category -> [Candidate]
    attention: list        # Candidateهای غیرقابل‌حذف که نیاز به نگاه ادمین دارن

    def all(self):
        return [c for cat in CATEGORIES for c in self.items.get(cat, [])]

    def deletable(self, category=None):
        return [c for c in self.all()
                if c.deletable and (category is None or c.category == category)]

    def total_size(self):
        return sum(c.size for c in self.deletable())


def default_options():
    opts = Options()
    days = config.get("gc_retention_days")
    if days:
        opts.retention_days = int(days)
    opts.errors_dir = logging_setup.ERRORS_DIR
    return opts


# ------------------------------------------------------------------ کمکی

def _under(root, path):
    """آیا path (بعد از resolve) واقعاً زیرِ root هست و symlink نیست؟"""
    if os.path.islink(path):
        return False
    root_r = os.path.realpath(root)
    path_r = os.path.realpath(path)
    return path_r != root_r and os.path.commonpath([root_r, path_r]) == root_r


def _tree_size(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return time.time()


def _is_protected(row):
    key = str(row["key"] or "").strip().upper()
    return (key in _HARD_PROTECTED or config.is_protected_licence(key)
            or licenses.is_unlimited(row))


#: نام عمومی برای ابزارهای بیرونی (tools/reset_project.py) تا منطقِ «محافظت‌شده»
#: جای دیگه‌ای کپی نشه.
is_protected = _is_protected


def _instance_dirs(row, data_dir):
    group = row["group_name"] or config_defaults.server_folder_name(row["tt_host"], row["tt_port"])
    bot = row["bot_name"] or config_defaults.safe_bot_folder_name(row["slug"])
    return group, bot


def fmt_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024


def _wanted(options, category):
    return options.categories is None or category in options.categories


# ------------------------------------------------------------------ scan

def scan(db, data_dir, now=None, options=None):
    now = int(now if now is not None else time.time())
    options = options or default_options()
    if options.errors_dir is None:
        options.errors_dir = default_options().errors_dir
    receipts_dir = options.receipts_dir or os.path.join(data_dir, "licensing", "receipts")
    items = {c: [] for c in CATEGORIES}
    attention = []

    licences = {int(r["id"]): r for r in db.query("SELECT * FROM licenses")}
    instances = list(db.query("SELECT * FROM instances"))

    _scan_instances(instances, licences, now, options, items, attention)
    _scan_folders(instances, data_dir, now, options, items)
    _scan_lines(instances, items)
    _scan_licences(licences, instances, now, options, items)
    _scan_orders(db, receipts_dir, now, options, items)
    _scan_receipts(db, receipts_dir, now, items)
    _scan_events(db, now, options, items)
    _scan_logs(options, now, items)
    _scan_temp(data_dir, now, items)
    _scan_downloads(data_dir, now, options, items)

    for cat in CATEGORIES:
        if not _wanted(options, cat):
            items[cat] = []
    return Report(items, attention)


def _scan_instances(instances, licences, now, options, items, attention):
    cutoff = now - options.retention_days * DAY
    for row in instances:
        if row["status"] not in ("removed", "missing"):
            continue
        lic = licences.get(int(row["license_id"]))
        if lic is not None and _is_protected(lic):
            continue
        when = int(row["removed_at"] or row["updated_at"] or 0)
        label = f"#{row['id']} {row['slug']} ({row['status']})"
        live = lic is not None and lic["status"] in _LIVE_LICENCE_STATUSES
        if row["status"] == "missing" and live:
            attention.append(Candidate(
                f"inst:{row['id']}", "instances", label, 0,
                "missing_active_licence", deletable=False,
                meta={"instance_id": int(row["id"]), "license_id": int(lic["id"])}))
            continue
        if when > cutoff:
            continue
        reason = "removed" if row["status"] == "removed" else "missing_dead_licence"
        items["instances"].append(Candidate(
            f"inst:{row['id']}", "instances", label, 0, reason,
            meta={"instance_id": int(row["id"])}))


def _scan_folders(instances, data_dir, now, options, items):
    known = {_instance_dirs(r, data_dir) for r in instances}
    groups_known = {g for g, _b in known}
    min_age = now - options.orphan_min_age_days * DAY
    if not os.path.isdir(data_dir):
        return
    for group in sorted(os.listdir(data_dir)):
        gdir = os.path.join(data_dir, group)
        if (group.startswith(("_", ".")) or group == "licensing"
                or not _GROUP_RE.match(group) or not os.path.isdir(gdir)
                or os.path.islink(gdir)):
            continue
        subdirs = [n for n in os.listdir(gdir) if os.path.isdir(os.path.join(gdir, n))]
        bots_left = 0
        for name in sorted(subdirs):
            bdir = os.path.join(gdir, name)
            ident = os.path.join(bdir, "identity.json")
            if os.path.islink(bdir) or not os.path.isfile(ident):
                bots_left += 1
                continue
            if (group, name) in known or _mtime(ident) > min_age or _mentions_protected(bdir):
                bots_left += 1
                continue
            items["folders"].append(Candidate(
                f"dir:{group}/{name}", "folders", f"{group}/{name}", _tree_size(bdir),
                "orphan_bot", meta={"path": bdir}))
        if not subdirs and group not in groups_known and _mtime(gdir) <= min_age:
            items["folders"].append(Candidate(
                f"dir:{group}", "folders", group, _tree_size(gdir),
                "empty_group", meta={"path": gdir}))


def _mentions_protected(bot_dir):
    """اگه license.json پوشه به یه لایسنسِ محافظت‌شده اشاره کنه، دست نمی‌زنیم."""
    try:
        with open(os.path.join(bot_dir, "license.json"), "r", encoding="utf-8") as f:
            text = f.read().upper()
    except OSError:
        return False
    keys = set(_HARD_PROTECTED) | {str(k).strip().upper() for k in (config.get("protected_licences") or [])}
    return any(k and k in text for k in keys)


mentions_protected = _mentions_protected
instance_dirs = _instance_dirs


def _scan_lines(instances, items):
    owners = set()
    for r in instances:
        if r["status"] == "removed":
            continue
        group, bot = _instance_dirs(r, None)
        owners.add(f"{group}/{bot}")
        owners.add(r["audio_line"] or r["slug"])
    for line in audio_lines.list_lines():
        owner = str(line.get("owner") or "")
        # فقط لاین‌هایی که provisioning ساخته ("group/bot"). لاینِ دستیِ ادمین یا
        # manage.py عمداً ساخته شده و «بی‌صاحب» حساب نمی‌شه.
        if "/" not in owner or owner in owners or line["slug"] in owners:
            continue
        items["lines"].append(Candidate(
            f"line:{line['slug']}", "lines", line["slug"], 0, "no_instance",
            meta={"slug": line["slug"]}))


def _scan_licences(licences, instances, now, options, items):
    grace = int(config.get("grace_days") or 0)
    live = {int(r["license_id"]) for r in instances if r["status"] not in ("removed", "missing")}
    for lic in licences.values():
        if _is_protected(lic) or lic["status"] in _LIVE_LICENCE_STATUSES or int(lic["id"]) in live:
            continue
        if lic["status"] == "expired":
            edge = int(lic["expires_at"]) + (grace + options.license_days) * DAY
            reason = "expired_long"
        elif lic["status"] == "revoked":
            edge = int(lic["deactivated_at"] or lic["updated_at"]) + options.license_days * DAY
            reason = "revoked_long"
        else:
            continue
        if edge < now:
            items["licenses"].append(Candidate(
                f"lic:{lic['id']}", "licenses", f"#{lic['id']} {lic['key']} ({lic['status']})",
                0, reason, meta={"license_id": int(lic["id"])}))


def _receipt_file(receipts_dir, order):
    name = os.path.basename(str(order["receipt_path"] or ""))
    path = os.path.join(receipts_dir, name) if name else None
    return path if path and os.path.isfile(path) else None


def _scan_orders(db, receipts_dir, now, options, items):
    marks = ",".join("?" * len(_STALE_ORDER_STATUSES))
    cutoff = now - options.order_days * DAY
    for o in db.query(
            f"SELECT * FROM orders WHERE status IN ({marks}) AND updated_at < ?",
            (*_STALE_ORDER_STATUSES, cutoff)):
        path = _receipt_file(receipts_dir, o)
        items["orders"].append(Candidate(
            f"order:{o['id']}", "orders", f"#{o['id']} ({o['status']})",
            _tree_size(path) if path else 0, "stale_order",
            meta={"order_id": int(o["id"]), "path": path}))


def _scan_receipts(db, receipts_dir, now, items):
    if not os.path.isdir(receipts_dir):
        return
    used = {os.path.basename(str(r["receipt_path"])) for r in
            db.query("SELECT receipt_path FROM orders WHERE receipt_path IS NOT NULL")}
    for name in sorted(os.listdir(receipts_dir)):
        path = os.path.join(receipts_dir, name)
        if name in used or not os.path.isfile(path) or _mtime(path) > now - DAY:
            continue
        items["receipts"].append(Candidate(
            f"rcpt:{name}", "receipts", name, _tree_size(path), "orphan_receipt",
            meta={"path": path}))


def _scan_events(db, now, options, items):
    cutoff = now - options.event_days * DAY
    row = db.query_one("SELECT COUNT(*) AS n FROM events WHERE ts < ?", (cutoff,))
    if row and row["n"]:
        items["events"].append(Candidate(
            "events:old", "events", f"{row['n']} events", 0, "old_events",
            deletable=options.delete_events, meta={"cutoff": cutoff}))


def _scan_logs(options, now, items):
    root = options.errors_dir
    if not root or not os.path.isdir(root):
        return
    cutoff = now - options.log_days * DAY
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.isfile(path) and _mtime(path) < cutoff:
            items["logs"].append(Candidate(
                f"log:{name}", "logs", name, _tree_size(path), "old_log", meta={"path": path}))


def _scan_temp(data_dir, now, items):
    if not os.path.isdir(data_dir):
        return
    for base, dirs, files in os.walk(data_dir):
        # licensing/ (کلیدها، کانفیگ، دیتابیس) کلاً بیرونِ این دسته‌ست.
        dirs[:] = [d for d in dirs
                   if not os.path.islink(os.path.join(base, d))
                   and not (base == data_dir and d in ("licensing", "_machine_id"))]
        for name in files:
            age_days = 1 if name.endswith(".tmp") else 7 if name.endswith(".bak") else None
            path = os.path.join(base, name)
            if age_days is None or _mtime(path) > now - age_days * DAY:
                continue
            rel = os.path.relpath(path, data_dir).replace(os.sep, "/")
            items["temp"].append(Candidate(
                f"tmp:{rel}", "temp", rel, _tree_size(path), "temp_file", meta={"path": path}))


def _scan_downloads(data_dir, now, options, items):
    if not os.path.isdir(data_dir):
        return
    cutoff = now - options.download_days * DAY
    for group in sorted(os.listdir(data_dir)):
        if group.startswith(("_", ".")) or group == "licensing" or not _GROUP_RE.match(group):
            continue
        gdir = os.path.join(data_dir, group)
        for bot in sorted(os.listdir(gdir)) if os.path.isdir(gdir) else ():
            ddir = os.path.join(gdir, bot, "downloads")
            if not os.path.isdir(ddir) or os.path.islink(ddir):
                continue
            old = [os.path.join(ddir, n) for n in os.listdir(ddir)
                   if os.path.isfile(os.path.join(ddir, n))
                   and _mtime(os.path.join(ddir, n)) < cutoff]
            if old:
                items["downloads"].append(Candidate(
                    f"dl:{group}/{bot}", "downloads", f"{group}/{bot} ({len(old)})",
                    sum(_tree_size(p) for p in old), "old_downloads",
                    meta={"files": old, "root": ddir, "cutoff": cutoff}))


# ------------------------------------------------------------------ apply

def _remove_path(root, path):
    """یه فایل یا پوشه رو فقط اگه زیرِ root باشه پاک می‌کنه. True اگه پاک شد."""
    if not path or not os.path.lexists(path) or not _under(root, path):
        return False
    if os.path.isdir(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
    return True


def apply(db, data_dir, selection, options=None, now=None, supervisor=None):
    """
    دقیقاً کاندیدهای انتخاب‌شده (و هنوز-امن) رو پاک می‌کنه.

    خروجی: {"deleted": {cat: n}, "freed": bytes, "errors": n, "skipped": [id]}
    """
    options = options or default_options()
    selection = set(selection)
    report = scan(db, data_dir, now=now, options=options)
    receipts_dir = options.receipts_dir or os.path.join(data_dir, "licensing", "receipts")
    result = {"deleted": {}, "freed": 0, "errors": 0,
              "skipped": sorted(selection - {c.id for c in report.deletable()})}

    for cand in report.deletable():
        if cand.id not in selection:
            continue
        try:
            freed = _apply_one(db, data_dir, receipts_dir, options, cand, supervisor)
        except Exception:
            logging_setup.log_exception(f"gc apply {cand.id}")
            result["errors"] += 1
            continue
        if freed is None:
            result["skipped"].append(cand.id)
            continue
        result["deleted"][cand.category] = result["deleted"].get(cand.category, 0) + 1
        result["freed"] += freed

    db.log_event("gc_applied", detail={"deleted": result["deleted"], "freed": result["freed"],
                                        "errors": result["errors"]})
    return result


def _apply_one(db, data_dir, receipts_dir, options, cand, supervisor):
    """اندازه‌ی آزادشده، یا None اگه چیزی پاک نشد."""
    cat, meta = cand.category, cand.meta
    if cat == "instances":
        db.delete_instance(meta["instance_id"])
    elif cat == "folders":
        if not _remove_path(data_dir, meta["path"]):
            return None
    elif cat == "lines":
        if not audio_lines.destroy_line(meta["slug"]):
            return None
    elif cat == "licenses":
        # همون هسته‌ی «🗑 حذف لایسنس» ادمین (خاموشی، لاین، دیتا، ردیف).
        provisioning.delete_license_completely(
            db, meta["license_id"], supervisor=supervisor, reason="gc")
    elif cat == "orders":
        if meta["path"]:
            _remove_path(receipts_dir, meta["path"])
        db.delete_order(meta["order_id"])
    elif cat in ("receipts", "temp"):
        if not _remove_path(receipts_dir if cat == "receipts" else data_dir, meta["path"]):
            return None
    elif cat == "logs":
        if not _remove_path(options.errors_dir, meta["path"]):
            return None
    elif cat == "events":
        db.delete_events_before(meta["cutoff"])
    elif cat == "downloads":
        n = 0
        for path in meta["files"]:
            if _mtime(path) < meta["cutoff"] and _remove_path(meta["root"], path):
                n += 1
        if not n:
            return None
    return cand.size
