"""
B8: decrypting a customer's encrypted errors.log from inside Telegram
(the same crypto and per-line loop as `manage.py read-errors`), admin-only.
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from unittest import mock

from core import error_crypt
from licensing.telegram.sales import admin_errors
from licensing.telegram.sales import media_input


def run(coro):
    return asyncio.run(coro)


class AdminErrorsFlowTest(unittest.TestCase):

    def setUp(self):
        self.private_b64, self.public_b64 = error_crypt.generate_keypair()
        self.tmp = tempfile.mkdtemp()
        self.key_path = os.path.join(self.tmp, "errors_private.key")
        with open(self.key_path, "w", encoding="ascii") as f:
            f.write(self.private_b64)

        mock.patch.object(admin_errors, "_PRIVATE_KEY_PATH", self.key_path).start()
        mock.patch.object(admin_errors, "_is_admin", return_value=True).start()
        self.sent = mock.patch.object(admin_errors, "_send", new=mock.AsyncMock()).start()
        self.db = mock.Mock()
        mock.patch.object(admin_errors, "_db", return_value=self.db).start()

        self.update = mock.Mock()
        self.update.effective_user.id = 1
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _encrypted_log(self, lines):
        with mock.patch.object(error_crypt, "PUBLIC_KEY_B64", self.public_b64), \
             mock.patch.object(error_crypt, "_box", None), \
             mock.patch.object(error_crypt, "_checked", False), \
             mock.patch.object(error_crypt, "is_frozen", return_value=True):
            return "".join(error_crypt.encrypt_line(line + "\n") for line in lines)

    def _document(self, content_bytes, file_size=None):
        document = mock.Mock()
        document.file_size = file_size if file_size is not None else len(content_bytes)
        telegram_file = mock.Mock()
        telegram_file.download_as_bytearray = mock.AsyncMock(return_value=bytearray(content_bytes))
        document.get_file = mock.AsyncMock(return_value=telegram_file)
        return document

    def test_start_asks_admin_for_the_file(self):
        run(admin_errors.admin_errors_start(self.update, self.context))
        self.assertEqual(self.context.user_data["awaiting"], "errors_log")

    def test_start_refuses_non_admin(self):
        with mock.patch.object(admin_errors, "_is_admin", return_value=False):
            run(admin_errors.admin_errors_start(self.update, self.context))
        self.assertNotIn("awaiting", self.context.user_data)

    def test_no_document_asks_again(self):
        self.update.effective_message = mock.Mock(document=None)
        run(admin_errors.handle_errors_document(self.update, self.context))
        self.sent.assert_awaited()

    def test_oversized_file_is_refused(self):
        self.update.effective_message = mock.Mock(
            document=self._document(b"x", file_size=admin_errors.MAX_ERRORS_LOG_BYTES + 1))
        run(admin_errors.handle_errors_document(self.update, self.context))
        text = self.sent.call_args[0][1]
        self.assertTrue(text)
        self.update.effective_message.reply_document.assert_not_called()

    def test_missing_key_tells_the_admin_to_generate_one(self):
        os.remove(self.key_path)
        self.update.effective_message = mock.Mock(document=self._document(b"data"))
        run(admin_errors.handle_errors_document(self.update, self.context))
        self.sent.assert_awaited()
        self.update.effective_message.reply_document.assert_not_called()

    def test_decrypts_and_replies_with_a_text_file(self):
        raw = self._encrypted_log(["crash in core/services/youtube.py", "another one"])
        raw += "plain old debug line\n"
        self.update.effective_message = mock.Mock(document=self._document(raw.encode("utf-8")))
        self.update.effective_message.reply_document = mock.AsyncMock()

        run(admin_errors.handle_errors_document(self.update, self.context))

        self.update.effective_message.reply_document.assert_awaited_once()
        args, kwargs = self.update.effective_message.reply_document.call_args
        buffer = args[0]
        content = buffer.read().decode("utf-8")
        self.assertIn("crash in core/services/youtube.py", content)
        self.assertIn("another one", content)
        self.assertIn("plain old debug line", content)
        caption = str(kwargs.get("caption"))
        self.assertIn("2", caption)
        self.db.log_event.assert_called_once()

    def test_a_broken_record_does_not_stop_the_rest(self):
        good = self._encrypted_log(["ok line"])
        raw = error_crypt.PREFIX + "not-valid-base64!!\n" + good
        self.update.effective_message = mock.Mock(document=self._document(raw.encode("utf-8")))
        self.update.effective_message.reply_document = mock.AsyncMock()
        run(admin_errors.handle_errors_document(self.update, self.context))
        args, _kwargs = self.update.effective_message.reply_document.call_args
        content = args[0].read().decode("utf-8")
        self.assertIn("ok line", content)


class MediaDocumentDispatchTest(unittest.TestCase):
    """media_input.on_document routes to errors-log vs. broadcast vs. fallback."""

    def setUp(self):
        mock.patch.object(media_input, "_is_admin", return_value=True).start()
        self.errors_handler = mock.patch.object(
            media_input, "handle_errors_document", new=mock.AsyncMock()).start()
        self.broadcast_handler = mock.patch.object(
            media_input, "broadcast_capture", new=mock.AsyncMock()).start()
        self.update = mock.Mock()
        self.update.effective_message = mock.Mock(caption=None)
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()

    def test_awaiting_errors_log_routes_there(self):
        self.context.user_data["awaiting"] = "errors_log"
        run(media_input.on_document(self.update, self.context))
        self.errors_handler.assert_awaited_once()
        self.broadcast_handler.assert_not_awaited()

    def test_caption_command_routes_to_errors_log_without_the_button(self):
        self.update.effective_message.caption = "/readerrors"
        run(media_input.on_document(self.update, self.context))
        self.errors_handler.assert_awaited_once()

    def test_awaiting_broadcast_content_routes_to_broadcast(self):
        self.context.user_data["awaiting"] = "broadcast_content"
        run(media_input.on_document(self.update, self.context))
        self.broadcast_handler.assert_awaited_once()
        self.errors_handler.assert_not_awaited()

    def test_non_admin_never_reaches_errors_log(self):
        with mock.patch.object(media_input, "_is_admin", return_value=False), \
             mock.patch.object(media_input, "_user_row",
                               return_value={"blocked": False, "telegram_id": 5}), \
             mock.patch.object(media_input, "_db", return_value=mock.Mock(
                                   licenses_by_user=mock.Mock(return_value=[]))), \
             mock.patch.object(media_input, "_send", new=mock.AsyncMock()):
            self.context.user_data["awaiting"] = "errors_log"
            run(media_input.on_document(self.update, self.context))
        self.errors_handler.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
