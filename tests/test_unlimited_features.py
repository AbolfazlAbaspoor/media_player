"""لایسنسِ نامحدودِ مالک/ادمین باید خودکار همه‌ی امکاناتِ فعلیِ کاتالوگ رو بگیره."""

import os
import shutil
import tempfile
import time
import unittest

from licensing import catalog, licenses
from licensing import db as db_module


class SyncUnlimitedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _licence(self, notes, features):
        now = int(time.time())
        row = self.db.create_license(key=licenses.unique_key(self.db), user_id=1, order_id=None,
                                     max_bots=1, max_users=1, features=features,
                                     starts_at=now, expires_at=now + 86400)
        return self.db.update_license(int(row["id"]), notes=notes)

    def test_unlimited_licences_get_every_feature_including_new_ones(self):
        admin = self._licence("admin unlimited", ["svc_instagram"])
        owner = self._licence("owner self-licence", [])
        sold = self._licence(None, ["svc_instagram"])

        updated = licenses.sync_unlimited_features(self.db)

        self.assertEqual({int(r["id"]) for r in updated}, {int(admin["id"]), int(owner["id"])})
        everything = sorted(catalog.features())
        for row in (admin, owner):
            got = db_module.json_list(self.db.get_license(int(row["id"]))["features"])
            self.assertEqual(sorted(got), everything)
        # لایسنسِ فروخته‌شده دست نمی‌خوره.
        self.assertEqual(db_module.json_list(self.db.get_license(int(sold["id"]))["features"]),
                         ["svc_instagram"])
        # دفعه‌ی دوم چیزی برای به‌روزرسانی نیست.
        self.assertEqual(licenses.sync_unlimited_features(self.db), [])


if __name__ == "__main__":
    unittest.main()
