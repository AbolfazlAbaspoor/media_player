"""
The sales bot is split by domain (licensing/telegram/sales/). The old entry
module still answers every name it used to have, and the application still
registers every command.
"""

import ast
import os
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "licensing", "telegram", "sales")

COMMANDS = {
    "start", "help", "cancel", "buy", "licenses", "mybots", "support", "language", "lang",
    "redeem", "promo", "promoadd", "promooff", "gift", "renew", "admin", "pending", "rate",
    "card", "grant", "extend", "suspend", "resume", "revoke", "license", "bots", "lines",
    "sweep", "tickets", "reply", "say", "reload", "pubkey", "commands",
    "broadcast", "readerrors", "catalog", "quote", "rentalreset", "alllicenses",
}


class SalesPackageTest(unittest.TestCase):

    def test_old_names_still_resolve_through_sales_bot(self):
        from licensing.telegram import sales_bot
        for name in ("build_application", "setup_handle_text", "on_callback", "on_text", "on_photo",
                     "approve_order", "admin_panel", "cmd_grant", "_run_sweep", "_db", "HTML"):
            self.assertTrue(hasattr(sales_bot, name), name)
        with self.assertRaises(AttributeError):
            sales_bot.no_such_handler

    def test_every_module_defines_its_names_once(self):
        seen = {}
        for file_name in sorted(os.listdir(PACKAGE)):
            if not file_name.endswith(".py") or file_name == "__init__.py":
                continue
            with open(os.path.join(PACKAGE, file_name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertNotIn(node.name, seen, f"{node.name} in {file_name} and {seen.get(node.name)}")
                    seen[node.name] = file_name

    def test_the_application_registers_every_command(self):
        from licensing import config
        from licensing.telegram import sales_bot
        from telegram.ext import CommandHandler
        real_get = config.get

        def fake_get(key, *args, **kwargs):
            if key == "sales_bot_token":
                return "123456:TEST"
            return real_get(key, *args, **kwargs)

        with mock.patch("licensing.config.get", side_effect=fake_get), \
                mock.patch("licensing.sync.autoregister", return_value=[]):
            app = sales_bot.build_application(mock.Mock(), None, None)
        registered = set()
        for handlers in app.handlers.values():
            for handler in handlers:
                if isinstance(handler, CommandHandler):
                    registered |= set(handler.commands)
        self.assertLessEqual(COMMANDS, registered)


if __name__ == "__main__":
    unittest.main()
