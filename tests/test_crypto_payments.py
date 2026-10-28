"""
USDT payments: the bot only watches a public address (TronGrid mocked here,
nothing touches the network). Covers matching, unique amounts, expiry,
duplicate transactions, wrong amounts, disabled config, the shared approval
path, the old-database migration and the keyboards/invoice text.
"""

import asyncio
import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from licensing import config
from licensing import crypto_pay
from licensing import db as db_module

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def tron_address(seed):
    """A syntactically valid TRON address (0x41 + 20 bytes + checksum)."""
    payload = b"\x41" + hashlib.sha256(seed.encode()).digest()[:20]
    raw = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    number = int.from_bytes(raw, "big")
    text = ""
    while number:
        number, rest = divmod(number, 58)
        text = _B58[rest] + text
    return text


ADDRESS = tron_address("shop")
OTHER_ADDRESS = tron_address("somebody else")
API_KEY = "test-key-123"


def settings(**overrides):
    base = {"enabled": True, "network": "trc20", "address": ADDRESS,
            "trongrid_api_key": API_KEY, "explorer_api_key": "",
            "expiry_minutes": 30, "min_confirmations": 1}
    base.update(overrides)
    return base


def grid_reply(*transfers):
    """TronGrid's /transactions/trc20 answer for (hash, to, micro, seconds) tuples."""
    return {"success": True, "data": [{
        "transaction_id": tx, "to": to, "from": "T" + "x" * 33, "type": "Transfer",
        "value": str(micro), "block_timestamp": ts * 1000,
        "token_info": {"address": crypto_pay.USDT_TRC20_CONTRACT, "symbol": "USDT",
                       "decimals": 6},
    } for tx, to, micro, ts in transfers]}


class CryptoBase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = db_module.Database(os.path.join(self.tmp, "t.sqlite3"))
        self.settings = settings()
        mock.patch("licensing.config.crypto_settings",
                   side_effect=lambda: dict(self.settings)).start()
        self.http = mock.patch("licensing.crypto_pay._http_json",
                               return_value=grid_reply()).start()

    def tearDown(self):
        mock.patch.stopall()
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def order(self, usd=12.5, user_id=555):
        return self.db.create_order(user_id=user_id, months=1, users=1, bots=1,
                                    features=[], amount_usd=usd, status="awaiting_receipt")

    def payment(self, usd=12.5, now=None, user_id=555):
        order = self.order(usd, user_id)
        return order, crypto_pay.create_payment(self.db, order, now=now)


class MatchingTest(CryptoBase):

    def test_exact_amount_to_our_address_inside_the_window_is_matched(self):
        order, payment = self.payment()
        amount = int(payment["amount_micro"])
        self.http.return_value = grid_reply(("tx1", ADDRESS, amount, int(time.time())))

        result = crypto_pay.check_pending(self.db)

        self.assertEqual(len(result.matched), 1)
        row = self.db.get_crypto_payment(int(payment["id"]))
        self.assertEqual((row["status"], row["tx_hash"]), ("paid", "tx1"))
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "awaiting_crypto")

    def test_request_targets_trongrid_usdt_endpoint_with_the_optional_key(self):
        self.payment()
        crypto_pay.check_pending(self.db)
        url, headers = self.http.call_args[0][0], self.http.call_args[0][1]
        self.assertIn(f"https://api.trongrid.io/v1/accounts/{ADDRESS}/transactions/trc20?", url)
        self.assertIn("only_to=true", url)
        self.assertIn(f"contract_address={crypto_pay.USDT_TRC20_CONTRACT}", url)
        self.assertIn("only_confirmed=true", url)
        self.assertEqual(headers, {"TRON-PRO-API-KEY": API_KEY})

    def test_no_api_key_means_no_header_and_zero_confirmations_means_unconfirmed_ok(self):
        self.settings.update(trongrid_api_key="", min_confirmations=0)
        self.payment()
        crypto_pay.check_pending(self.db)
        url, headers = self.http.call_args[0][0], self.http.call_args[0][1]
        self.assertEqual(headers, {})
        self.assertNotIn("only_confirmed", url)

    def test_the_same_transaction_cannot_pay_two_orders(self):
        _, first = self.payment()
        amount = int(first["amount_micro"])
        tx = ("tx1", ADDRESS, amount, int(time.time()))
        self.http.return_value = grid_reply(tx)
        crypto_pay.check_pending(self.db)

        # A later order happens to draw the same amount (the first one is no
        # longer pending) and even has an old enough creation time.
        second_order = self.order()
        second = crypto_pay.create_payment(self.db, second_order, rng=_FixedRng(amount))
        self.assertEqual(int(second["amount_micro"]), amount)
        self.db._execute("UPDATE crypto_payments SET created_at = created_at - 100 WHERE id = ?",
                         (int(second["id"]),))

        result = crypto_pay.check_pending(self.db)

        self.assertEqual(result.matched, [])
        self.assertEqual(self.db.get_crypto_payment(int(second["id"]))["status"], "pending")
        self.assertFalse(self.db.claim_crypto_payment(int(second["id"]), "tx1"))

    def test_a_reused_hash_does_not_block_a_different_valid_transaction(self):
        _, first = self.payment()
        amount = int(first["amount_micro"])
        now = int(time.time())
        self.http.return_value = grid_reply(("tx1", ADDRESS, amount, now))
        crypto_pay.check_pending(self.db)
        second_order = self.order()
        second = crypto_pay.create_payment(self.db, second_order, rng=_FixedRng(amount))
        self.db._execute("UPDATE crypto_payments SET created_at = created_at - 100 WHERE id = ?",
                         (int(second["id"]),))
        self.http.return_value = grid_reply(("tx1", ADDRESS, amount, now),
                                            ("tx2", ADDRESS, amount, now + 1))

        result = crypto_pay.check_pending(self.db)

        self.assertEqual([t.tx_hash for _, t in result.matched], ["tx2"])

    def test_wrong_amount_wrong_address_and_out_of_window_are_ignored(self):
        _, payment = self.payment()
        amount = int(payment["amount_micro"])
        now = int(time.time())
        self.http.return_value = grid_reply(
            ("under", ADDRESS, amount - 100, now),
            ("over", ADDRESS, amount + 100, now),
            ("elsewhere", OTHER_ADDRESS, amount, now),
            ("before", ADDRESS, amount, int(payment["created_at"]) - 1),
            ("after", ADDRESS, amount, int(payment["expires_at"]) + 1),
        )

        result = crypto_pay.check_pending(self.db)

        self.assertEqual(result.matched, [])
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "pending")

    def test_a_foreign_token_with_the_right_amount_is_ignored(self):
        _, payment = self.payment()
        reply = grid_reply(("fake", ADDRESS, int(payment["amount_micro"]), int(time.time())))
        reply["data"][0]["token_info"]["address"] = "T" + "F" * 33
        self.http.return_value = reply
        self.assertEqual(crypto_pay.check_pending(self.db).matched, [])

    def test_an_unreachable_service_is_reported_not_raised(self):
        _, payment = self.payment()
        self.http.side_effect = crypto_pay.CryptoNetworkError("HTTP 500")
        result = crypto_pay.check_pending(self.db)
        self.assertTrue(result.failed)
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "pending")

    def test_nothing_pending_means_no_network_call(self):
        crypto_pay.check_pending(self.db)
        self.http.assert_not_called()

    def test_bep20_reads_the_explorer_shape_and_respects_confirmations(self):
        evm = "0x" + "ab" * 20
        self.settings.update(network="bep20", address=evm, explorer_api_key="k",
                             min_confirmations=3)
        order = self.order()
        payment = crypto_pay.create_payment(self.db, order)
        micro = int(payment["amount_micro"])
        now = int(time.time())
        row = {"hash": "0xaaa", "to": evm.upper().replace("0X", "0x"), "value": str(micro * 10 ** 12),
               "tokenDecimal": "18", "timeStamp": str(now), "confirmations": "2",
               "contractAddress": crypto_pay.USDT_BEP20_CONTRACT.lower()}
        self.http.return_value = {"status": "1", "message": "OK", "result": [row]}
        self.assertEqual(crypto_pay.check_pending(self.db).matched, [])   # 2 < 3

        row["confirmations"] = "3"
        result = crypto_pay.check_pending(self.db)

        self.assertEqual([t.tx_hash for _, t in result.matched], ["0xaaa"])
        self.assertIn("chainid=56", self.http.call_args[0][0])


class _FixedRng:
    """rng stand-in that always picks `amount` (it is among the free candidates)."""

    def __init__(self, amount):
        self.amount = amount

    def choice(self, candidates):
        assert self.amount in candidates
        return self.amount


class UniqueAmountTest(CryptoBase):

    def test_amounts_are_price_plus_a_small_offset_and_never_repeat(self):
        amounts = set()
        for index in range(60):
            _, payment = self.payment(12.5, user_id=1000 + index)
            amounts.add(int(payment["amount_micro"]))
        self.assertEqual(len(amounts), 60)
        for amount in amounts:
            offset = amount - 12_500_000
            self.assertTrue(100 <= offset <= 99_900, offset)
            self.assertEqual(offset % 100, 0)

    def test_pressing_the_button_twice_reuses_the_open_invoice(self):
        order = self.order()
        first = crypto_pay.create_payment(self.db, order)
        second = crypto_pay.create_payment(self.db, order)
        self.assertEqual(int(first["id"]), int(second["id"]))
        self.assertEqual(len(self.db.pending_crypto_payments()), 1)

    def test_running_out_of_free_amounts_is_reported_as_busy(self):
        with mock.patch.object(crypto_pay, "OFFSET_MAX_STEPS", 2):
            self.payment(5)
            self.payment(5)
            with self.assertRaises(crypto_pay.CryptoBusy):
                self.payment(5)

    def test_a_freed_amount_can_be_used_again(self):
        with mock.patch.object(crypto_pay, "OFFSET_MAX_STEPS", 1):
            order, payment = self.payment(5)
            crypto_pay.cancel_for_order(self.db, int(order["id"]))
            _, again = self.payment(5)
            self.assertEqual(int(again["amount_micro"]), int(payment["amount_micro"]))

    def test_the_database_itself_refuses_two_pending_payments_with_one_amount(self):
        _, payment = self.payment()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.create_crypto_payment(
                99, 1, payment["network"], payment["address"], int(payment["amount_micro"]),
                int(time.time()) + 100)

    def test_the_price_is_converted_without_float_error(self):
        self.assertEqual(crypto_pay.usd_to_micro(0.1 + 0.2), 300_000)
        self.assertEqual(crypto_pay.usd_to_micro(19.99), 19_990_000)
        self.assertEqual(crypto_pay.format_amount(12_503_400), "12.5034")
        self.assertEqual(crypto_pay.format_amount(12_500_100), "12.5001")

    def test_a_free_order_has_nothing_to_pay(self):
        order = self.order(0)
        with self.assertRaises(crypto_pay.CryptoUnavailable):
            crypto_pay.create_payment(self.db, order)


class ExpiryTest(CryptoBase):

    def test_an_overdue_payment_expires_and_closes_its_order(self):
        order, payment = self.payment()
        later = int(payment["expires_at"]) + crypto_pay.EXPIRY_GRACE_SECONDS + 1

        result = crypto_pay.check_pending(self.db, now=later)

        self.assertEqual([int(p["id"]) for p in result.expired], [int(payment["id"])])
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "expired")
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "expired")

    def test_invoice_lifetime_comes_from_the_config(self):
        self.settings.update(expiry_minutes=45)
        now = 1_000_000
        _, payment = self.payment(now=now)
        self.assertEqual(int(payment["expires_at"]), now + 45 * 60)

    def test_a_payment_made_in_time_but_seen_late_still_counts(self):
        _, payment = self.payment()
        expires = int(payment["expires_at"])
        self.http.return_value = grid_reply(
            ("late", ADDRESS, int(payment["amount_micro"]), expires - 5))

        result = crypto_pay.check_pending(self.db, now=expires + 60)   # inside the grace

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(result.expired, [])

    def test_a_transfer_after_expiry_never_matches(self):
        _, payment = self.payment()
        expires = int(payment["expires_at"])
        self.http.return_value = grid_reply(
            ("toolate", ADDRESS, int(payment["amount_micro"]), expires + 10))

        result = crypto_pay.check_pending(
            self.db, now=expires + crypto_pay.EXPIRY_GRACE_SECONDS + 1)

        self.assertEqual(result.matched, [])
        self.assertEqual(len(result.expired), 1)

    def test_an_expired_invoice_is_replaced_by_a_fresh_one(self):
        order, payment = self.payment(now=1000)
        fresh = crypto_pay.create_payment(self.db, self.db.get_order(int(order["id"])),
                                          now=1000 + 31 * 60)
        self.assertNotEqual(int(fresh["id"]), int(payment["id"]))
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "expired")

    def test_cancelling_the_order_stops_matching(self):
        order, payment = self.payment()
        crypto_pay.cancel_for_order(self.db, int(order["id"]))
        self.http.return_value = grid_reply(
            ("tx", ADDRESS, int(payment["amount_micro"]), int(time.time())))
        self.assertEqual(crypto_pay.check_pending(self.db).matched, [])
        self.http.assert_not_called()


class DisabledConfigTest(CryptoBase):

    def test_each_misconfiguration_has_its_own_reason(self):
        self.assertIsNone(crypto_pay.unavailable_reason())
        for override, reason in (({"enabled": False}, "disabled"),
                                 ({"address": ""}, "no_address"),
                                 ({"network": "solana"}, "bad_network"),
                                 ({"address": ADDRESS[:-1] + "1"}, "bad_address"),
                                 ({"address": "0x" + "ab" * 20}, "bad_address")):
            with self.subTest(reason=reason):
                self.settings = settings(**override)
                self.assertEqual(crypto_pay.unavailable_reason(), reason)
                self.assertFalse(crypto_pay.available())

    def test_a_disabled_config_refuses_invoices_and_hides_the_buttons(self):
        from licensing.telegram import keyboards as kb
        self.settings = settings(enabled=False)
        with self.assertRaises(crypto_pay.CryptoUnavailable):
            crypto_pay.create_payment(self.db, self.order())
        self.assertEqual(_callbacks(kb.invoice_actions()), ["buy:confirm", "buy:custom", "buy:panels"])
        self.assertNotIn("buy:crypto:7", _callbacks(kb.payment_actions(7)))

        self.settings = settings(address="")
        self.assertNotIn("buy:crypto", _callbacks(kb.invoice_actions()))

    def test_an_enabled_config_adds_the_usdt_buttons(self):
        from licensing.telegram import keyboards as kb
        invoice = kb.invoice_actions()
        self.assertIn("buy:crypto", _callbacks(invoice))
        self.assertIn("USDT (TRC20)", _labels(invoice)[1])
        self.assertIn("buy:confirm", _callbacks(invoice))     # card flow is untouched
        self.assertIn("buy:crypto:7", _callbacks(kb.payment_actions(7)))
        self.assertIn("buy:cchk:7", _callbacks(kb.crypto_actions(7)))

    def test_crypto_only_shop_does_not_need_a_card(self):
        with mock.patch.object(config, "_cache", {"sales_bot_token": "1:x", "admin_ids": [1],
                                                  "card_number": ""}):
            self.assertEqual(config.missing_required(), [])
            self.settings = settings(enabled=False)
            self.assertEqual(len(config.missing_required()), 1)

    def test_the_card_button_can_be_dropped_when_there_is_no_card(self):
        from licensing.telegram import keyboards as kb
        self.assertEqual(_callbacks(kb.invoice_actions(card=False))[0], "buy:crypto")


def _callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class ConfigTest(unittest.TestCase):

    def test_defaults_are_off_and_complete(self):
        with mock.patch.object(config, "_cache", {}), mock.patch.dict(os.environ, {}, clear=False):
            for name in ("LICENSING_CRYPTO_ADDRESS", "LICENSING_TRONGRID_API_KEY"):
                os.environ.pop(name, None)
            self.assertEqual(config.crypto_settings(), {
                "enabled": False, "network": "trc20", "address": "", "trongrid_api_key": "",
                "explorer_api_key": "", "expiry_minutes": 30, "min_confirmations": 1})

    def test_a_partial_section_is_merged_and_bad_values_fall_back(self):
        section = {"enabled": "true", "address": "  Tabc ", "expiry_minutes": "abc",
                   "min_confirmations": -4, "network": "TRC20", "unknown": 1}
        with mock.patch.object(config, "_cache", {"crypto": section}):
            merged = config.crypto_settings()
            self.assertIs(merged["enabled"], True)
            self.assertEqual(merged["address"], "Tabc")
            self.assertEqual(merged["expiry_minutes"], 30)
            self.assertEqual(merged["min_confirmations"], 0)
            self.assertEqual(merged["network"], "trc20")
            self.assertNotIn("unknown", merged)
            self.assertEqual(config.get("crypto.address"), "  Tabc ")
            self.assertEqual(config.get("crypto.nothing", "d"), "d")

    def test_environment_variables_override_the_secrets(self):
        env = {"LICENSING_CRYPTO_ADDRESS": ADDRESS, "LICENSING_TRONGRID_API_KEY": "envkey"}
        with mock.patch.object(config, "_cache", {"crypto": {"address": "other"}}), \
                mock.patch.dict(os.environ, env):
            merged = config.crypto_settings()
            self.assertEqual((merged["address"], merged["trongrid_api_key"]), (ADDRESS, "envkey"))

    def test_the_init_template_carries_the_crypto_section(self):
        self.assertIn("crypto", config._DEFAULTS)
        self.assertIs(config._DEFAULTS["crypto"]["enabled"], False)


class MigrationTest(unittest.TestCase):

    def test_an_old_database_gets_the_table_without_losing_orders(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "old.sqlite3")
            old = db_module.Database(path)
            order = old.create_order(user_id=1, months=1, users=1, bots=1, features=[],
                                     amount_usd=5)
            old._execute("DROP TABLE crypto_payments")
            old._execute("UPDATE schema_info SET version = 2")
            old.close()

            migrated = db_module.Database(path)
            self.assertEqual(migrated.pending_crypto_payments(), [])
            self.assertEqual(migrated.get_order(int(order["id"]))["amount_usd"], 5)
            self.assertEqual(migrated.query_one("SELECT version FROM schema_info")[0],
                             db_module.SCHEMA_VERSION)
            migrated.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# the Telegram layer
# ---------------------------------------------------------------------------

def make_application(db):
    application = mock.Mock()
    application.bot_data = {"db": db, "supervisor": None}
    application.bot.send_message = mock.AsyncMock()
    return application


def sent(application):
    """[(chat_id, text)] of everything the bot sent."""
    return [(c.args[0], c.args[1]) for c in application.bot.send_message.call_args_list]


class TelegramFlowTest(CryptoBase):

    def setUp(self):
        super().setUp()
        mock.patch("licensing.config.admin_ids", return_value=[9001]).start()
        self.application = make_application(self.db)

    def settle(self, usd=12.5):
        """An order with an open invoice that a matching transfer is about to pay."""
        order, payment = self.payment(usd)
        self.http.return_value = grid_reply(
            ("txabcdef123456", ADDRESS, int(payment["amount_micro"]), int(time.time())))
        return order, payment

    def test_a_match_issues_the_licence_and_tells_customer_and_admins(self):
        from licensing.telegram.sales import crypto_payment as cp
        order, payment = self.settle()

        result = asyncio.run(cp.crypto_check_pending(self.application))

        self.assertEqual(len(result.matched), 1)
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "approved")
        licences = self.db.licenses_by_user(555)
        self.assertEqual(len(licences), 1)
        messages = sent(self.application)
        self.assertEqual([chat for chat, _ in messages], [555, 555, 9001])
        self.assertIn(licences[0]["key"], messages[1][1])
        self.assertIn(licences[0]["key"], messages[2][1])
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "paid")

    def test_the_automatic_path_is_the_admin_approval_path(self):
        from licensing.telegram.sales import approval
        from licensing.telegram.sales import crypto_payment as cp
        self.assertIs(cp.issue_order_license, approval.issue_order_license)

        order, _ = self.settle()
        with mock.patch.object(cp, "issue_order_license",
                               new=mock.AsyncMock(return_value=("ok", {"key": "TT-X"}))) as issue:
            asyncio.run(cp.crypto_check_pending(self.application))
        issue.assert_awaited_once_with(self.application, int(order["id"]), None)

    def test_running_the_check_twice_never_approves_twice(self):
        from licensing.telegram.sales import crypto_payment as cp
        self.settle()
        asyncio.run(cp.crypto_check_pending(self.application))
        asyncio.run(cp.crypto_check_pending(self.application))
        self.assertEqual(len(self.db.licenses_by_user(555)), 1)

    def test_a_failed_approval_keeps_the_payment_and_alerts_the_admins(self):
        from licensing.telegram.sales import crypto_payment as cp
        _, payment = self.settle()
        with mock.patch.object(cp, "issue_order_license",
                               new=mock.AsyncMock(side_effect=RuntimeError("boom"))):
            asyncio.run(cp.crypto_check_pending(self.application))

        row = self.db.get_crypto_payment(int(payment["id"]))
        self.assertEqual((row["status"], row["tx_hash"]), ("approval_failed", "txabcdef123456"))
        admin_text = sent(self.application)[-1]
        self.assertEqual(admin_text[0], 9001)
        self.assertNotIn("boom", admin_text[1])

    def test_an_expired_invoice_tells_the_customer(self):
        from licensing.telegram.sales import crypto_payment as cp
        _, payment = self.payment()
        self.db._execute("UPDATE crypto_payments SET expires_at = ? WHERE id = ?",
                         (int(time.time()) - 1000, int(payment["id"])))

        asyncio.run(cp.crypto_check_pending(self.application))

        self.assertEqual([chat for chat, _ in sent(self.application)], [555])
        self.assertIn(str(int(payment["order_id"])), sent(self.application)[0][1])

    def test_the_customer_is_told_in_their_own_language(self):
        from licensing.telegram.sales import crypto_payment as cp
        self.db.upsert_user(555, "u", "U")
        self.db.set_user_lang(555, "fa")
        self.settle()
        asyncio.run(cp.crypto_check_pending(self.application))
        customer_text = sent(self.application)[0][1]
        self.assertIn("دریافت شد", customer_text)

    def test_the_poll_loop_only_hits_the_network_while_something_is_pending(self):
        from licensing.telegram.sales import background
        self.application.bot_data["db"] = self.db
        calls = []

        async def fake_check(application):
            calls.append(1)

        async def run(pending):
            sleeps = []

            async def fake_sleep(seconds):
                sleeps.append(seconds)
                if len(sleeps) > 2:
                    raise asyncio.CancelledError
            with mock.patch.object(background.asyncio, "sleep", fake_sleep), \
                    mock.patch.object(background, "crypto_check_pending", fake_check):
                if pending:
                    self.payment()
                await background._crypto_poll_loop(self.application)
            return sleeps

        sleeps = asyncio.run(run(pending=False))
        self.assertEqual((calls, sleeps[0]), ([], crypto_pay.POLL_SECONDS))
        asyncio.run(run(pending=True))
        self.assertEqual(len(calls), 2)

    def test_the_loop_is_registered_with_the_application(self):
        import inspect
        from licensing.telegram.sales import app
        self.assertIn("_crypto_poll_loop(app)", inspect.getsource(app.build_application))


class InvoiceScreenTest(CryptoBase):

    def setUp(self):
        super().setUp()
        from licensing.telegram.sales import crypto_payment as cp
        from licensing.telegram.sales import purchase
        self.cp, self.purchase = cp, purchase
        self.sent = mock.AsyncMock()
        mock.patch.object(cp, "_send", self.sent).start()
        mock.patch.object(purchase, "_send", self.sent).start()
        self.application = make_application(self.db)
        self.context = mock.Mock()
        self.context.application = self.application
        self.context.user_data = {"cfg": {"months": 1, "bots": 1, "features": [],
                                          "panel_code": None, "kind": "new",
                                          "license_id": None}}
        self.update = mock.Mock()
        self.update.effective_user.id = 555
        self.update.effective_user.username = "u"
        self.update.effective_user.first_name = "U"
        self.update.effective_user.language_code = "en"
        self.update.callback_query = None

    def screen(self):
        return self.sent.call_args[0][1], self.sent.call_args[0][2]

    def test_pay_with_usdt_from_the_invoice_shows_amount_address_expiry_and_check_button(self):
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))

        order = self.db.orders_by_user(555)[0]
        payment = self.db.crypto_payment_for_order(int(order["id"]))
        text, markup = self.screen()
        self.assertEqual(order["status"], "awaiting_crypto")
        self.assertIn(f"<code>{crypto_pay.format_amount(payment['amount_micro'])}</code>", text)
        self.assertIn(f"<code>{ADDRESS}</code>", text)
        self.assertIn("30 min", text)
        self.assertEqual(_callbacks(markup)[0], f"buy:cchk:{order['id']}")
        self.assertNotEqual(self.context.user_data.get("awaiting"), "receipt")

    def test_switching_a_card_order_to_usdt_keeps_the_same_order(self):
        async def go():
            await self.purchase.create_order_and_ask_payment(self.update, self.context)
        with mock.patch("licensing.config.payment_info", return_value={"card_number": "6037"}):
            asyncio.run(go())
        order = self.db.orders_by_user(555)[0]
        self.assertEqual(order["status"], "awaiting_receipt")
        self.assertEqual(self.context.user_data["awaiting"], "receipt")

        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context, int(order["id"])))

        self.assertEqual(len(self.db.orders_by_user(555)), 1)
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "awaiting_crypto")
        self.assertNotIn("awaiting", self.context.user_data)

    def test_someone_elses_order_cannot_be_switched(self):
        order = self.order(user_id=777)
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context, int(order["id"])))
        self.assertIsNone(self.db.crypto_payment_for_order(int(order["id"])))
        self.assertIn("no longer", self.screen()[0])

    def test_card_flow_is_unchanged_when_crypto_is_off(self):
        self.settings = settings(enabled=False)
        with mock.patch("licensing.config.payment_info", return_value={"card_number": "6037"}):
            asyncio.run(self.purchase.create_order_and_ask_payment(self.update, self.context))
        order = self.db.orders_by_user(555)[0]
        self.assertEqual(order["status"], "awaiting_receipt")
        self.assertEqual(self.context.user_data["awaiting"], "receipt")
        self.assertNotIn("buy:crypto", str(_callbacks(self.screen()[1])))
        self.assertIsNone(self.db.crypto_payment_for_order(int(order["id"])))

    def test_pressing_pay_with_usdt_while_disabled_creates_no_order(self):
        self.settings = settings(enabled=False)
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        self.assertEqual(self.db.orders_by_user(555), [])

    def test_a_busy_price_point_leaves_no_orphan_order(self):
        with mock.patch.object(crypto_pay, "OFFSET_MAX_STEPS", 0):
            asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        self.assertEqual([o["status"] for o in self.db.orders_by_user(555)], ["cancelled"])

    def test_check_now_reports_no_payment_yet_and_then_rate_limits(self):
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        order = self.db.orders_by_user(555)[0]

        asyncio.run(self.cp.crypto_check_now(self.update, self.context, int(order["id"])))
        self.assertIn("no matching payment yet", self.screen()[0])
        self.assertEqual(self.http.call_count, 1)

        asyncio.run(self.cp.crypto_check_now(self.update, self.context, int(order["id"])))
        self.assertIn("wait a few seconds", self.screen()[0])
        self.assertEqual(self.http.call_count, 1)

    def test_check_now_with_a_paid_transfer_approves_immediately(self):
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        order = self.db.orders_by_user(555)[0]
        payment = self.db.crypto_payment_for_order(int(order["id"]))
        self.http.return_value = grid_reply(
            ("tx", ADDRESS, int(payment["amount_micro"]), int(time.time())))

        asyncio.run(self.cp.crypto_check_now(self.update, self.context, int(order["id"])))

        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "approved")
        self.assertIn("Payment detected", self.screen()[0])

    def test_a_network_failure_shows_a_generic_message_not_the_error(self):
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        order = self.db.orders_by_user(555)[0]
        self.http.side_effect = crypto_pay.CryptoNetworkError("HTTP 500 secret-detail")
        asyncio.run(self.cp.crypto_check_now(self.update, self.context, int(order["id"])))
        text = self.screen()[0]
        self.assertIn("did not answer", text)
        self.assertNotIn("secret-detail", text)

    def test_cancelling_the_order_closes_the_invoice(self):
        asyncio.run(self.cp.crypto_invoice_start(self.update, self.context))
        order = self.db.orders_by_user(555)[0]
        asyncio.run(self.purchase.cancel_order(self.update, self.context, int(order["id"])))
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "cancelled")
        self.assertEqual(self.db.crypto_payment_for_order(int(order["id"]))["status"], "cancelled")


class AdminViewAndManualApprovalTest(CryptoBase):

    def setUp(self):
        super().setUp()
        from licensing.telegram.sales import approval
        from licensing.telegram.sales import crypto_payment as cp
        self.approval, self.cp = approval, cp
        self.sent = mock.AsyncMock()
        mock.patch.object(cp, "_send", self.sent).start()
        mock.patch.object(approval, "_send", self.sent).start()
        mock.patch.object(cp, "_is_admin", return_value=True).start()
        self.application = make_application(self.db)
        self.context = mock.Mock()
        self.context.application = self.application
        self.update = mock.Mock()
        self.update.effective_user.id = 9001

    def test_the_admin_sees_pending_and_received_payments(self):
        order, pending = self.payment(10, user_id=1)
        paid_order, paid = self.payment(20, user_id=2)
        self.db.claim_crypto_payment(int(paid["id"]), "f" * 64)

        asyncio.run(self.cp.admin_crypto_view(self.update, self.context))

        text, markup = self.sent.call_args[0][1], self.sent.call_args[0][2]
        self.assertIn(crypto_pay.format_amount(pending["amount_micro"]), text)
        self.assertIn(crypto_pay.format_amount(paid["amount_micro"]), text)
        self.assertIn("tronscan.org/#/transaction/" + "f" * 64, text)
        self.assertIn(f"adm:show:{order['id']}", _callbacks(markup))
        self.assertIn("adm:cryptock", _callbacks(markup))

    def test_the_admin_view_explains_why_crypto_is_off(self):
        self.settings = settings(address="")
        asyncio.run(self.cp.admin_crypto_view(self.update, self.context))
        self.assertIn("crypto.address is empty", self.sent.call_args[0][1])

    def test_non_admins_are_refused(self):
        with mock.patch.object(self.cp, "_is_admin", return_value=False):
            asyncio.run(self.cp.admin_crypto_view(self.update, self.context))
        self.assertNotIn("USDT payments", self.sent.call_args[0][1])
        self.assertEqual(self.db.pending_crypto_payments(), [])

    def test_admin_check_now_runs_a_round(self):
        _, payment = self.payment()
        self.http.return_value = grid_reply(
            ("tx", ADDRESS, int(payment["amount_micro"]), int(time.time())))
        with mock.patch("licensing.config.admin_ids", return_value=[9001]):
            asyncio.run(self.cp.admin_crypto_view(self.update, self.context, check=True))
        self.assertIn("1 matched", self.sent.call_args[0][1])

    def test_a_manual_approval_closes_the_open_invoice(self):
        order, payment = self.payment()
        asyncio.run(self.approval.approve_order(self.update, self.context, int(order["id"])))
        self.assertEqual(self.db.get_order(int(order["id"]))["status"], "approved")
        self.assertEqual(self.db.get_crypto_payment(int(payment["id"]))["status"], "manual")
        # ...so a late transfer cannot approve it a second time
        self.http.return_value = grid_reply(
            ("late", ADDRESS, int(payment["amount_micro"]), int(time.time())))
        self.assertEqual(crypto_pay.check_pending(self.db).matched, [])

    def test_manual_approval_still_reports_unknown_and_repeat_orders(self):
        asyncio.run(self.approval.approve_order(self.update, self.context, 4242))
        self.assertEqual(self.sent.await_count, 1)
        order = self.order()
        asyncio.run(self.approval.approve_order(self.update, self.context, int(order["id"])))
        asyncio.run(self.approval.approve_order(self.update, self.context, int(order["id"])))
        self.assertEqual(len(self.db.licenses_by_user(555)), 1)


class NewTextsTest(unittest.TestCase):

    def test_every_new_key_exists_in_both_languages_and_formats(self):
        import re
        import json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tables = {}
        for lang in ("en", "fa"):
            with open(os.path.join(root, "licensing", "locales", lang + ".json"),
                      encoding="utf-8") as f:
                tables[lang] = json.load(f)
        names = [k for k in tables["en"] if "crypto" in k]
        self.assertGreaterEqual(len(names), 30)
        for name in names:
            self.assertIn(name, tables["fa"])
            fields = lambda t: sorted(re.findall(r"\{(\w+)\}", t if isinstance(t, str) else "".join(t)))
            self.assertEqual(fields(tables["en"][name]), fields(tables["fa"][name]), name)


if __name__ == "__main__":
    unittest.main()
