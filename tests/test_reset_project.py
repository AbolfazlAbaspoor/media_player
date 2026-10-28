"""
tools/reset_project.py روی یه پروژه‌ی ساختگی توی پوشه‌ی موقت؛ به data/ واقعی
و به goldenFriends واقعی دست نمی‌زنه.
"""

import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout

from licensing import db as db_module
from tools import reset_project as rp

SOLD = "TT-EQ4F-2V6D-AWFF"
KEEP = "TT-KEEP-AAAA-BBBB"
NOW = 1_800_000_000


def _write(path, text="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ResetTests(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for marker in rp.MARKERS:
            _write(os.path.join(self.root, marker))
        # ماندگارها
        _write(self.p("bin", "ffmpeg.exe"), "binary")
        _write(self.p("goldenFriends", "rental.json"), SOLD)
        _write(self.p("goldenFriends", "data", "a.json"))
        _write(self.p("core", "mod.py"), "code")
        # پسماند
        _write(self.p("core", "__pycache__", "mod.pyc"))
        _write(self.p("errors", "errors.log"), "err")
        _write(self.p("dist", "app.exe"), "big")
        _write(self.p("build", "_work", "t.o"))
        _write(self.p("token.txt"), "secret")
        _write(self.p("create_and_push.bat"), "git push")
        _write(self.p("e2esrv", "x.txt"))
        _write(self.p("data", "_machine_id"), "abc")
        _write(self.p("data", "1.2.3.4_10333", "shared_config.json"))
        _write(self.p("data", "1.2.3.4_10333", "dead_1", "identity.json"), "{}")
        _write(self.p("data", "5.6.7.8_10333", "sold_1", "identity.json"), "{}")
        _write(self.p("data", "5.6.7.8_10333", "sold_1", "license.json"), json.dumps({"key": SOLD}))
        _write(self.p("data", "5.6.7.8_10333", "other_1", "identity.json"), "{}")
        _write(self.p("data", "licensing", "config.json"),
               json.dumps({"sales_bot_token": "123:ABC", "protected_licences": [KEEP]}))
        _write(self.p("data", "licensing", "catalog.json"), "{}")
        _write(self.p("data", "licensing", "keys", "private.key"), "k")
        _write(self.p("data", "licensing", "receipts", "keep.jpg"), "r1")
        _write(self.p("data", "licensing", "receipts", "drop.jpg"), "r2")
        _write(self.p("data", "_audio_lines.json"), json.dumps({"lines": {
            "sold_1": {"owner": "5.6.7.8_10333/sold_1"}, "dead_1": {"owner": "1.2.3.4_10333/dead_1"}}}))
        self._db()

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def _db(self):
        db = db_module.Database(self.p("data", "licensing", "licensing.sqlite3"))
        for uid in (1, 2):
            db.upsert_user(uid, f"u{uid}", "n")
        c = db.conn
        with c:
            c.execute("INSERT INTO orders (id,user_id,months,users,bots,amount_usd,status,receipt_path,created_at,updated_at)"
                      " VALUES (10,1,1,1,1,1,'approved','keep.jpg',1,1)")
            c.execute("INSERT INTO orders (id,user_id,months,users,bots,amount_usd,status,created_at,updated_at)"
                      " VALUES (11,2,1,1,1,1,'approved',1,1)")
            for lid, key, uid, oid in ((1, SOLD, 1, 10), (2, KEEP, 1, None), (3, "TT-DEAD-AAAA-BBBB", 2, 11)):
                c.execute("INSERT INTO licenses (id,key,user_id,order_id,starts_at,expires_at,status,created_at,updated_at)"
                          " VALUES (?,?,?,?,1,?,'active',1,1)", (lid, key, uid, oid, NOW))
            for iid, lid, slug, grp in ((1, 1, "sold_1", "5.6.7.8_10333"), (3, 3, "dead_1", "1.2.3.4_10333")):
                c.execute("INSERT INTO instances (id,license_id,slug,tt_host,group_name,bot_name,created_at,updated_at)"
                          " VALUES (?,?,?,?,?,?,1,1)", (iid, lid, slug, "h", grp, slug))
            c.execute("INSERT INTO events (ts,kind,license_id) VALUES (1,'a',1)")
            c.execute("INSERT INTO events (ts,kind,license_id) VALUES (1,'b',3)")
        db.close()

    def snapshot(self, sub):
        out = {}
        for base, _d, files in os.walk(self.p(sub)):
            for f in files:
                full = os.path.join(base, f)
                with open(full, "rb") as fh:
                    out[os.path.relpath(full, self.root)] = fh.read()
        return out

    def run_main(self, *args, root=None, answer="RESET"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rp.main(["--root", root or self.root, *args], input_fn=lambda _p: answer)
        return code, buf.getvalue()

    def rows(self, table):
        c = sqlite3.connect(self.p("data", "licensing", "licensing.sqlite3"))
        try:
            return c.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            c.close()

    def test_dry_run_touches_nothing(self):
        before = self.snapshot(".")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("فقط گزارش", out)
        self.assertEqual(before, self.snapshot("."))
        self.assertFalse(os.path.exists(self.p(rp.BACKUP_DIR)))

    def test_apply_removes_only_listed(self):
        gf_before = self.snapshot("goldenFriends")
        code, out = self.run_main("--apply", "--yes")
        self.assertEqual(code, 0, out)
        for gone in ("core/__pycache__", "errors/errors.log", "dist", "build/_work", "token.txt",
                     "create_and_push.bat", "e2esrv", "data/_machine_id",
                     "data/1.2.3.4_10333", "data/5.6.7.8_10333/other_1", "data/licensing/catalog.json",
                     "data/licensing/receipts/drop.jpg"):
            self.assertFalse(os.path.exists(self.p(*gone.split("/"))), gone)
        for kept in ("core/mod.py", "bin/ffmpeg.exe", "data/5.6.7.8_10333/sold_1/license.json",
                     "data/licensing/keys/private.key", "data/licensing/receipts/keep.jpg", "manage.py"):
            self.assertTrue(os.path.exists(self.p(*kept.split("/"))), kept)
        self.assertEqual(gf_before, self.snapshot("goldenFriends"))

    def test_protected_licence_rows_survive(self):
        self.run_main("--apply", "--yes")
        self.assertEqual({r[1] for r in self.rows("licenses")}, {SOLD, KEEP})
        self.assertEqual([r[0] for r in self.rows("instances")], [1])
        self.assertEqual([r[0] for r in self.rows("orders")], [10])
        self.assertEqual([r[0] for r in self.rows("users")], [1])
        self.assertEqual(len(self.rows("events")), 1)

    def test_config_secret_removed_but_protected_list_kept(self):
        self.run_main("--apply", "--yes")
        with open(self.p("data", "licensing", "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"protected_licences": [KEEP]})
        with open(self.p("data", "_audio_lines.json"), encoding="utf-8") as f:
            self.assertEqual(list(json.load(f)["lines"]), ["sold_1"])

    def test_backup_created_and_contains_removed(self):
        _code, out = self.run_main("--apply", "--yes")
        zips = os.listdir(self.p(rp.BACKUP_DIR))
        self.assertEqual(len(zips), 1)
        self.assertIn(zips[0], out)
        with zipfile.ZipFile(self.p(rp.BACKUP_DIR, zips[0])) as zf:
            names = set(zf.namelist())
        self.assertIn("token.txt", names)
        self.assertIn("data/licensing/licensing.sqlite3", names)
        self.assertIn("data/licensing/receipts/drop.jpg", names)
        self.assertFalse(any(n.startswith("goldenFriends") for n in names))

    def test_backup_dir_survives_second_reset(self):
        self.run_main("--apply", "--yes")
        _write(self.p("token.txt"))
        self.run_main("--apply", "--yes")
        self.assertEqual(len(os.listdir(self.p(rp.BACKUP_DIR))), 2)

    def test_refuses_outside_project_root(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        _write(os.path.join(empty, "token.txt"))
        code, _out = self.run_main("--apply", "--yes", root=empty)
        self.assertEqual(code, 2)
        self.assertTrue(os.path.exists(os.path.join(empty, "token.txt")))

    def test_wrong_confirmation_aborts(self):
        code, _out = self.run_main("--apply", answer="no")
        self.assertEqual(code, 1)
        self.assertTrue(os.path.exists(self.p("token.txt")))
        self.assertFalse(os.path.exists(self.p(rp.BACKUP_DIR)))

    def test_flags_keep_config_db_only_bin(self):
        self.run_main("--apply", "--yes", "--keep-config", "--keep-licensing-db",
                      "--only", "leftovers,config,licensing-db")
        self.assertTrue(os.path.exists(self.p("data", "licensing", "catalog.json")))
        self.assertEqual(len(self.rows("licenses")), 3)
        self.assertFalse(os.path.exists(self.p("token.txt")))
        self.assertTrue(os.path.exists(self.p("dist", "app.exe")))  # خارج از --only
        self.run_main("--apply", "--yes", "--include-bin", "--only", "bin")
        self.assertFalse(os.path.exists(self.p("bin", "ffmpeg.exe")))
        self.assertTrue(os.path.exists(self.p("goldenFriends", "rental.json")))

    def test_check_clean(self):
        self.assertEqual(self.run_main("--check-clean")[0], 1)
        self.run_main("--apply", "--yes")
        code, out = self.run_main("--check-clean")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
