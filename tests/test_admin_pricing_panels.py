"""
مدیریتِ دکمه‌ایِ پنل‌های فروش (📋 «مدیریتِ پنل‌های فروش»): دیدن/ویرایش/
افزودن/حذف، همه با دکمه، بدونِ دست‌زدن به data/licensing/catalog.json.
"""

import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

from licensing import catalog
from licensing.telegram.sales import admin_pricing_panels as pnl

_DEFAULT_OVERRIDE_FILE = catalog.OVERRIDE_FILE


def run(coro):
    return asyncio.run(coro)


class PanelsAdminTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        catalog.OVERRIDE_FILE = os.path.join(self.tmp, "catalog.json")
        catalog.load(force=True)

        mock.patch.object(pnl, "_is_admin", return_value=True).start()
        self.sent = mock.patch.object(pnl, "_send", new=mock.AsyncMock()).start()

        self.update = mock.Mock()
        self.context = mock.Mock()
        self.context.user_data = {}

    def tearDown(self):
        mock.patch.stopall()
        catalog.OVERRIDE_FILE = _DEFAULT_OVERRIDE_FILE
        catalog.load(force=True)

    def _markup(self):
        return self.sent.call_args[0][2]

    def _callbacks(self):
        return [b.callback_data for row in self._markup().inline_keyboard for b in row]

    def test_list_shows_every_default_panel_with_a_show_button(self):
        run(pnl.panels_admin_list(self.update, self.context))
        callbacks = self._callbacks()
        for panel in catalog.panels():
            self.assertIn(f"pnl:show:{panel['code']}", callbacks)
        self.assertIn("pnl:new", callbacks)

    def test_add_edit_and_save_a_new_panel(self):
        run(pnl.panels_admin_new(self.update, self.context))
        run(pnl.panels_admin_title_fa_text(self.update, self.context, "تست"))
        run(pnl.panels_admin_title_en_text(self.update, self.context, "Test"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "b", "+1"))
        code = sorted(catalog.features())[0]
        run(pnl.panels_admin_on_callback(self.update, self.context, "feat"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "tf", code))
        run(pnl.panels_admin_on_callback(self.update, self.context, "save"))

        saved = [p for p in catalog.panels() if p["title_fa"] == "تست"]
        self.assertEqual(len(saved), 1)
        panel = saved[0]
        self.assertEqual(panel["bots"], 2)
        self.assertEqual(panel["months"], 1)   # همیشه ثابت، حتی اگه فردا کد دیگه‌ای بخواد عوضش کنه
        self.assertEqual(panel["features"], [code])
        self.assertNotIn("panel_edit", self.context.user_data)

    def test_new_panel_gets_a_fresh_unused_code(self):
        existing = {p["code"] for p in catalog.panels()}
        run(pnl.panels_admin_new(self.update, self.context))
        run(pnl.panels_admin_title_fa_text(self.update, self.context, "دوم"))
        run(pnl.panels_admin_title_en_text(self.update, self.context, "Second"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "save"))
        new_codes = {p["code"] for p in catalog.panels()} - existing
        self.assertEqual(len(new_codes), 1)

    def test_cannot_save_without_both_titles(self):
        run(pnl.panels_admin_new(self.update, self.context))
        run(pnl.panels_admin_on_callback(self.update, self.context, "save"))
        self.assertIn("panel_edit", self.context.user_data)  # هنوز باز مونده

    def test_edit_existing_panel_changes_it_in_place(self):
        first_code = catalog.panels()[0]["code"]
        run(pnl.panels_admin_show(self.update, self.context, first_code))
        run(pnl.panels_admin_on_callback(self.update, self.context, "b", "+1"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "save"))

        codes = [p["code"] for p in catalog.panels()]
        self.assertEqual(codes.count(first_code), 1)   # جایگزین شده، تکراری نساخته
        panel = next(p for p in catalog.panels() if p["code"] == first_code)
        self.assertEqual(panel["bots"], 2)

    def test_delete_asks_confirmation_then_removes(self):
        code = catalog.panels()[0]["code"]
        run(pnl.panels_admin_show(self.update, self.context, code))
        run(pnl.panels_admin_on_callback(self.update, self.context, "del"))
        self.assertIn(code, [p["code"] for p in catalog.panels()])   # هنوز حذف نشده

        run(pnl.panels_admin_on_callback(self.update, self.context, "delok", code))
        self.assertNotIn(code, [p["code"] for p in catalog.panels()])

    def test_cancel_does_not_touch_the_catalog(self):
        before = json.dumps(catalog.panels(), sort_keys=True)
        run(pnl.panels_admin_new(self.update, self.context))
        run(pnl.panels_admin_title_fa_text(self.update, self.context, "لغوشده"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "cancel"))
        after = json.dumps(catalog.panels(), sort_keys=True)
        self.assertEqual(before, after)

    def test_save_preserves_other_override_sections(self):
        catalog.save_panels(catalog.panels())  # یه override می‌سازه فقط با panels
        with open(catalog.OVERRIDE_FILE, "r", encoding="utf-8") as f:
            override = json.load(f)
        override["pricing"] = {"base_monthly_usd": 42.0}
        with open(catalog.OVERRIDE_FILE, "w", encoding="utf-8") as f:
            json.dump(override, f)
        catalog.load(force=True)

        run(pnl.panels_admin_new(self.update, self.context))
        run(pnl.panels_admin_title_fa_text(self.update, self.context, "س"))
        run(pnl.panels_admin_title_en_text(self.update, self.context, "S"))
        run(pnl.panels_admin_on_callback(self.update, self.context, "save"))

        self.assertEqual(catalog.pricing()["base_monthly_usd"], 42.0)


if __name__ == "__main__":
    unittest.main()


class HelpTextLanguageTest(unittest.TestCase):
    """/help قبلاً حتی توی راهنمای انگلیسی توضیحِ فارسیِ هر امکان رو نشون می‌داد."""

    def test_english_help_uses_english_notes(self):
        from licensing import i18n as licensing_i18n
        from licensing.telegram import texts

        original = licensing_i18n.get_language()
        licensing_i18n.set_language("en")
        try:
            help_text = texts.HELP
        finally:
            licensing_i18n.set_language(original)

        self.assertIn("Speak with vs", help_text)
        self.assertNotIn("با vs حرف بزن", help_text)
