"""
B7 (2026-09-16): the number of operator users is no longer a priced or
limited dimension. These tests pin down the parts of that decision that
have nothing to do with the setup wizard (covered in test_setup_wizard.py):
pricing.quote() itself, the panel catalog, and backward compatibility with
an old data/licensing/catalog.json override that still mentions users.
"""

import copy
import inspect
import json
import os
import tempfile
import unittest

from licensing import catalog
from licensing import pricing

_DEFAULT_OVERRIDE_FILE = catalog.OVERRIDE_FILE


def _use_default_catalog(test):
    """کاتالوگ پیش‌فرض، مستقل از data/ واقعیِ ماشین (فایل override وجود نداره)."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    catalog.OVERRIDE_FILE = os.path.join(tmp.name, "catalog.json")
    catalog.load(force=True)


class QuoteHasNoUserTermTest(unittest.TestCase):

    def setUp(self):
        _use_default_catalog(self)

    def tearDown(self):
        # اگه یه تستِ دیگه OVERRIDE_FILE رو عوض کرده باشه و کرش کنه، این
        # تضمین می‌کنه بقیه‌ی تست‌های سوییت با کاتالوگِ پیش‌فرض ادامه بدن.
        catalog.OVERRIDE_FILE = _DEFAULT_OVERRIDE_FILE
        catalog.load(force=True)

    def test_quote_signature_has_no_users_parameter(self):
        params = list(inspect.signature(pricing.quote).parameters)
        self.assertEqual(params, ["months", "bots", "feature_codes", "db"])

    def test_quote_result_has_no_users_key(self):
        quote = pricing.quote(1, 1, [])
        self.assertNotIn("users", quote)
        self.assertEqual(quote["bots"], 1)

    def test_invoice_lines_never_mention_a_per_operator_charge(self):
        quote = pricing.quote(1, 3, [])
        titles = " ".join(line["title"] for line in quote["lines"]).lower()
        self.assertNotIn("operator", titles)
        self.assertNotIn("کاربر", titles)

    def test_pricing_config_has_no_user_pricing_keys(self):
        config = catalog.pricing()
        self.assertNotIn("extra_user_usd", config)
        self.assertNotIn("max_users", config)

    def test_override_file_with_extra_user_usd_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            override_path = os.path.join(tmp, "catalog.json")
            with open(override_path, "w", encoding="utf-8") as f:
                json.dump({"pricing": {"extra_user_usd": 999.0, "max_users": 1,
                                       "base_monthly_usd": 5.0}}, f)
            catalog.OVERRIDE_FILE = override_path
            catalog.load(force=True)
            # override می‌گه extra_user_usd=999، ولی هیچ کدی دیگه اون کلید
            # رو نمی‌خونه، پس نباید توی قیمت اثر کنه -- فقط base_monthly_usd
            # و هزینه‌ی زیرساخت (که مستقل از این override است) حساب می‌شن.
            quote = pricing.quote(1, 1, [])
            expected = 5.0 + pricing.server_cost_per_bot()
            self.assertAlmostEqual(quote["monthly_usd"], expected, places=2)
            self.assertFalse(any("999" in line["title"] for line in quote["lines"]))


class PanelsHaveNoUsersTest(unittest.TestCase):

    def setUp(self):
        _use_default_catalog(self)

    def tearDown(self):
        catalog.OVERRIDE_FILE = _DEFAULT_OVERRIDE_FILE
        catalog.load(force=True)

    def test_no_panel_has_a_users_key(self):
        for panel in catalog.PANELS:
            self.assertNotIn("users", panel)

    def test_p2_is_gone_but_the_other_codes_stay_stable(self):
        codes = [p["code"] for p in catalog.PANELS]
        self.assertNotIn("p2", codes)
        self.assertEqual(codes, ["p1", "p3", "p4", "p5"])

    def test_panels_render_without_a_users_key(self):
        from licensing.telegram import keyboards as kb

        markup = kb.panels()
        self.assertEqual(len(markup.inline_keyboard), len(catalog.PANELS) + 2)

    def test_an_old_override_panel_with_users_still_renders(self):
        # یه سرورِ قدیمی ممکنه هنوز کل کاتالوگش رو (با پنل p2 و کلید
        # users) توی override نگه داشته باشه. کد باید این کلیدها رو نادیده
        # بگیره، نه کرش کنه.
        legacy_panels = copy.deepcopy(catalog.PANELS) + [{
            "code": "p2", "title_fa": "پنل قدیمی", "title_en": "Old plan",
            "months": 1, "users": 2, "bots": 1, "features": [],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            override_path = os.path.join(tmp, "catalog.json")
            with open(override_path, "w", encoding="utf-8") as f:
                json.dump({"panels": legacy_panels}, f, ensure_ascii=False)
            catalog.OVERRIDE_FILE = override_path
            catalog.load(force=True)

            from licensing.telegram import keyboards as kb

            codes = [p["code"] for p in catalog.panels()]
            self.assertIn("p2", codes)
            markup = kb.panels()  # نباید کرش کنه
            self.assertEqual(len(markup.inline_keyboard), len(codes) + 2)


class MaxOneMonthTest(unittest.TestCase):
    """
    تصمیمِ صاحبِ کسب‌وکار: هیچ خرید/تمدید/پنلی بیشتر از یه ماه نباشه. یه
    override قدیمی (این ماشین یا سرورِ واقعی) ممکنه هنوز مقادیرِ چندماهه
    داشته باشه؛ load() باید این‌ها رو *همیشه* کوتاه کنه، نه فقط پیش‌فرض‌های
    جدید کوتاه باشن.
    """

    def setUp(self):
        _use_default_catalog(self)

    def tearDown(self):
        catalog.OVERRIDE_FILE = _DEFAULT_OVERRIDE_FILE
        catalog.load(force=True)

    def test_default_panels_are_all_one_month(self):
        for panel in catalog.panels():
            self.assertEqual(panel["months"], 1, panel["code"])

    def test_default_duration_multipliers_has_only_one_month(self):
        self.assertEqual(list(catalog.pricing()["duration_multipliers"]), ["1"])

    def test_stale_override_with_multi_month_panels_is_clamped(self):
        legacy_panels = copy.deepcopy(catalog.PANELS)
        legacy_panels[0]["months"] = 6
        with tempfile.TemporaryDirectory() as tmp:
            override_path = os.path.join(tmp, "catalog.json")
            with open(override_path, "w", encoding="utf-8") as f:
                json.dump({
                    "panels": legacy_panels,
                    "pricing": {"duration_multipliers": {"1": 1.0, "3": 2.85, "12": 10.2}},
                }, f, ensure_ascii=False)
            catalog.OVERRIDE_FILE = override_path
            catalog.load(force=True)

            for panel in catalog.panels():
                self.assertEqual(panel["months"], 1, panel["code"])
            self.assertEqual(list(catalog.pricing()["duration_multipliers"]), ["1"])

    def test_renew_and_configurator_only_offer_one_month(self):
        from licensing.telegram import keyboards as kb

        markup = kb.renew_durations(1)
        # فقط یه دکمه‌ی تمدید (+دکمه‌ی برگشت).
        self.assertEqual(len(markup.inline_keyboard), 2)


if __name__ == "__main__":
    unittest.main()
