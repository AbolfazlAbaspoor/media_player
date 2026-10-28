"""
configure.py (ویزارد راه‌اندازی) و کمک‌های کانفیگ‌اش. همه‌چیز آفلاین: ورودی
ساختگی، شبکه mock، و همه‌ی مسیرها (کانفیگ/کلید/دیتابیس/data) توی پوشه‌ی
موقت -- به data/ واقعی و به هیچ لایسنسِ فروخته‌شده‌ای دست نمی‌زنه.
"""

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import configure
import license_server
from licensing import catalog
from licensing import cloudflare
from licensing import config
from licensing import db as db_module

TOKEN = "123456789:AAH-fake_token_for_unit_tests_0123456789"
ADMIN = 424242424
CARD = "6037 9975 1234 5678"

# آدرس‌های عمومیِ معتبر: قرارداد USDT روی ترون و روی BSC
TRON_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BSC_ADDRESS = "0x55d398326f99059fF775485246999027B3197955"

# اگه نسخه‌ی کانفیگ کلیدِ crypto.* داشته باشه، ویزارد یه سؤالِ بله/خیر اضافه می‌پرسه؛
# تست‌ها جواب اون سؤال رو از همین‌جا می‌گیرن تا به تعداد/اسمِ کلیدها بسته نباشن.
CRYPTO_NO = ["n"] if config.known_keys("crypto.") else []
HAS_CRYPTO = bool(CRYPTO_NO)

# متغیرهایی که نباید از محیطِ واقعیِ ماشین به تست نشت کنن
_ENV_NAMES = (
    [config.env_name(k) for k in configure.NAMED_FLAGS]
    + [config.env_name("crypto." + k) for k in ("address", "trongrid_api_key", "explorer_api_key")]
    + ["LICENSING_ADMIN_IDS", "CF_ACCOUNT_ID", "CF_KV_NAMESPACE", "CF_API_TOKEN"]
)


class Script:
    """جواب‌های از پیش‌تعیین‌شده؛ پرامپت‌ها هم برای بررسی ضبط می‌شن."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.prompts = []
        self.lines = []

    def prompter(self):
        return configure.Prompter(input_fn=self._ask, secret_fn=self._ask, out=self.lines.append)

    def _ask(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    @property
    def text(self):
        return "\n".join(self.lines + self.prompts)


class ConfigureCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        lic = os.path.join(self.root, "data", "licensing")
        self.data_dir = os.path.join(self.root, "data")

        for patcher in (
            mock.patch.object(config, "CONFIG_DIR", lic),
            mock.patch.object(config, "CONFIG_FILE", os.path.join(lic, "config.json")),
            mock.patch.object(config, "KEYS_DIR", os.path.join(lic, "keys")),
            mock.patch.object(catalog, "OVERRIDE_FILE", os.path.join(lic, "catalog.json")),
            mock.patch.object(db_module, "DB_PATH", os.path.join(lic, "licensing.sqlite3")),
            mock.patch.object(db_module, "_default", None),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in _ENV_NAMES:
            if name:
                os.environ.pop(name, None)
        for name in [n for n in os.environ if n.startswith("CONFIGURE_")]:
            os.environ.pop(name)
        config.reload()
        self.addCleanup(config.reload)

        # شبکه و چک نهایی و نصب: همیشه mock، مگه تست بخواد
        self.probe_patcher = mock.patch.object(configure, "probe_bot", return_value=(True, "@sales_bot"))
        self.probe = self.probe_patcher.start()
        self.addCleanup(self.probe_patcher.stop)
        self.check = self._patch(license_server, "cmd_check", return_value=0)

    def _patch(self, target, name, **kw):
        patcher = mock.patch.object(target, name, **kw)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def file_text(self):
        with open(config.CONFIG_FILE, "r", encoding="utf-8") as f:
            return f.read()

    def file_data(self):
        return json.loads(self.file_text())

    def run_wizard(self, argv, answers=()):
        script = Script(answers)
        captured = io.StringIO()  # چیزی که manage/install مستقیم print می‌کنن
        with contextlib.redirect_stdout(captured):
            code = configure.main(argv, prompter=script.prompter(), data_dir=self.data_dir)
        script.lines.extend(captured.getvalue().splitlines())
        return code, script

    # پاسخ‌های یه اجرای کامل تعاملی (بدون نصب: --skip-install)
    FULL = ["http://127.0.0.1:8080", TOKEN, f"Id: {ADMIN}", "6037-9975-1234-5678", "Ali", "Mellat", "",
            "n",   # Cloudflare؟
            *CRYPTO_NO,  # کریپتو؟
            "n",   # تنظیمات پیشرفته؟
            "y",   # نوشته بشه؟
            "n",   # ساخت ربات؟
            "n"]   # لایسنس مالک؟


class ConfigHelpersTest(ConfigureCase):

    def test_mask_never_reveals_the_middle_of_a_secret(self):
        masked = config.mask_secret(TOKEN)
        self.assertNotEqual(masked, TOKEN)
        self.assertNotIn(TOKEN[8:-4], masked)
        self.assertEqual(config.mask_secret(""), "")
        self.assertNotIn("abc", config.mask_secret("abc"))

    def test_secret_keys_are_recognised_by_name(self):
        for key in ("sales_bot_token", "cloudflare_api_token", "crypto.api_secret", "crypto.wallet_seed"):
            self.assertTrue(config.is_secret_key(key), key)
        for key in ("card_number", "admin_ids", "crypto.enabled"):
            self.assertFalse(config.is_secret_key(key), key)

    def test_mask_value_hides_proxy_credentials(self):
        self.assertNotIn("hunter2", config.mask_value("proxy_url", "http://bob:hunter2@10.0.0.1:8080"))
        self.assertEqual(config.mask_value("admin_ids", [1, 2]), "1, 2")

    def test_admin_ids_are_found_in_free_text(self):
        self.assertEqual(config.parse_admin_ids("Id: 123456789, ۹۸۷۶۵۴"), [123456789, 987654])
        self.assertEqual(config.parse_admin_ids("nothing"), [])

    def test_card_number_accepts_persian_digits_and_rejects_junk(self):
        self.assertEqual(config.normalize_card_number("۶۰۳۷-۹۹۷۵ 1234 5678"), CARD)
        self.assertIsNone(config.normalize_card_number("1234"))
        self.assertIsNone(config.normalize_card_number("abcd efgh ijkl mnop"))

    def test_save_values_merges_and_keeps_unknown_keys(self):
        config.write_template()
        config.save_values({"protected_licences": ["TT-X"]})
        config.save_values({"card_number": CARD})
        data = self.file_data()
        self.assertEqual(data["protected_licences"], ["TT-X"])
        self.assertEqual(data["card_number"], CARD)
        self.assertIn("grace_days", data)
        self.assertEqual(config.get("card_number"), CARD)  # cache refreshed

    def test_save_values_refuses_to_overwrite_a_malformed_file(self):
        os.makedirs(config.CONFIG_DIR, exist_ok=True)
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write('{"admin_ids": [1,]')
        before = self.file_text()
        with self.assertRaises(config.ConfigWriteError):
            config.save_values({"card_number": CARD})
        self.assertEqual(self.file_text(), before)

    def test_required_keys_line_up_with_missing_required(self):
        self.assertEqual(len(config.missing_required_keys()), len(config.missing_required()))
        config.save_values({"sales_bot_token": TOKEN, "admin_ids": [1], "card_number": CARD})
        self.assertEqual(config.missing_required_keys(), [])
        self.assertEqual(config.missing_required(), [])

    def test_known_keys_flatten_nested_and_flat_crypto_settings(self):
        nested = dict(config._DEFAULTS, crypto={"enabled": False, "api_secret": ""})
        with mock.patch.object(config, "_DEFAULTS", nested):
            self.assertEqual(config.known_keys("crypto."), ["crypto.api_secret", "crypto.enabled"])
            config.save_values({"crypto.enabled": True})
            self.assertEqual(self.file_data()["crypto"], {"enabled": True})
            config.save_values({"crypto.api_secret": "x"})
            self.assertEqual(self.file_data()["crypto"], {"enabled": True, "api_secret": "x"})
        flat = {k: v for k, v in config._DEFAULTS.items() if not k.startswith("crypto")}
        flat["crypto.enabled"] = False
        with mock.patch.object(config, "_DEFAULTS", flat):
            self.assertEqual(config.known_keys("crypto."), ["crypto.enabled"])
            config.save_values({"crypto.enabled": True})
            self.assertIs(self.file_data()["crypto.enabled"], True)
        no_crypto = {k: v for k, v in config._DEFAULTS.items() if not k.startswith("crypto")}
        with mock.patch.object(config, "_DEFAULTS", no_crypto):
            self.assertEqual(config.known_keys("crypto."), [])  # بدون کلید: خالی، بدون خطا


class NetworkTest(ConfigureCase):

    def test_probe_uses_the_explicit_proxy_and_ignores_the_environment(self):
        self.probe_patcher.stop()
        self.addCleanup(self.probe_patcher.start)
        created = {}

        class FakeClient:
            def __init__(self, **kw):
                created.update(kw)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url):
                created["url"] = url
                return mock.Mock(json=lambda: {"ok": True, "result": {"username": "sales_bot"}})

        with mock.patch("httpx.Client", FakeClient):
            ok, detail = configure.probe_bot(TOKEN, "socks5://127.0.0.1:1080")
        self.assertEqual((ok, detail), (True, "@sales_bot"))
        self.assertIs(created["trust_env"], False)
        self.assertEqual(created["proxy"], "socks5://127.0.0.1:1080")

    def test_probe_failures_never_contain_the_token(self):
        self.probe_patcher.stop()
        self.addCleanup(self.probe_patcher.start)
        with mock.patch.object(configure, "_http_get_json",
                               side_effect=RuntimeError(f"boom https://x/bot{TOKEN}/getMe")):
            ok, detail = configure.probe_bot(TOKEN)
        self.assertFalse(ok)
        self.assertNotIn(TOKEN, detail)
        with mock.patch.object(configure, "_http_get_json",
                               return_value={"ok": False, "description": "Unauthorized"}):
            self.assertEqual(configure.probe_bot(TOKEN), (False, "Unauthorized"))

    def test_temp_env_restores_the_environment(self):
        os.environ["CF_API_TOKEN"] = "original"
        with configure._temp_env({"CF_API_TOKEN": "candidate", "CF_ACCOUNT_ID": "a"}):
            self.assertEqual(os.environ["CF_API_TOKEN"], "candidate")
        self.assertEqual(os.environ["CF_API_TOKEN"], "original")
        self.assertNotIn("CF_ACCOUNT_ID", os.environ)


class InteractiveTest(ConfigureCase):

    def test_full_run_writes_the_config_and_masks_the_token(self):
        code, script = self.run_wizard(["--skip-install"], self.FULL)
        self.assertEqual(code, 0, script.text)
        data = self.file_data()
        self.assertEqual(data["sales_bot_token"], TOKEN)
        self.assertEqual(data["proxy_url"], "http://127.0.0.1:8080")
        self.assertEqual(data["admin_ids"], [ADMIN])
        self.assertEqual(data["card_number"], CARD)
        self.assertEqual((data["card_holder"], data["card_bank"]), ("Ali", "Mellat"))
        self.assertNotIn(TOKEN, script.text)  # هیچ‌جا کامل چاپ نشده
        self.assertIn(config.mask_secret(TOKEN), script.text)
        self.probe.assert_called_with(TOKEN, "http://127.0.0.1:8080")
        self.check.assert_called_once()
        if os.name == "posix":
            self.assertEqual(os.stat(config.CONFIG_FILE).st_mode & 0o777, 0o600)

    def test_proxy_is_asked_before_the_token(self):
        _code, script = self.run_wizard(["--skip-install"], self.FULL)
        order = [p for p in script.prompts if "Proxy" in p or "token" in p.lower()]
        self.assertIn("Proxy", order[0])
        self.assertIn("token", order[1].lower())

    def test_required_fields_are_asked_again_when_left_blank_or_invalid(self):
        answers = ["", "not-a-token", TOKEN,          # توکن
                   "", "no ids here", str(ADMIN),     # ادمین
                   "12", CARD]                        # کارت
        answers = [""] + answers + ["", "", ""] + ["n"] + CRYPTO_NO + ["n", "y", "n", "n"]
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        self.assertIn("required", script.text)
        self.assertEqual(self.file_data()["admin_ids"], [ADMIN])

    def test_rerun_is_idempotent_and_shows_masked_defaults(self):
        self.run_wizard(["--skip-install"], self.FULL)
        config.save_values({"protected_licences": ["TT-KEEP"]})
        before = self.file_text()

        # هر فیلد Enter؛ CF/کریپتو/پیشرفته پیش‌فرض (خیر)؛ ربات/لایسنس n
        blanks = [""] * 7 + [""] + [""] * len(CRYPTO_NO) + ["", "n", "n"]
        code, script = self.run_wizard(["--skip-install"], blanks)
        self.assertEqual(code, 0, script.text)
        self.assertEqual(self.file_text(), before)
        self.assertIn("No changes", script.text)
        shown = "\n".join(script.prompts)
        self.assertIn(f"[{config.mask_secret(TOKEN)}]", shown)
        self.assertNotIn(TOKEN, script.text)
        self.assertIn(f"[{CARD}]", shown)

    def test_only_the_edited_field_changes(self):
        self.run_wizard(["--skip-install"], self.FULL)
        answers = ["", "", "", "", "Reza", "", "", ""] + [""] * len(CRYPTO_NO) + ["", "y", "n", "n"]
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        data = self.file_data()
        self.assertEqual(data["card_holder"], "Reza")
        self.assertEqual(data["sales_bot_token"], TOKEN)
        self.assertIn("card_holder: Ali -> Reza", script.text)

    def test_declining_the_write_confirmation_leaves_the_file_alone(self):
        answers = list(self.FULL)
        answers[9 + len(CRYPTO_NO)] = "n"
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(self.file_data()["sales_bot_token"], "")
        self.assertIn("Not written", script.text)

    def test_failed_getme_offers_a_choice_and_can_change_the_proxy(self):
        self.probe.side_effect = [(False, "ConnectError"), (True, "@sales_bot")]
        answers = ["", TOKEN, "p", "http://10.0.0.1:3128",   # پروکسی اول خالی، getMe شکست، عوض کردن پروکسی
                   str(ADMIN), CARD, "", "", "", "n", *CRYPTO_NO, "n", "y", "n", "n"]
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        self.assertEqual(self.file_data()["proxy_url"], "http://10.0.0.1:3128")
        self.assertEqual(self.probe.call_args_list[1].args, (TOKEN, "http://10.0.0.1:3128"))

    def test_discarding_a_token_that_fails_getme_does_not_save_it(self):
        self.probe.return_value = (False, "Unauthorized")
        answers = ["", TOKEN, "s", str(ADMIN), CARD, "", "", "", "n", *CRYPTO_NO, "n", "y", "n", "n"]
        self.run_wizard(["--skip-install"], answers)
        self.assertEqual(self.file_data()["sales_bot_token"], "")

    def test_input_ending_early_exits_cleanly(self):
        code, _ = self.run_wizard(["--skip-install"], ["http://127.0.0.1:8080"])
        self.assertEqual(code, 1)

    def test_a_malformed_config_file_is_never_overwritten(self):
        os.makedirs(config.CONFIG_DIR, exist_ok=True)
        with open(config.CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write("{oops")
        code, script = self.run_wizard(["--skip-install"], self.FULL)
        self.assertEqual(code, 1)
        self.assertEqual(self.file_text(), "{oops")
        self.assertEqual(script.prompts, [])

    def test_old_python_stops_the_wizard(self):
        with mock.patch.object(configure, "MIN_PYTHON", (99, 0)):
            code, _ = self.run_wizard(["--skip-install"], [])
        self.assertEqual(code, 1)

    def test_environment_override_is_reported(self):
        os.environ["LICENSING_CARD_HOLDER"] = "FromEnv"
        self.addCleanup(os.environ.pop, "LICENSING_CARD_HOLDER", None)
        answers = list(self.FULL)
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertIn("LICENSING_CARD_HOLDER overrides card_holder", script.text)
        # مقدار env توی فایل نریخته، مقداری که ادمین تایپ کرده نوشته شده
        self.assertEqual(self.file_data()["card_holder"], "Ali")


class CloudflareAndCryptoTest(ConfigureCase):

    CF = ["y", "acc123", "0123456789abcdef0123456789abcdef", "cf-secret-token-0123456789"]

    def test_cloudflare_values_are_validated_with_the_candidates_then_saved(self):
        seen = {}

        def fake_check():
            seen.update(os.environ)
            return True, "connected"

        with mock.patch.object(cloudflare, "check_connection", fake_check):
            answers = ["", TOKEN, str(ADMIN), CARD, "", "", ""] + self.CF + CRYPTO_NO + ["n", "y", "n", "n"]
            code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        self.assertEqual(seen["CF_API_TOKEN"], "cf-secret-token-0123456789")
        self.assertNotIn("CF_API_TOKEN", os.environ)
        data = self.file_data()
        self.assertEqual(data["cloudflare_account_id"], "acc123")
        self.assertEqual(data["cloudflare_api_token"], "cf-secret-token-0123456789")
        self.assertNotIn("cf-secret-token-0123456789", script.text)

    def test_cloudflare_failure_can_be_discarded(self):
        with mock.patch.object(cloudflare, "check_connection", return_value=(False, "403 bad token")):
            answers = ["", TOKEN, str(ADMIN), CARD, "", "", ""] + self.CF + ["s"] + CRYPTO_NO + ["n", "y", "n", "n"]
            code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(self.file_data()["cloudflare_api_token"], "")
        self.assertIn("403 bad token", script.text)

    def test_crypto_step_is_skipped_quietly_when_the_config_has_no_crypto_keys(self):
        real = config.known_keys
        with mock.patch.object(config, "known_keys",
                               lambda prefix="": [] if prefix.startswith("crypto.") else real(prefix)):
            code, script = self.run_wizard(["--skip-install"], self.no_crypto_full())
        self.assertEqual(code, 0, script.text)
        self.assertIn("no crypto.* settings", script.text)
        self.assertNotIn("Configure crypto", script.text)

    def no_crypto_full(self):
        """FULL، ولی بدون سؤالِ کریپتو (وقتی known_keys("crypto.") رو خالی کردیم)."""
        answers = list(self.FULL)
        if CRYPTO_NO:
            del answers[8]
        return answers

    def test_crypto_question_defaults_to_no_and_writes_nothing(self):
        if not HAS_CRYPTO:
            self.skipTest("this version has no crypto.* settings")
        code, script = self.run_wizard(["--skip-install"], self.FULL)
        self.assertEqual(code, 0, script.text)
        self.assertIn("Configure crypto", script.text)
        self.assertNotIn("Network (trc20", script.text)
        self.assertEqual(self.file_data()["crypto"]["enabled"], False)
        self.assertEqual(self.file_data()["crypto"]["address"], "")

    def crypto_answers(self, crypto):
        """FULL با یه بلوکِ کریپتو به‌جای «n»ی کریپتو."""
        answers = list(self.FULL)
        answers[8:9] = crypto
        return answers

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_crypto_step_validates_the_address_and_writes_the_nested_layout(self):
        from licensing import crypto_pay
        answers = self.crypto_answers([
            "y",                     # تنظیم بشه؟
            "trc20",                 # network
            "TXYZ", TRON_ADDRESS,    # address: اول غلط، بعد درست
            "45",                    # expiry_minutes
            "",                      # min_confirmations: همون پیش‌فرض
            "tg-secret-key-0123456789",  # trongrid_api_key (explorer_api_key برای trc20 پرسیده نمی‌شه)
            "y",                     # فعال بشه؟
        ])
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        self.assertIn("not a valid", script.text)
        crypto = self.file_data()["crypto"]
        self.assertEqual(crypto["address"], TRON_ADDRESS)
        self.assertEqual(crypto["expiry_minutes"], 45)
        self.assertEqual(crypto["trongrid_api_key"], "tg-secret-key-0123456789")
        self.assertIs(crypto["enabled"], True)
        self.assertNotIn("crypto.address", self.file_data())  # تودرتو، نه کلیدِ نقطه‌دار
        self.assertNotIn("tg-secret-key-0123456789", script.text)
        self.assertNotIn("crypto.explorer_api_key", " ".join(script.prompts))
        self.assertTrue(crypto_pay.available(config.crypto_settings()))

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_crypto_address_is_checked_against_the_chosen_network(self):
        answers = self.crypto_answers(["y", "bep20", TRON_ADDRESS, BSC_ADDRESS, "", "explorer-key-0123456789", "", "y"])
        # bep20: explorer_api_key پرسیده می‌شه و trongrid_api_key نه
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        crypto = self.file_data()["crypto"]
        self.assertEqual((crypto["network"], crypto["address"]), ("bep20", BSC_ADDRESS))
        self.assertEqual(crypto["explorer_api_key"], "explorer-key-0123456789")
        self.assertIn("not a valid", script.text)

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_enabling_crypto_without_an_address_warns(self):
        answers = self.crypto_answers(["y", "", "", "", "", "", "y"])
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertIn("would not work yet", script.text)

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_a_crypto_only_seller_does_not_need_a_card_number(self):
        config.save_values({"crypto": {"enabled": True, "address": TRON_ADDRESS}})
        self.assertNotIn("card_number", config.missing_required_keys())
        self.assertEqual(len(config.missing_required_keys()), len(config.missing_required()))


class NonInteractiveTest(ConfigureCase):

    BASE = ["--non-interactive", "--skip-install", "--sales-token", TOKEN, "--admin-ids", str(ADMIN),
            "--card-number", CARD]

    def test_flags_are_written_and_checked(self):
        code, script = self.run_wizard(self.BASE + ["--proxy-url", "127.0.0.1:2080", "--card-holder", "Ali"])
        self.assertEqual(code, 0, script.text)
        self.assertEqual(script.prompts, [])  # هیچ سؤالی نپرسید
        data = self.file_data()
        self.assertEqual(data["proxy_url"], "http://127.0.0.1:2080")  # normalize شد
        self.assertEqual(data["card_holder"], "Ali")
        self.assertNotIn(TOKEN, script.text)
        self.probe.assert_called_once_with(TOKEN, "http://127.0.0.1:2080")

    def test_values_come_from_the_environment_too(self):
        os.environ.update({"LICENSING_BOT_TOKEN": TOKEN, "LICENSING_ADMIN_IDS": str(ADMIN),
                           "LICENSING_CARD_NUMBER": CARD, "CONFIGURE_GRACE_DAYS": "9"})
        code, _ = self.run_wizard(["--non-interactive", "--skip-install"])
        self.assertEqual(code, 0)
        data = self.file_data()
        self.assertEqual((data["sales_bot_token"], data["admin_ids"], data["grace_days"]),
                         (TOKEN, [ADMIN], 9))

    def test_set_flag_writes_any_known_key_with_its_type(self):
        code, _ = self.run_wizard(self.BASE + ["--set", "reminder_days=5,2", "--set", "hosting_enabled=false"])
        self.assertEqual(code, 0)
        data = self.file_data()
        self.assertEqual(data["reminder_days"], [5, 2])
        self.assertIs(data["hosting_enabled"], False)

    def test_unknown_key_is_a_usage_error_but_unknown_crypto_key_is_ignored(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            configure.parse_args(["--non-interactive", "--set", "nope=1"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            args = configure.parse_args(["--non-interactive", "--set", "crypto.no_such_setting=true"])
        self.assertEqual(args.set_values, {})
        self.assertIn("ignored", out.getvalue())

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_crypto_keys_are_taken_from_set_and_env_and_validated(self):
        os.environ["LICENSING_TRONGRID_API_KEY"] = "s3cret-value-0123456789"
        code, script = self.run_wizard(self.BASE + ["--set", "crypto.enabled=true",
                                                    "--set", f"crypto.address={TRON_ADDRESS}",
                                                    "--set", "crypto.expiry_minutes=60"])
        self.assertEqual(code, 0, script.text)
        crypto = self.file_data()["crypto"]
        self.assertEqual((crypto["enabled"], crypto["address"], crypto["expiry_minutes"]),
                         (True, TRON_ADDRESS, 60))
        self.assertEqual(crypto["trongrid_api_key"], "s3cret-value-0123456789")
        self.assertNotIn("s3cret-value-0123456789", script.text)
        self.assertIn("LICENSING_TRONGRID_API_KEY overrides crypto.trongrid_api_key", script.text)

    @unittest.skipUnless(HAS_CRYPTO, "this version has no crypto.* settings")
    def test_a_crypto_address_that_fails_the_validator_is_not_saved(self):
        code, script = self.run_wizard(self.BASE + ["--set", "crypto.network=bep20",
                                                    "--set", f"crypto.address={TRON_ADDRESS}"])
        self.assertEqual(code, 1)
        self.assertEqual(self.file_data()["crypto"]["address"], "")
        self.assertIn("crypto.address", script.text)

    def test_a_token_that_fails_getme_is_not_saved_and_the_exit_code_says_so(self):
        self.probe.return_value = (False, "ConnectError")
        code, script = self.run_wizard(self.BASE)
        self.assertEqual(code, 1)
        self.assertEqual(self.file_data()["sales_bot_token"], "")
        self.assertEqual(self.file_data()["admin_ids"], [ADMIN])  # بقیه نوشته شد
        self.assertIn("not saved", script.text)

    def test_skip_network_saves_unchecked(self):
        self.probe.return_value = (False, "ConnectError")
        code, _ = self.run_wizard(self.BASE + ["--skip-network"])
        self.assertEqual(code, 0)
        self.assertEqual(self.file_data()["sales_bot_token"], TOKEN)
        self.probe.assert_not_called()

    def test_invalid_values_are_reported_not_written(self):
        code, script = self.run_wizard(["--non-interactive", "--skip-install", "--sales-token", "bad",
                                        "--card-number", "12", "--admin-ids", "x"])
        self.assertEqual(code, 1)
        self.assertEqual(len([line for line in script.lines if line.startswith("Problem:")]), 3)
        self.assertEqual(self.file_data()["card_number"], "")

    def test_cloudflare_flags(self):
        with mock.patch.object(cloudflare, "check_connection", return_value=(True, "ok")):
            code, _ = self.run_wizard(self.BASE + ["--cf-account-id", "a1", "--cf-kv-namespace", "n1",
                                                   "--cf-api-token", "tok-0123456789abcdefghij"])
        self.assertEqual(code, 0)
        self.assertEqual(self.file_data()["cloudflare_kv_namespace"], "n1")

    def test_twice_is_a_noop(self):
        self.run_wizard(self.BASE)
        before = self.file_text()
        code, script = self.run_wizard(self.BASE)
        self.assertEqual(code, 0)
        self.assertEqual(self.file_text(), before)
        self.assertIn("No changes", script.text)


class BotAndLicenceTest(ConfigureCase):

    BOT = ["--create-bot", "--bot-host", "tt.example", "--bot-port", "10444", "--bot-name", "bot1",
           "--bot-username", "user", "--bot-password", "bot-pw-secret"]

    def test_bot_files_are_created_once_and_never_overwritten(self):
        base = NonInteractiveTest.BASE
        code, script = self.run_wizard(base + self.BOT)
        self.assertEqual(code, 0, script.text)
        bot_dir = os.path.join(self.data_dir, "tt.example_10444", "bot1")
        identity_path = os.path.join(bot_dir, "identity.json")
        self.assertTrue(os.path.isfile(os.path.join(self.data_dir, "tt.example_10444", "shared_config.json")))
        with open(identity_path, encoding="utf-8") as f:
            identity = json.load(f)
        self.assertEqual(identity["server"]["username"], "user")
        self.assertNotIn("bot-pw-secret", script.text)

        identity["server"]["nickname"] = "Edited"
        with open(identity_path, "w", encoding="utf-8") as f:
            json.dump(identity, f)
        self.run_wizard(base + self.BOT)
        with open(identity_path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["server"]["nickname"], "Edited")

    def test_create_bot_without_a_host_is_an_error(self):
        code, script = self.run_wizard(NonInteractiveTest.BASE + ["--create-bot"])
        self.assertEqual(code, 1)
        self.assertIn("--bot-host", script.text)

    def test_self_licence_is_created_with_the_bot_dir_then_not_repeated(self):
        base = NonInteractiveTest.BASE + self.BOT + ["--self-license"]
        code, script = self.run_wizard(base)
        self.assertEqual(code, 0, script.text)
        bot_dir = os.path.join(self.data_dir, "tt.example_10444", "bot1")
        self.assertTrue(os.path.isfile(os.path.join(bot_dir, "license.json")))
        rows = db_module.get_db().licenses_by_user(ADMIN)
        self.assertEqual(len(rows), 1)
        key = rows[0]["key"]

        code, script = self.run_wizard(base)
        self.assertEqual(code, 0, script.text)
        self.assertEqual(len(db_module.get_db().licenses_by_user(ADMIN)), 1)
        self.assertIn("already has a licence", script.text)

    def test_self_licence_uses_the_first_admin_and_is_skipped_without_the_flag(self):
        with mock.patch("manage.cmd_self_license", return_value=0) as called:
            self.run_wizard(NonInteractiveTest.BASE)
            called.assert_not_called()
            self.run_wizard(NonInteractiveTest.BASE + ["--self-license"])
            called.assert_called_once_with([str(ADMIN)])

    def test_interactive_bot_creation(self):
        answers = list(self.FULL)
        answers[10 + len(CRYPTO_NO):] = ["y",                                 # ساخت ربات
                        "tt.example", "", "", "", "user", "pw", "", "",  # host, port, name, nick, user, pw, channel, chpw
                        "n"]                                 # لایسنس
        code, script = self.run_wizard(["--skip-install"], answers)
        self.assertEqual(code, 0, script.text)
        self.assertTrue(os.path.isfile(os.path.join(self.data_dir, "tt.example_10333", "bot1", "identity.json")))
        self.assertNotIn("pw\n", script.text)


class ComponentsTest(ConfigureCase):

    def fake_install(self, missing, calls):
        import install

        def run(names, dry_run, with_licensing, venv):
            name = names[0]
            if dry_run:
                return {name: install.Status.PLANNED if name in missing else install.Status.OK}
            calls.append(name)
            return {name: install.Status.DONE}
        return mock.patch.object(install, "run", run)

    def test_interactive_asks_before_installing_each_missing_component(self):
        calls = []
        with self.fake_install({"ffmpeg", "tesseract"}, calls):
            answers = ["y", "n"] + self.FULL  # ffmpeg بله؛ tesseract (اختیاری) نه
            code, script = self.run_wizard([], answers)
        self.assertEqual(code, 0, script.text)
        self.assertEqual(calls, ["ffmpeg"])
        self.assertIn("ffmpeg is not installed", script.text)

    def test_declining_a_required_component_is_remembered_as_a_warning(self):
        calls = []
        with self.fake_install({"libmpv"}, calls):
            answers = ["n"] + self.FULL
            code, script = self.run_wizard([], answers)
        self.assertEqual(calls, [])
        self.assertIn("Warning: libmpv is not installed", script.text)

    def test_missing_python_packages_trigger_the_python_step(self):
        calls = []
        with self.fake_install(set(), calls), \
                mock.patch("importlib.util.find_spec", side_effect=lambda m: None if m == "cryptography" else object()):
            answers = ["y"] + self.FULL
            self.run_wizard([], answers)
        self.assertEqual(calls, ["python"])

    def test_non_interactive_installs_only_what_was_asked_for(self):
        calls = []
        with self.fake_install({"ffmpeg", "libmpv"}, calls):
            code, script = self.run_wizard(["--non-interactive", "--install-components", "ffmpeg"])
        self.assertEqual(calls, ["ffmpeg"])
        self.assertIn("Warning: libmpv is not installed", script.text)

    def test_default_keyword_installs_required_but_not_optional(self):
        calls = []
        with self.fake_install({"ffmpeg", "tesseract"}, calls):
            self.run_wizard(["--non-interactive", "--install-components", "default"])
        self.assertEqual(calls, ["ffmpeg"])

    def test_install_probe_output_is_not_printed(self):
        calls = []
        with self.fake_install(set(), calls):
            _code, script = self.run_wizard(["--non-interactive"])
        self.assertNotIn("dry-run", script.text)


class InitFilesTest(ConfigureCase):

    def test_the_real_init_files_run_in_a_temp_tree(self):
        code, script = self.run_wizard(["--non-interactive", "--skip-install", "--skip-check"])
        self.assertEqual(code, 0, script.text)
        for path in (config.CONFIG_FILE, catalog.OVERRIDE_FILE, db_module.DB_PATH):
            self.assertTrue(os.path.isfile(path), path)
        self.assertIn("Created:", script.text)

    def test_skip_check_does_not_run_the_check(self):
        self.run_wizard(["--non-interactive", "--skip-install", "--skip-check"])
        self.check.assert_not_called()

    def test_check_failure_sets_the_exit_code(self):
        self.check.return_value = 1
        code, _ = self.run_wizard(NonInteractiveTest.BASE)
        self.assertEqual(code, 1)


class Cf_token_uses_shared_writerTest(ConfigureCase):

    def test_manage_cf_token_writes_through_save_values(self):
        import manage
        config.write_template()
        with mock.patch.object(cloudflare, "check_connection", return_value=(True, "ok")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(manage.cmd_cf_token(["t" * 30]), 0)
        self.assertEqual(self.file_data()["cloudflare_api_token"], "t" * 30)
        self.assertIn("grace_days", self.file_data())


class DocsTest(unittest.TestCase):

    def test_configure_doc_exists_and_is_linked_from_the_install_docs(self):
        docs = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
        self.assertTrue(os.path.isfile(os.path.join(docs, "CONFIGURE.md")))
        for name in ("INSTALL.md", "INSTALL-linux.md", "SERVER.md"):
            with open(os.path.join(docs, name), encoding="utf-8") as f:
                self.assertIn("CONFIGURE.md", f.read(), name)


if __name__ == "__main__":
    unittest.main()
