"""
پاکسازیِ ادمین (licensing/gc.py + دکمه‌ی /admin + manage.py gc).

همه‌چی توی دایرکتوری و دیتابیسِ موقت؛ به data/ واقعی و به لاین‌های صوتیِ
واقعی دست نمی‌زنه (audio_lines و config با mock جایگزین می‌شن).
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from licensing import db as db_module
from licensing import gc
from licensing.telegram.sales import admin_gc

DAY = 86400
NOW = int(time.time())
SOLD = "TT-EQ4F-2V6D-AWFF"


def _age(path, days):
    ts = time.time() - days * DAY
    os.utime(path, (ts, ts))


class GcBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.data = os.path.join(self.tmp, "data")
        self.errors = os.path.join(self.tmp, "errors")
        self.receipts = os.path.join(self.data, "licensing", "receipts")
        for d in (self.data, self.errors, self.receipts):
            os.makedirs(d)
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.cfg = {"protected_licences": [], "grace_days": 3}
        self.lines = []
        self.destroyed = []
        mock.patch("licensing.gc.config.get", side_effect=lambda k, d=None: self.cfg.get(k, d)).start()
        mock.patch("licensing.gc.audio_lines.list_lines", side_effect=lambda: list(self.lines)).start()
        mock.patch("licensing.gc.audio_lines.destroy_line",
                   side_effect=self._destroy).start()
        mock.patch("licensing.gc.provisioning.deactivate_license", return_value=[]).start()
        self.opts = gc.Options(errors_dir=self.errors, receipts_dir=self.receipts)

    def _destroy(self, slug):
        self.destroyed.append(slug)
        self.lines = [ln for ln in self.lines if ln["slug"] != slug]
        return True

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def licence(self, status="active", key=None, expires=None, notes=None):
        key = key or f"TT-TEST-{len(self.db.query('SELECT id FROM licenses')):04d}-AAAA"
        row = self.db.create_license(
            key=key, user_id=1, order_id=None, max_bots=1, max_users=1, features=[],
            starts_at=NOW - 400 * DAY, expires_at=expires if expires is not None else NOW - 300 * DAY,
            status=status)
        if notes is not None:
            self.db._execute("UPDATE licenses SET notes=? WHERE id=?", (notes, row["id"]))
        self.db._execute("UPDATE licenses SET updated_at=?, deactivated_at=? WHERE id=?",
                         (NOW - 300 * DAY, NOW - 300 * DAY, row["id"]))
        return self.db.get_license(row["id"])

    def instance(self, lic, slug="b1", status="removed", age_days=100, group="h_1", bot="b1"):
        row = self.db.create_instance(
            lic["id"], slug, "h", 1, "n", "u", "p", group_name=group, bot_name=bot, status=status)
        self.db._execute("UPDATE instances SET removed_at=?, updated_at=? WHERE id=?",
                         (NOW - age_days * DAY, NOW - age_days * DAY, row["id"]))
        return row["id"]

    def scan(self):
        return gc.scan(self.db, self.data, now=NOW, options=self.opts)

    def ids(self, report):
        return {c.id for c in report.deletable()}


class ScanTests(GcBase):

    def test_dead_instance_row_and_active_licence_missing_needs_attention(self):
        dead = self.licence("expired")
        live = self.licence("active", expires=NOW + DAY)
        gone = self.instance(dead)
        miss = self.instance(live, slug="m", status="missing", bot="m")
        rep = self.scan()
        self.assertIn(f"inst:{gone}", self.ids(rep))
        self.assertNotIn(f"inst:{miss}", self.ids(rep))
        self.assertEqual([c.id for c in rep.attention], [f"inst:{miss}"])
        self.assertFalse(rep.attention[0].deletable)

    def test_protected_licences_never_candidates(self):
        self.cfg["protected_licences"] = ["TT-CUST-0000-AAAA"]
        keys = [SOLD, "TT-CUST-0000-AAAA"]
        made = [self.licence("expired", key=k) for k in keys]
        made.append(self.licence("revoked", notes="Owner licence"))
        made.append(self.licence("expired", notes="admin unlimited"))
        made.append(self.licence("suspended"))
        for lic in made:
            self.instance(lic, slug=f"s{lic['id']}", bot=f"s{lic['id']}",
                          status="running" if lic["status"] == "suspended" else "removed")
        rep = self.scan()
        bad = {f"lic:{l['id']}" for l in made} | {f"inst:{i['id']}" for i in self.db.query("SELECT id FROM instances")}
        self.assertFalse(bad & self.ids(rep))

    def test_old_expired_and_revoked_licences_listed_recent_not(self):
        old = self.licence("expired")
        rev = self.licence("revoked")
        fresh = self.licence("expired", expires=NOW - 5 * DAY)
        ids = self.ids(self.scan())
        self.assertIn(f"lic:{old['id']}", ids)
        self.assertIn(f"lic:{rev['id']}", ids)
        self.assertNotIn(f"lic:{fresh['id']}", ids)

    def test_orphan_folder_only_without_row_and_old(self):
        lic = self.licence("active", expires=NOW + DAY)
        self.instance(lic, status="running", group="h_1", bot="known", slug="known")
        for name in ("known", "orphan", "young"):
            p = os.path.join(self.data, "h_1", name)
            os.makedirs(p)
            open(os.path.join(p, "identity.json"), "w").write("{}")
            open(os.path.join(p, "x.bin"), "wb").write(b"1234")
        _age(os.path.join(self.data, "h_1", "orphan", "identity.json"), 10)
        _age(os.path.join(self.data, "h_1", "known", "identity.json"), 10)
        ids = self.ids(self.scan())
        self.assertIn("dir:h_1/orphan", ids)
        self.assertNotIn("dir:h_1/known", ids)
        self.assertNotIn("dir:h_1/young", ids)

    def test_orphan_folder_naming_sold_licence_is_kept(self):
        p = os.path.join(self.data, "h_1", "sold")
        os.makedirs(p)
        open(os.path.join(p, "identity.json"), "w").write("{}")
        open(os.path.join(p, "license.json"), "w").write(f'{{"key": "{SOLD}"}}')
        _age(os.path.join(p, "identity.json"), 10)
        self.assertNotIn("dir:h_1/sold", self.ids(self.scan()))

    def test_orphan_audio_lines(self):
        lic = self.licence("active", expires=NOW + DAY)
        self.instance(lic, status="running", group="h_1", bot="b1")
        self.lines = [{"slug": "kept", "owner": "h_1/b1"},
                      {"slug": "orph", "owner": "h_1/gone"},
                      {"slug": "manual", "owner": "admin"}]
        ids = self.ids(self.scan())
        self.assertEqual({i for i in ids if i.startswith("line:")}, {"line:orph"})

    def test_stale_orders_and_receipts(self):
        def order(status, age):
            o = self.db.create_order(1, 1, 1, 1, [], 1.0, status=status)
            self.db._execute("UPDATE orders SET updated_at=?, receipt_path=? WHERE id=?",
                             (NOW - age * DAY, f"r{o['id']}.jpg", o["id"]))
            open(os.path.join(self.receipts, f"r{o['id']}.jpg"), "wb").write(b"img")
            return o["id"]
        old = order("rejected", 60)
        young = order("rejected", 1)
        review = order("admin_review", 90)
        done = order("approved", 90)
        ids = self.ids(self.scan())
        self.assertIn(f"order:{old}", ids)
        for keep in (young, review, done):
            self.assertNotIn(f"order:{keep}", ids)

    def test_logs_and_temp(self):
        old = os.path.join(self.errors, "old.log")
        new = os.path.join(self.errors, "new.log")
        for p in (old, new):
            open(p, "w").write("x")
        _age(old, 90)
        tmp_old = os.path.join(self.data, "a.tmp")
        open(tmp_old, "w").write("x")
        _age(tmp_old, 3)
        secret = os.path.join(self.data, "licensing", "keys.tmp")
        open(secret, "w").write("x")
        _age(secret, 30)
        ids = self.ids(self.scan())
        self.assertIn("log:old.log", ids)
        self.assertNotIn("log:new.log", ids)
        self.assertIn("tmp:a.tmp", ids)
        self.assertFalse([i for i in ids if "licensing" in i])


class ApplyTests(GcBase):

    def test_apply_deletes_only_selection_and_rescans(self):
        old = os.path.join(self.errors, "old.log")
        other = os.path.join(self.errors, "old2.log")
        for p in (old, other):
            open(p, "w").write("x")
            _age(p, 90)
        res = gc.apply(self.db, self.data, ["log:old.log", "log:../evil", "tmp:nothing"],
                       options=self.opts, now=NOW)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(other))
        self.assertEqual(res["deleted"], {"logs": 1})
        self.assertEqual(sorted(res["skipped"]), ["log:../evil", "tmp:nothing"])

    def test_apply_refuses_attention_and_protected(self):
        live = self.licence("active", expires=NOW + DAY)
        miss = self.instance(live, status="missing", slug="m", bot="m")
        sold = self.licence("expired", key=SOLD)
        res = gc.apply(self.db, self.data, [f"inst:{miss}", f"lic:{sold['id']}"],
                       options=self.opts, now=NOW)
        self.assertEqual(res["deleted"], {})
        self.assertIsNotNone(self.db.get_license(sold["id"]))
        self.assertIsNotNone(self.db.get_license(live["id"]))
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM instances")["n"], 1)

    def test_apply_full_flow_orphan_dir_order_line_licence(self):
        lic = self.licence("expired")
        p = os.path.join(self.data, "h_1", "orphan")
        os.makedirs(p)
        open(os.path.join(p, "identity.json"), "w").write("{}")
        _age(os.path.join(p, "identity.json"), 10)
        o = self.db.create_order(1, 1, 1, 1, [], 1.0, status="cancelled")
        rp = os.path.join(self.receipts, "r.jpg")
        open(rp, "wb").write(b"img")
        self.db._execute("UPDATE orders SET updated_at=?, receipt_path='r.jpg' WHERE id=?",
                         (NOW - 90 * DAY, o["id"]))
        self.lines = [{"slug": "orph", "owner": "h_1/gone"}]
        rep = self.scan()
        res = gc.apply(self.db, self.data, [c.id for c in rep.deletable()],
                       options=self.opts, now=NOW)
        self.assertEqual(res["errors"], 0)
        self.assertFalse(os.path.exists(p))
        self.assertFalse(os.path.exists(rp))
        self.assertEqual(self.destroyed, ["orph"])
        self.assertIsNone(self.db.get_license(lic["id"]))
        self.assertEqual(self.db.query_one("SELECT COUNT(*) n FROM orders")["n"], 0)
        # بعد از پاکسازی چیزی نمی‌مونه.
        self.assertEqual(self.ids(self.scan()), set())

    def test_remove_path_refuses_outside_root_and_symlink(self):
        outside = os.path.join(self.tmp, "outside.txt")
        open(outside, "w").write("x")
        self.assertFalse(gc._remove_path(self.data, outside))
        self.assertTrue(os.path.exists(outside))
        try:
            link = os.path.join(self.data, "lnk")
            os.symlink(self.tmp, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            return
        self.assertFalse(gc._remove_path(self.data, link))
        self.assertTrue(os.path.isdir(self.tmp))


class HandlerTests(GcBase):

    def setUp(self):
        super().setUp()
        self.sent = mock.patch.object(admin_gc, "_send", new=mock.AsyncMock()).start()
        self.update = mock.Mock()
        self.update.effective_user.id = 5
        self.context = mock.Mock()

    def run_h(self, fn, *a):
        return asyncio.run(fn(self.update, self.context, *a))

    def test_non_admin_is_refused_everywhere(self):
        scan = mock.patch.object(gc, "scan").start()
        apply_ = mock.patch.object(gc, "apply").start()
        with mock.patch.object(admin_gc, "_is_admin", return_value=False):
            self.run_h(admin_gc.gc_start)
            self.run_h(admin_gc.gc_category, "logs", 0)
            self.run_h(admin_gc.gc_confirm, "all")
            self.run_h(admin_gc.gc_apply, "all")
            self.run_h(admin_gc.gc_attention)
        scan.assert_not_called()
        apply_.assert_not_called()
        self.assertEqual(self.sent.await_count, 5)

    def test_admin_flow_scan_confirm_apply(self):
        old = os.path.join(self.errors, "old.log")
        open(old, "w").write("x")
        _age(old, 90)
        opts = self.opts
        with mock.patch.object(admin_gc, "_is_admin", return_value=True), \
                mock.patch.object(admin_gc, "_db", return_value=self.db), \
                mock.patch.object(admin_gc, "_supervisor", return_value=None), \
                mock.patch.object(admin_gc, "DATA_DIR", self.data), \
                mock.patch.object(gc, "default_options", return_value=opts):
            self.run_h(admin_gc.gc_start)
            self.run_h(admin_gc.gc_confirm, "all")
            self.assertTrue(os.path.exists(old))  # تأیید هنوز چیزی پاک نکرده
            self.run_h(admin_gc.gc_apply, "all")
        self.assertFalse(os.path.exists(old))

    def test_scan_failure_shows_generic_error(self):
        with mock.patch.object(admin_gc, "_is_admin", return_value=True), \
                mock.patch.object(admin_gc, "_db", return_value=self.db), \
                mock.patch.object(gc, "scan", side_effect=RuntimeError("secret-path")):
            self.run_h(admin_gc.gc_start)
        shown = " ".join(str(c) for c in self.sent.await_args_list)
        self.assertNotIn("secret-path", shown)


if __name__ == "__main__":
    unittest.main()
