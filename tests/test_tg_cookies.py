"""
Cookie management from the Telegram sales bot: owner/admin only, file and
pasted-text input, validation errors, delete, and never echoing contents.
"""

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

from core import cookie_files
from licensing import db as db_module
from licensing import licenses
from licensing import provisioning
from licensing.telegram.sales import cookies, media_input, text_input

SECRET = "SUPERSECRETVALUE"
GOOD = ".youtube.com\tTRUE\t/\tTRUE\t2000000000\tSID\t" + SECRET + "\n"
FUTURE = int(time.time()) + 30 * 86400


def run(coro):
    return asyncio.run(coro)


class CookiesTestBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        mock.patch.object(provisioning, "DATA_DIR", os.path.join(self.tmp, "data")).start()
        self.admin = mock.patch("licensing.config.is_admin", side_effect=lambda uid: uid == 1).start()
        mock.patch("licensing.telegram.sales.my_licenses._db", return_value=self.db).start()
        self.sent = mock.AsyncMock()
        # هر سه ماژول _send رو از common می‌گیرن؛ همه رو روی یه mock می‌بریم.
        mock.patch("licensing.telegram.sales.my_licenses._send", new=self.sent).start()
        mock.patch.object(cookies, "_send", new=self.sent).start()
        mock.patch.object(text_input, "_db", return_value=self.db).start()
        mock.patch.object(text_input, "_user_row", return_value={"blocked": 0, "telegram_id": 5}).start()
        mock.patch.object(text_input, "_send", new=self.sent).start()
        mock.patch.object(media_input, "_user_row", return_value={"blocked": 0, "telegram_id": 5}).start()
        mock.patch.object(media_input, "_send", new=self.sent).start()

        license_row = self.db.create_license(
            key=licenses.unique_key(self.db), user_id=5, order_id=None, max_bots=1,
            max_users=1, features=[], starts_at=int(time.time()), expires_at=FUTURE,
            status="active")
        self.instance = self.db.create_instance(
            license_row["id"], "bot-a", "h", 1, "nick", "user", "pw")
        self.bot_dir = provisioning.instance_dirs(self.instance)[1]

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_update(self, user_id, text=None, document=None):
        update = mock.Mock()
        update.effective_user.id = user_id
        update.callback_query = None
        update.effective_message.text = text
        update.effective_message.document = document
        update.effective_message.delete = mock.AsyncMock()
        return update

    def make_context(self):
        context = mock.Mock()
        context.user_data = {}
        context.application.bot_data = {"db": self.db, "supervisor": None}
        return context

    def shown(self):
        return " ".join(str(c) for c in self.sent.call_args_list)

    def arm(self, context, user_id, service="youtube"):
        iid = self.instance["id"]
        run(cookies.cookies_on_callback(self.make_update(user_id), context, "add", iid, service))
        self.assertEqual(context.user_data["awaiting"], "cookie_upload")

    def document(self, data):
        doc = mock.Mock()
        doc.file_size = len(data)
        tg_file = mock.Mock()
        tg_file.download_as_bytearray = mock.AsyncMock(return_value=bytearray(data))
        doc.get_file = mock.AsyncMock(return_value=tg_file)
        return doc


class PermissionTest(CookiesTestBase):

    def test_owner_can_add(self):
        context = self.make_context()
        self.arm(context, 5)
        run(text_input.on_text(self.make_update(5, GOOD), context))
        self.assertEqual(cookie_files.present(self.bot_dir), ["youtube"])

    def test_admin_can_add_for_any_instance(self):
        context = self.make_context()
        self.arm(context, 1)
        run(text_input.on_text(self.make_update(1, GOOD), context))
        self.assertEqual(cookie_files.present(self.bot_dir), ["youtube"])

    def test_stranger_cannot_open_or_add(self):
        context = self.make_context()
        iid = self.instance["id"]
        run(cookies.cookies_on_callback(self.make_update(99), context, "add", iid, "youtube"))
        self.assertNotIn("awaiting", context.user_data)
        # حتی با state دست‌ساز، ذخیره هنگام نوشتن دوباره چک می‌شه.
        context.user_data.update({"awaiting": "cookie_upload",
                                  "cookies": {"iid": iid, "service": "youtube"}})
        run(text_input.on_text(self.make_update(99, GOOD), context))
        self.assertEqual(cookie_files.present(self.bot_dir), [])

    def test_stranger_cannot_delete(self):
        cookie_files.write(self.bot_dir, "youtube", GOOD)
        context = self.make_context()
        run(cookies.cookies_on_callback(self.make_update(99), context, "delok",
                                        self.instance["id"], "youtube"))
        self.assertEqual(cookie_files.present(self.bot_dir), ["youtube"])


class InputPathsTest(CookiesTestBase):

    def test_pasted_text_saved_and_message_deleted(self):
        context = self.make_context()
        self.arm(context, 5)
        update = self.make_update(5, GOOD)
        run(text_input.on_text(update, context))
        update.effective_message.delete.assert_awaited()
        with open(cookie_files.path_in(self.bot_dir, "youtube"), encoding="utf-8") as f:
            self.assertIn(SECRET, f.read())
        self.assertNotIn("awaiting", context.user_data)

    def test_uploaded_document_saved(self):
        context = self.make_context()
        self.arm(context, 5, "instagram")
        update = self.make_update(5, document=self.document(GOOD.encode()))
        run(media_input.on_document(update, context))
        self.assertEqual(cookie_files.present(self.bot_dir), ["instagram"])

    def test_oversize_document_not_downloaded(self):
        context = self.make_context()
        self.arm(context, 5)
        doc = self.document(b"x")
        doc.file_size = cookie_files.MAX_BYTES + 1
        run(media_input.on_document(self.make_update(5, document=doc), context))
        doc.get_file.assert_not_called()
        self.assertEqual(cookie_files.present(self.bot_dir), [])

    def test_invalid_text_and_binary_rejected_without_echo(self):
        context = self.make_context()
        self.arm(context, 5)
        run(text_input.on_text(self.make_update(5, "hello " + SECRET), context))
        self.assertEqual(cookie_files.present(self.bot_dir), [])
        self.assertNotIn(SECRET, self.shown())
        self.assertNotIn("CookieError", self.shown())
        self.assertNotIn("Netscape cookies.txt file'", self.shown())
        # هنوز منتظره تا کاربر دوباره بفرسته یا لغو کنه.
        self.assertEqual(context.user_data["awaiting"], "cookie_upload")
        run(media_input.on_document(
            self.make_update(5, document=self.document(b"\xff\xfe\x00bad")), context))
        self.assertEqual(cookie_files.present(self.bot_dir), [])

    def test_other_service_name_is_validated(self):
        context = self.make_context()
        run(cookies.cookies_on_callback(self.make_update(5), context, "other", self.instance["id"]))
        run(text_input.on_text(self.make_update(5, "../../evil"), context))
        self.assertEqual(context.user_data["awaiting"], "cookie_service")
        run(text_input.on_text(self.make_update(5, "tiktok"), context))
        self.assertEqual(context.user_data["awaiting"], "cookie_upload")
        self.assertEqual(context.user_data["cookies"]["service"], "tiktok")

    def test_bad_service_in_callback_rejected(self):
        context = self.make_context()
        run(cookies.cookies_on_callback(self.make_update(5), context, "add",
                                        self.instance["id"], "../x"))
        self.assertNotIn("awaiting", context.user_data)


class DeleteAndMenuTest(CookiesTestBase):

    def test_delete_asks_then_removes(self):
        cookie_files.write(self.bot_dir, "youtube", GOOD)
        context = self.make_context()
        iid = self.instance["id"]
        run(cookies.cookies_on_callback(self.make_update(5), context, "del", iid, "youtube"))
        self.assertEqual(cookie_files.present(self.bot_dir), ["youtube"])
        run(cookies.cookies_on_callback(self.make_update(5), context, "delok", iid, "youtube"))
        self.assertEqual(cookie_files.present(self.bot_dir), [])

    def test_menu_lists_names_never_contents(self):
        cookie_files.write(self.bot_dir, "youtube", GOOD)
        context = self.make_context()
        run(cookies.cookies_show(self.make_update(5), context, self.instance["id"]))
        self.assertIn("youtube", self.shown())
        self.assertNotIn(SECRET, self.shown())


if __name__ == "__main__":
    unittest.main()
