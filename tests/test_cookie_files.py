"""Each bot's cookies stay with that bot; a customer's never reach another's."""

import os
import shutil
import tempfile
import unittest

from core import cookie_files as cf

GOOD = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tSID\tabc123\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tHSID\tdef456\n"
)


class ResolveTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.group = os.path.join(self.tmp, "host_10333")
        self.bot_a = os.path.join(self.group, "customer_a")
        self.bot_b = os.path.join(self.group, "customer_b")
        for d in (self.bot_a, self.bot_b):
            os.makedirs(d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_bots_own_cookie_wins(self):
        cf.write(self.bot_a, "youtube", GOOD)
        cf.write(self.group, "youtube", GOOD)
        self.assertEqual(cf.resolve(self.bot_a, self.group, "youtube", managed=True),
                         cf.path_in(self.bot_a, "youtube"))

    def test_hosted_bot_never_uses_the_shared_server_cookie(self):
        cf.write(self.group, "youtube", GOOD)
        self.assertIsNone(cf.resolve(self.bot_b, self.group, "youtube", managed=True))

    def test_customer_a_cookie_never_reaches_customer_b(self):
        cf.write(self.bot_a, "youtube", GOOD)
        self.assertIsNone(cf.resolve(self.bot_b, self.group, "youtube", managed=True))

    def test_personal_install_still_shares_the_server_cookie(self):
        cf.write(self.group, "youtube", GOOD)
        self.assertEqual(cf.resolve(self.bot_b, self.group, "youtube", managed=False),
                         cf.path_in(self.group, "youtube"))


class ValidateTest(unittest.TestCase):

    def test_accepts_a_netscape_file(self):
        self.assertIn("SID", cf.validate(GOOD.encode()))

    def test_rejects_html(self):
        with self.assertRaises(cf.CookieError):
            cf.validate(b"<html><body>login</body></html>")

    def test_rejects_json_export(self):
        with self.assertRaises(cf.CookieError):
            cf.validate(b'[{"name":"SID","value":"x"}]')

    def test_rejects_comments_only(self):
        with self.assertRaises(cf.CookieError):
            cf.validate(b"# Netscape HTTP Cookie File\n\n")

    def test_rejects_binary(self):
        with self.assertRaises(cf.CookieError):
            cf.validate(b"\xff\xd8\xff\xe0 jpeg")

    def test_rejects_oversized(self):
        with self.assertRaises(cf.CookieError):
            cf.validate(b"x" * (cf.MAX_BYTES + 1))

    def test_service_name_cannot_escape_the_folder(self):
        for bad in ("../../etc", "you/tube", "", "a" * 60, "YouTube!"):
            with self.assertRaises(cf.CookieError):
                cf.check_service_name(bad)


class StorageTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_list_remove(self):
        cf.write(self.tmp, "youtube", GOOD)
        cf.write(self.tmp, "instagram", GOOD)
        self.assertEqual(cf.present(self.tmp), ["instagram", "youtube"])
        self.assertTrue(cf.remove(self.tmp, "youtube"))
        self.assertFalse(cf.remove(self.tmp, "youtube"))
        self.assertEqual(cf.present(self.tmp), ["instagram"])

    def test_a_rejected_file_leaves_the_old_one_intact(self):
        cf.write(self.tmp, "youtube", GOOD)
        with self.assertRaises(cf.CookieError):
            cf.write(self.tmp, "youtube", b"<html>")
        with open(cf.path_in(self.tmp, "youtube"), encoding="utf-8") as f:
            self.assertIn("SID", f.read())


if __name__ == "__main__":
    unittest.main()


class CustomerUploadTest(unittest.TestCase):
    """The personal bot must only ever write into the owner's own bot."""

    def setUp(self):
        import asyncio
        from unittest import mock
        from licensing.telegram import customer_bot as cb
        self.asyncio, self.mock, self.cb = asyncio, mock, cb
        self.tmp = tempfile.mkdtemp()
        self.dirs = {1: os.path.join(self.tmp, "g", "mine"), 2: os.path.join(self.tmp, "g", "theirs")}
        db = mock.Mock()
        db.get_instance.side_effect = lambda i: {"id": i, "license_id": 10 + i, "slug": f"s{i}"}
        db.get_license.side_effect = lambda lid: {"user_id": 500 if lid == 11 else 777}
        self.context = mock.Mock()
        self.context.application.bot_data = {"db": db, "owner_id": 500, "supervisor": None}
        self.context.user_data = {}
        mock.patch("licensing.provisioning.instance_dirs",
                   side_effect=lambda inst: (os.path.join(self.tmp, "g"), self.dirs[inst["id"]])).start()
        mock.patch.object(cb, "_is_owner", return_value=True).start()
        self.sent = mock.patch.object(cb, "_send", new=mock.AsyncMock()).start()

    def tearDown(self):
        self.mock.patch.stopall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _update_with_file(self, payload):
        telegram_file = self.mock.Mock()
        telegram_file.download_as_bytearray = self.mock.AsyncMock(return_value=bytearray(payload))
        document = self.mock.Mock(file_size=len(payload))
        document.get_file = self.mock.AsyncMock(return_value=telegram_file)
        update = self.mock.Mock()
        update.effective_message.document = document
        return update

    def test_upload_into_own_bot(self):
        self.context.user_data["cookie_target"] = (1, "youtube")
        self.asyncio.run(self.cb.on_document(self._update_with_file(GOOD.encode()), self.context))
        self.assertEqual(cf.present(self.dirs[1]), ["youtube"])

    def test_forged_target_for_someone_elses_bot_writes_nothing(self):
        self.context.user_data["cookie_target"] = (2, "youtube")
        self.asyncio.run(self.cb.on_document(self._update_with_file(GOOD.encode()), self.context))
        self.assertEqual(cf.present(self.dirs[2]), [])

    def test_selecting_a_foreign_bot_is_refused(self):
        self.asyncio.run(self.cb.show_cookies(self.mock.Mock(), self.context, 2, "youtube"))
        self.assertNotIn("cookie_target", self.context.user_data)

    def test_file_without_a_selected_target_is_refused(self):
        self.asyncio.run(self.cb.on_document(self._update_with_file(GOOD.encode()), self.context))
        self.assertEqual(cf.present(self.dirs[1]), [])
