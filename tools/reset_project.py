#!/usr/bin/env python3
"""
ریستِ پروژه به حالت «آماده‌ی ارسال به سرور».

  python tools/reset_project.py                 گزارش (dry-run)؛ هیچ‌چیز پاک نمی‌شه
  python tools/reset_project.py --apply         بکاپ می‌گیره، تأیید تایپی می‌خواد، پاک می‌کنه
  python tools/reset_project.py --check-clean   آماده‌ی ارسال هست؟ (کد خروج ۰ / ۱)

گزینه‌ها:
  --yes               تأیید تایپی رو رد می‌کنه (برای اسکریپت‌ها)
  --only a,b          فقط این دسته‌ها
  --keep-config       کانفیگ پلتفرم (config.json، catalog.json، settings و کدهای
                      تخفیف داخل دیتابیس) دست نخوره
  --keep-licensing-db دیتابیس لایسنس و رسیدها دست نخوره
  --include-bin       بایناری‌های bin/ و tesseract/ هم پاک بشن (پیش‌فرض: هرگز)
  --root DIR          ریشه‌ی پروژه (پیش‌فرض: پوشه‌ی بالاتر از این فایل)

قاعده‌های سخت (هیچ گزینه‌ای خاموششون نمی‌کنه):
  * goldenFriends/ (ربات فروخته‌شده) و لایسنس TT-EQ4F-2V6D-AWFF لمس نمی‌شن.
  * لایسنس‌های محافظت‌شده (همون منطق licensing/gc.py) با ردیف، سفارش، نمونه و
    پوشه‌ی دیتاشون سالم می‌مونن؛ بقیه‌ی ردیف‌ها پاک می‌شن.
  * فایل‌های tracked گیت هرگز پاک نمی‌شن.
  * قبل از هر پاک‌کردن، بکاپ zip زیر _reset_backups/ ساخته می‌شه.
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
SELF_ROOT = os.path.dirname(HERE)
if SELF_ROOT not in sys.path:
    sys.path.insert(0, SELF_ROOT)

# فایل‌هایی که نشون می‌دن این پوشه واقعاً ریشه‌ی پروژه‌ست.
MARKERS = ("manage.py", os.path.join("licensing", "gc.py"), os.path.join("core", "paths.py"))

BACKUP_DIR = "_reset_backups"
CONFIRM_WORD = "RESET"

CATEGORIES = ("bots", "licensing-db", "receipts", "config", "logs",
              "caches", "build", "leftovers", "bin")
#: دسته‌هایی که پیش‌فرض اجرا می‌شن (bin فقط با --include-bin).
DEFAULT_CATEGORIES = tuple(c for c in CATEGORIES if c != "bin")
#: دسته‌هایی که دوباره ساخته‌شدنیِ بی‌دردسرن؛ توی zip بکاپ نمی‌رن.
NO_BACKUP = {"caches", "build", "bin"}

#: زیرمجموعه‌هایی که هیچ‌وقت لمس نمی‌شن.
FORBIDDEN_TOP = {"goldenFriends", ".git", ".claude", BACKUP_DIR}

CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
SKIP_WALK = FORBIDDEN_TOP | {"bin", "tesseract", "data", "node_modules", ".venv", "venv"}
LEFTOVER_NAMES = ("token.txt", "create_and_push.bat", "e2esrv", "nul", ".env")
LEFTOVER_SUFFIX = (".tmp", ".bak", ".log")
SECRET_HINTS = ("token", "password", "secret", "api_key", "private")


@dataclass
class Item:
    category: str
    label: str
    size: int
    kind: str = "path"            # path | db | audio | config
    paths: list = field(default_factory=list)   # مسیرهای مطلق برای پاک‌کردن/بکاپ
    meta: dict = field(default_factory=dict)


@dataclass
class Plan:
    items: list
    notes: list


class ResetError(Exception):
    pass


# ------------------------------------------------------------------ کمکی

def _gc():
    from licensing import gc
    return gc


def is_project_root(root):
    return all(os.path.isfile(os.path.join(root, m)) for m in MARKERS)


def _rel(root, path):
    return os.path.relpath(path, root).replace(os.sep, "/")


def _size(path):
    return _gc()._tree_size(path) if os.path.lexists(path) else 0


def _forbidden(root, path, include_bin=False):
    """مسیر توی ناحیه‌ی ممنوع هست؟ (goldenFriends، .git، بکاپ‌ها، bin)"""
    parts = _rel(root, os.path.realpath(path)).split("/")
    top = parts[0]
    if top in FORBIDDEN_TOP or top == "..":
        return True
    if top in ("bin", "tesseract") and not include_bin:
        return True
    return False


def tracked_files(root):
    """فایل‌های tracked گیت (مسیر نسبی)؛ بدون گیت/مخزن، مجموعه‌ی خالی."""
    if not os.path.exists(os.path.join(root, ".git")):
        return set()
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True,
                             timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {p for p in out.decode("utf-8", "replace").split("\0") if p}


def _has_tracked(root, path, tracked):
    rel = _rel(root, path)
    prefix = rel + "/"
    return rel in tracked or any(t.startswith(prefix) for t in tracked)


@contextmanager
def _config_of(root):
    """licensing.config رو موقتاً روی کانفیگِ *این* ریشه می‌بره تا gc همون رو ببینه."""
    from licensing import config
    saved = config.CONFIG_FILE
    config.CONFIG_FILE = os.path.join(root, "data", "licensing", "config.json")
    config.reload()
    try:
        yield config
    finally:
        config.CONFIG_FILE = saved
        config.reload()


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ دیتابیس

def _snapshot_db(db_path, dest):
    """کپیِ سازگار از دیتابیس (WAL هم لحاظ می‌شه)؛ برای dry-run و بکاپ."""
    # فایل‌های اصلی رو باز نمی‌کنیم (باز کردنِ WAL ممکنه -shm بسازه)؛ اول کپی،
    # بعد از روی کپی یه فایل یکدست می‌سازیم.
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work.sqlite3")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                shutil.copy2(db_path + suffix, work + suffix)
        src = sqlite3.connect(work)
        try:
            dst = sqlite3.connect(dest)
            with dst:
                src.backup(dst)
            dst.close()
        finally:
            src.close()


def _in(ids):
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


def db_statements(keep_lic, keep_orders, keep_users, keep_config):
    """(جدول، شرطِ WHERE برای ردیف‌های *قابل‌حذف*). ترتیب مهمه: users آخر."""
    stmts = [
        ("instances", f"license_id NOT IN {_in(keep_lic)}"),
        ("licenses", f"id NOT IN {_in(keep_lic)}"),
        ("orders", f"id NOT IN {_in(keep_orders)}"),
        ("tickets", f"user_id NOT IN {_in(keep_users)}"),
        ("promo_redemptions", f"user_id NOT IN {_in(keep_users)}"),
        ("events", f"license_id IS NULL OR license_id NOT IN {_in(keep_lic)}"),
        ("users", f"telegram_id NOT IN {_in(keep_users)}"),
    ]
    if not keep_config:
        stmts += [("promo_codes", "1"), ("settings", "1")]
    return stmts


def plan_db(conn, keep_config):
    """
    با یه اتصال به دیتابیس (یا کپیش): چی می‌مونه و چی پاک می‌شه.
    خروجی: (شمارش حذف‌ها {table: n}، مجموعه‌ی نگه‌داشته‌ها، ردیف‌های محافظت‌شده)
    منطق «محافظت‌شده» از licensing/gc.py می‌آد.
    """
    gc = _gc()
    conn.row_factory = sqlite3.Row
    licences = list(conn.execute("SELECT * FROM licenses"))
    protected = [r for r in licences if gc.is_protected(r)]
    keep_lic = {int(r["id"]) for r in protected}
    keep_users = {int(r["user_id"]) for r in protected}
    keep_orders = {int(r["order_id"]) for r in protected if r["order_id"]}
    if keep_lic:
        keep_orders |= {int(r["id"]) for r in conn.execute(
            f"SELECT id FROM orders WHERE license_id IN {_in(keep_lic)}")}
    if keep_orders:
        keep_users |= {int(r["user_id"]) for r in conn.execute(
            f"SELECT user_id FROM orders WHERE id IN {_in(keep_orders)}")}
    counts = {}
    for table, where in db_statements(keep_lic, keep_orders, keep_users, keep_config):
        n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        if n:
            counts[table] = n
    return counts, {"lic": keep_lic, "orders": keep_orders, "users": keep_users}, protected


def _protected_instances(conn, protected_ids):
    if not protected_ids:
        return []
    return list(conn.execute(
        f"SELECT * FROM instances WHERE license_id IN {_in(protected_ids)}"))


def _apply_db(db_path, keep_config):
    with _config_of(os.path.dirname(os.path.dirname(os.path.dirname(db_path)))):
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            _counts, keep, _prot = plan_db(conn, keep_config)
            with conn:
                for table, where in db_statements(keep["lic"], keep["orders"], keep["users"], keep_config):
                    conn.execute(f"DELETE FROM {table} WHERE {where}")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("VACUUM")
        finally:
            conn.close()


# ------------------------------------------------------------------ planning

def build_plan(root, categories=DEFAULT_CATEGORIES, keep_config=False, keep_db=False,
               include_bin=False):
    """فقط می‌خونه؛ هیچ‌چیز رو تغییر نمی‌ده."""
    cats = set(categories)
    if keep_db:
        cats -= {"licensing-db", "receipts"}
    if keep_config:
        cats -= {"config"}
    if include_bin:
        cats.add("bin")
    tracked = tracked_files(root)
    items, notes = [], []
    lic_dir = os.path.join(root, "data", "licensing")
    db_path = os.path.join(lic_dir, "licensing.sqlite3")

    keep_dirs, keep_lines, keep_orders = set(), set(), set()
    with _config_of(root) as cfg:
        gc = _gc()
        protected_keys = set(gc._HARD_PROTECTED) | {
            str(k).strip().upper() for k in (cfg.get("protected_licences") or [])}
        protected_ids = set()
        if os.path.isfile(db_path):
            with tempfile.TemporaryDirectory() as tmp:
                snap = os.path.join(tmp, "snap.sqlite3")
                _snapshot_db(db_path, snap)
                conn = sqlite3.connect(snap)
                try:
                    counts, keep, protected = plan_db(conn, keep_config)
                    protected_ids = keep["lic"]
                    keep_orders = keep["orders"]
                    for inst in _protected_instances(conn, protected_ids):
                        keep_dirs.add(gc.instance_dirs(inst, None))
                        keep_lines |= {inst["slug"], inst["audio_line"] or inst["slug"]}
                    receipts_kept = {os.path.basename(str(r[0])) for r in conn.execute(
                        f"SELECT receipt_path FROM orders WHERE id IN {_in(keep_orders)} "
                        "AND receipt_path IS NOT NULL")} if keep_orders else set()
                finally:
                    conn.close()
            if "licensing-db" in cats and counts:
                detail = "، ".join(f"{t}:{n}" for t, n in sorted(counts.items()))
                items.append(Item("licensing-db", f"ردیف‌های دیتابیس لایسنس ({detail})",
                                  0, "db", [db_path], {"counts": counts}))
            if protected:
                notes.append("لایسنس محافظت‌شده (نگه داشته می‌شه): "
                             + ", ".join(sorted(r["key"] for r in protected)))
        else:
            receipts_kept = set()

        if "bots" in cats:
            items += _plan_bots(root, keep_dirs, keep_lines, protected_keys, gc)
        if "receipts" in cats:
            rdir = os.path.join(lic_dir, "receipts")
            for name in sorted(os.listdir(rdir)) if os.path.isdir(rdir) else ():
                path = os.path.join(rdir, name)
                if name not in receipts_kept and os.path.isfile(path):
                    items.append(Item("receipts", f"data/licensing/receipts/{name}",
                                      _size(path), paths=[path]))
        if "config" in cats:
            items += _plan_config(root, lic_dir, cfg)

    if "logs" in cats:
        edir = os.path.join(root, "errors")
        for name in sorted(os.listdir(edir)) if os.path.isdir(edir) else ():
            path = os.path.join(edir, name)
            items.append(Item("logs", f"errors/{name}", _size(path), paths=[path]))
    if "caches" in cats:
        items += _plan_caches(root)
    if "build" in cats:
        items += _plan_build(root)
    if "leftovers" in cats:
        items += _plan_leftovers(root)
    if "bin" in cats:
        for name in ("bin", "tesseract"):
            base = os.path.join(root, name)
            for entry in sorted(os.listdir(base)) if os.path.isdir(base) else ():
                path = os.path.join(base, entry)
                items.append(Item("bin", f"{name}/{entry}", _size(path), paths=[path]))

    keys_dir = os.path.join(lic_dir, "keys")
    if os.path.isdir(keys_dir):
        notes.append("data/licensing/keys/ (کلید امضا) عمداً لمس نمی‌شه؛ اگه لایسنس‌های "
                     "قبلی باید معتبر بمونن، همین کلید رو با پروژه ببر.")
    items = _drop_unsafe(root, items, tracked, include_bin, notes)
    return Plan(items, notes)


def _plan_bots(root, keep_dirs, keep_lines, protected_keys, gc):
    """data/ به‌جز licensing/: هر چیزی جز پوشه‌ی ربات‌های محافظت‌شده."""
    items = []
    data = os.path.join(root, "data")
    if not os.path.isdir(data):
        return items
    for name in sorted(os.listdir(data)):
        path = os.path.join(data, name)
        if name == "licensing":
            continue
        if name == "_audio_lines.json":
            item = _plan_audio(path, keep_lines)
            if item:
                items.append(item)
            continue
        if not os.path.isdir(path) or os.path.islink(path):
            items.append(Item("bots", f"data/{name}", _size(path), paths=[path]))
            continue
        kept_bots = [b for b in os.listdir(path) if os.path.isdir(os.path.join(path, b))
                     and ((name, b) in keep_dirs or gc.mentions_protected(os.path.join(path, b)))]
        if not kept_bots:
            items.append(Item("bots", f"data/{name}/", _size(path), paths=[path]))
            continue
        # گروهی که ربات محافظت‌شده داره: فقط بقیه‌ی بچه‌هاش پاک می‌شن.
        for child in sorted(os.listdir(path)):
            cpath = os.path.join(path, child)
            # فقط پوشه‌ی رباتِ غیرمحافظت‌شده؛ فایل‌ها و cookies/ی سطحِ گروه (که
            # ربات محافظت‌شده ممکنه ازشون استفاده کنه) سر جاشون می‌مونن.
            if child in kept_bots or not os.path.isfile(os.path.join(cpath, "identity.json")):
                continue
            items.append(Item("bots", f"data/{name}/{child}", _size(cpath), paths=[cpath]))
    return items


def _plan_audio(path, keep_lines):
    state = _read_json(path)
    lines = state.get("lines") if isinstance(state.get("lines"), dict) else {}
    drop = [s for s, v in lines.items()
            if s not in keep_lines and str((v or {}).get("owner", "")).split("/")[-1] not in keep_lines]
    if not drop and lines:
        return None
    return Item("bots", f"data/_audio_lines.json ({len(drop)} لاین)", _size(path), "audio",
                [path], {"drop": drop, "all": len(lines)})


def _plan_config(root, lic_dir, cfg):
    items = []
    cfg_path = os.path.join(lic_dir, "config.json")
    data = _read_json(cfg_path)
    extra = {k for k in data if k != "protected_licences"}
    if extra or (os.path.isfile(cfg_path) and not data):
        secrets = sorted(k for k in extra if any(h in k.lower() for h in SECRET_HINTS)
                         and isinstance(data[k], str) and data[k])
        note = f" (شامل: {', '.join(secrets)})" if secrets else ""
        items.append(Item("config", "data/licensing/config.json" + note, _size(cfg_path),
                          "config", [cfg_path], {"keep": {"protected_licences": data["protected_licences"]}
                                                 if data.get("protected_licences") else {}}))
    cat = os.path.join(lic_dir, "catalog.json")
    if os.path.isfile(cat):
        items.append(Item("config", "data/licensing/catalog.json", _size(cat), paths=[cat]))
    return items


def _walk(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not (base == root and d in SKIP_WALK)
                   and not (base == root and d == "dist")
                   and not (d == "_work" and os.path.basename(base) == "build")
                   and not os.path.islink(os.path.join(base, d))]
        yield base, dirs, files


def _plan_caches(root):
    items = []
    for base, dirs, files in _walk(root):
        for d in [d for d in dirs if d in CACHE_DIRS]:
            path = os.path.join(base, d)
            items.append(Item("caches", _rel(root, path) + "/", _size(path), paths=[path]))
            dirs.remove(d)
        for f in files:
            if f.endswith((".pyc", ".pyo")):
                path = os.path.join(base, f)
                items.append(Item("caches", _rel(root, path), _size(path), paths=[path]))
    return items


def _plan_build(root):
    items = []
    for rel in ("dist", os.path.join("build", "_work"), ".wrangler", os.path.join("deploy", ".wrangler")):
        path = os.path.join(root, rel)
        if os.path.lexists(path):
            items.append(Item("build", rel.replace(os.sep, "/") + "/", _size(path), paths=[path]))
    for name in sorted(os.listdir(root)):
        if name.endswith(".spec") and os.path.isfile(os.path.join(root, name)):
            items.append(Item("build", name, _size(os.path.join(root, name)),
                              paths=[os.path.join(root, name)]))
    return items


def _plan_leftovers(root):
    items = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if name in LEFTOVER_NAMES or (name.endswith(LEFTOVER_SUFFIX) and os.path.isfile(path)):
            items.append(Item("leftovers", name + ("/" if os.path.isdir(path) else ""),
                              _size(path), paths=[path]))
    return items


def _drop_unsafe(root, items, tracked, include_bin, notes):
    """ناحیه‌ی ممنوع، symlink خارج از پروژه و فایل‌های tracked رو از برنامه بیرون می‌ندازه."""
    gc = _gc()
    safe = []
    for item in items:
        if item.kind == "db":
            safe.append(item)
            continue
        ok = []
        for path in item.paths:
            if _forbidden(root, path, include_bin):
                continue
            if _has_tracked(root, path, tracked):
                notes.append(f"tracked در گیت، رد شد: {_rel(root, path)}")
                continue
            if item.kind == "path" and not gc._under(root, path):
                continue
            ok.append(path)
        if ok:
            item.paths = ok
            safe.append(item)
    return safe


# ------------------------------------------------------------------ اجرا

def make_backup(root, plan):
    """zip از همه‌چیزِ قابل‌پاک‌شدن (به‌جز دسته‌های دوباره‌ساخته‌شدنی). مسیر zip رو برمی‌گردونه."""
    backup_dir = os.path.join(root, BACKUP_DIR)
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(backup_dir, f"reset-{stamp}.zip")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(backup_dir, f"reset-{stamp}-{n}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf, tempfile.TemporaryDirectory() as tmp:
        for item in plan.items:
            if item.category in NO_BACKUP:
                continue
            for src in item.paths:
                if item.kind == "db":
                    snap = os.path.join(tmp, "snap.sqlite3")
                    _snapshot_db(src, snap)
                    zf.write(snap, _rel(root, src))
                    continue
                if os.path.isdir(src):
                    for base, _d, files in os.walk(src):
                        for f in files:
                            full = os.path.join(base, f)
                            zf.write(full, _rel(root, full))
                elif os.path.isfile(src):
                    zf.write(src, _rel(root, src))
    return path


def _remove(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def apply_plan(root, plan, keep_config=False):
    """پاک‌کردن. خروجی: تعداد خطا."""
    errors = 0
    for item in plan.items:
        try:
            if item.kind == "db":
                _apply_db(item.paths[0], keep_config)
            elif item.kind == "audio":
                path = item.paths[0]
                state = _read_json(path)
                left = {s: v for s, v in state.get("lines", {}).items() if s not in item.meta["drop"]}
                if left:
                    state["lines"] = left
                    _write_json(path, state)
                else:
                    _remove(path)
            elif item.kind == "config":
                path = item.paths[0]
                if item.meta["keep"]:
                    _write_json(path, item.meta["keep"])
                else:
                    _remove(path)
            else:
                for path in item.paths:
                    _remove(path)
        except (OSError, sqlite3.Error) as e:
            errors += 1
            print(f"  خطا در «{item.label}»: {e}")
    return errors


def _fmt(n):
    return _gc().fmt_size(n)


def print_plan(plan):
    for cat in CATEGORIES:
        group = [i for i in plan.items if i.category == cat]
        if not group:
            continue
        print(f"\n[{cat}]  {len(group)} مورد  {_fmt(sum(i.size for i in group))}")
        for i in group:
            print(f"   - {i.label}  {_fmt(i.size) if i.size else ''}".rstrip())
    for note in plan.notes:
        print(f"\n(توجه) {note}")


def parse_args(argv):
    p = argparse.ArgumentParser(description="ریستِ پروژه به حالت آماده‌ی ارسال به سرور")
    p.add_argument("--apply", action="store_true", help="واقعاً پاک کن (پیش‌فرض: فقط گزارش)")
    p.add_argument("--yes", action="store_true", help="تأیید تایپی نخواه")
    p.add_argument("--check-clean", action="store_true", help="فقط بررسی آماده‌بودن؛ کد خروج ۰/۱")
    p.add_argument("--only", default="", help="دسته‌ها، با کاما: " + ",".join(CATEGORIES))
    p.add_argument("--keep-config", action="store_true")
    p.add_argument("--keep-licensing-db", action="store_true")
    p.add_argument("--include-bin", action="store_true")
    p.add_argument("--root", default=SELF_ROOT)
    return p.parse_args(argv)


def main(argv=None, input_fn=input):
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    if not is_project_root(root):
        print(f"این پوشه ریشه‌ی پروژه نیست (فایل‌های نشانه پیدا نشد): {root}")
        return 2
    only = tuple(c for c in args.only.split(",") if c)
    unknown = set(only) - set(CATEGORIES)
    if unknown:
        print("دسته‌ی ناشناس: " + ", ".join(sorted(unknown)) + "\nمجاز: " + ", ".join(CATEGORIES))
        return 2
    cats = only or DEFAULT_CATEGORIES
    plan = build_plan(root, cats, args.keep_config, args.keep_licensing_db, args.include_bin)

    if args.check_clean:
        if plan.items:
            print("پروژه آماده‌ی ارسال نیست؛ این موارد باقی مونده:")
            print_plan(plan)
            return 1
        print("پروژه تمیز و آماده‌ی ارسال به سرور هست.")
        for note in plan.notes:
            print(f"(توجه) {note}")
        return 0

    print_plan(plan)
    total = sum(i.size for i in plan.items)
    print(f"\nجمع: {len(plan.items)} مورد، {_fmt(total)}")
    if not args.apply:
        print("(فقط گزارش؛ چیزی پاک نشد. برای اجرای واقعی --apply بزن)")
        return 0
    if not plan.items:
        print("چیزی برای پاک‌کردن نیست.")
        return 0
    if not args.yes:
        print("\nاین کار برگشت‌ناپذیره (به‌جز از روی بکاپ). سرور لایسنس و ربات‌ها باید خاموش باشن.")
        if input_fn(f"برای ادامه {CONFIRM_WORD} تایپ کن: ").strip() != CONFIRM_WORD:
            print("لغو شد.")
            return 1
    backup = make_backup(root, plan)
    print(f"\nبکاپ ساخته شد: {backup}")
    errors = apply_plan(root, plan, args.keep_config)
    print(f"انجام شد. خطا: {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
