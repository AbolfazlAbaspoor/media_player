"""
پرداخت با تتر (USDT): تماشای یه آدرس عمومی، بدون هیچ کلید خصوصی.

## ایده

ربات فقط *می‌خونه*: آدرس دریافتِ تو رو از یه API عمومی (TronGrid برای
ترون، Etherscan برای BSC) بازخونی می‌کنه و می‌بینه تراکنشی با مبلغِ
مورد انتظار رسیده یا نه. هیچ‌چیزی امضا یا ارسال نمی‌شه، پس لو رفتنِ
کانفیگ ربات هیچ‌وقت به پولِ تو دسترسی نمی‌ده.

## چرا مبلغِ یکتا

روی بلاک‌چین فرستنده «شماره‌ی سفارش» نمی‌نویسه. تنها چیزی که از هر
تراکنش داریم: مقصد، مبلغ، زمان و هشِ تراکنشه. پس هر سفارش یه مبلغِ
یکتا می‌گیره (قیمت + ۰٫۰۰۰۱ تا ۰٫۰۹۹۹ تتر) که بین پرداخت‌های در
انتظار تکراری نیست، و تطبیق روی سه چیز انجام می‌شه:

  ۱. آدرس مقصد و مبلغِ *دقیقاً برابر*
  ۲. زمانِ تراکنش داخل پنجره‌ی [ساخت فاکتور، انقضا]
  ۳. هشِ تراکنش قبلاً برای پرداخت دیگه‌ای ثبت نشده باشه (ایندکس یکتای
     دیتابیس، نه فقط چک توی کد -- دو حلقه‌ی هم‌زمان هم نمی‌تونن یه
     تراکنش رو دو بار خرج کنن)

مبلغِ کمتر یا بیشتر *عمداً* خودکار تأیید نمی‌شه: ادمین از پنل می‌بینه و
دستی تصمیم می‌گیره.

## شبکه‌ها

هر شبکه یه کلاس کوچیکه با یه متد `fetch_incoming`. اضافه‌کردن شبکه‌ی
جدید یعنی یه کلاس و یه خط توی NETWORKS.
"""

import hashlib
import json
import random
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

from core import logging_setup
from licensing import config

MICRO = 1_000_000

# آفست مبلغ: ۰٫۰۰۰۱ تا ۰٫۰۹۹۹ تتر، در گام‌های ۰٫۰۰۰۱ (۹۹۹ مبلغ ممکن برای هر قیمت).
OFFSET_STEP_MICRO = 100
OFFSET_MAX_STEPS = 999

# بعد از انقضا هنوز این‌قدر صبر می‌کنیم تا تراکنشِ لحظه‌ی آخر که دیرتر از
# API دیده می‌شه جا نمونه؛ تراکنش‌هایی که *زمانشون* بعد از انقضاست هیچ‌وقت
# تطبیق نمی‌خورن.
EXPIRY_GRACE_SECONDS = 120

# فاصله‌ی بررسی‌های پس‌زمینه (فقط وقتی پرداختی در انتظار باشه).
POLL_SECONDS = 30

FETCH_LIMIT = 200
REQUEST_TIMEOUT = 15

TRONGRID_BASE = "https://api.trongrid.io"
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

ETHERSCAN_V2_BASE = "https://api.etherscan.io/v2/api"
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class CryptoError(Exception):
    pass


class CryptoUnavailable(CryptoError):
    """خاموشه، آدرس نداره، یا آدرسش معتبر نیست."""


class CryptoBusy(CryptoError):
    """همه‌ی مبلغ‌های یکتای این قیمت الان درگیرن."""


class CryptoNetworkError(CryptoError):
    """API شبکه جواب نداد یا جواب نامعتبر بود. متنش هیچ‌وقت راز (کلید) نداره."""


class Transfer(NamedTuple):
    tx_hash: str
    to_address: str
    amount_micro: int
    timestamp: int  # ثانیه


class CheckResult(NamedTuple):
    matched: list   # [(ردیف پرداخت، Transfer)]
    expired: list   # ردیف‌های پرداختِ تازه منقضی‌شده
    failed: bool    # حداقل یه شبکه جواب نداد


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _http_json(url, headers=None):
    """
    GET و JSON. مثل مسیر کلادفلر: اول مستقیم، بعد با پروکسیِ ربات فروش
    (proxy_url). تستا همین تابع رو mock می‌کنن.
    """
    from core import proxy_state
    request = urllib.request.Request(
        url, headers={"User-Agent": "ttbot-licensing/1.0", **(headers or {})})
    try:
        with proxy_state.open_direct_then_proxy(
                request, REQUEST_TIMEOUT, config.proxy_url()) as response:
            body = response.read()
    except urllib.error.HTTPError as e:
        raise CryptoNetworkError(f"HTTP {e.code}") from e
    except Exception as e:
        raise CryptoNetworkError(type(e).__name__) from e
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError as e:
        raise CryptoNetworkError("invalid JSON") from e


def _to_micro(value, decimals):
    """
    مقدارِ خامِ توکن -> میکرو‌تتر. اگه رقم‌های اضافه‌ای داشته باشه که توی
    شش رقم جا نمی‌شه None می‌ده (مبلغِ «دقیق» نیست، پس هیچ‌وقت تطبیق نمی‌خوره).
    """
    value, decimals = int(value), int(decimals)
    if decimals <= 6:
        return value * 10 ** (6 - decimals)
    step = 10 ** (decimals - 6)
    return value // step if value % step == 0 else None


# ---------------------------------------------------------------------------
# شبکه‌ها
# ---------------------------------------------------------------------------

class _Network:
    code = ""
    label = ""

    def valid_address(self, address):
        raise NotImplementedError

    def same_address(self, a, b):
        return a == b

    def fetch_incoming(self, address, settings, since_ts):
        """تراکنش‌های USDT ورودی به address از since_ts (ثانیه) به بعد."""
        raise NotImplementedError

    def tx_url(self, tx_hash):
        return ""


class _TronNetwork(_Network):
    code = "trc20"
    label = "USDT (TRC20)"

    def valid_address(self, address):
        """base58check: پیشوند ۰x41 و چک‌سامِ ۴ بایتی -- غلط تایپی رو همون اول می‌گیره."""
        if len(address) != 34 or any(c not in _B58_ALPHABET for c in address):
            return False
        number = 0
        for char in address:
            number = number * 58 + _B58_ALPHABET.index(char)
        try:
            raw = number.to_bytes(25, "big")
        except OverflowError:
            return False
        checksum = hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4]
        return raw[0] == 0x41 and raw[21:] == checksum

    def fetch_incoming(self, address, settings, since_ts):
        query = {
            "only_to": "true",
            "contract_address": USDT_TRC20_CONTRACT,
            "limit": FETCH_LIMIT,
            "order_by": "block_timestamp,desc",
            "min_timestamp": int(since_ts) * 1000,
        }
        # در ترون «تأیید» یعنی قطعی‌شدنِ بلاک (solidified)؛ تعدادش قابل
        # تنظیم نیست، فقط «قطعی یا نه».
        if settings["min_confirmations"] >= 1:
            query["only_confirmed"] = "true"
        url = (f"{TRONGRID_BASE}/v1/accounts/{address}/transactions/trc20?"
               + urllib.parse.urlencode(query))
        headers = {}
        if settings["trongrid_api_key"]:
            headers["TRON-PRO-API-KEY"] = settings["trongrid_api_key"]
        data = _http_json(url, headers)
        if not isinstance(data, dict) or data.get("success") is False:
            raise CryptoNetworkError("TronGrid rejected the request")

        transfers = []
        for item in data.get("data") or []:
            try:
                info = item.get("token_info") or {}
                if info.get("address") != USDT_TRC20_CONTRACT:
                    continue
                amount = _to_micro(item["value"], info.get("decimals", 6))
                if amount is None:
                    continue
                transfers.append(Transfer(
                    str(item["transaction_id"]), str(item["to"]), amount,
                    int(item["block_timestamp"]) // 1000))
            except (KeyError, TypeError, ValueError):
                continue
        return transfers

    def tx_url(self, tx_hash):
        return f"https://tronscan.org/#/transaction/{tx_hash}"


class _BscNetwork(_Network):
    code = "bep20"
    label = "USDT (BEP20)"

    def valid_address(self, address):
        return bool(_EVM_ADDRESS.match(address))

    def same_address(self, a, b):
        return a.lower() == b.lower()

    def fetch_incoming(self, address, settings, since_ts):
        query = {
            "chainid": 56, "module": "account", "action": "tokentx",
            "contractaddress": USDT_BEP20_CONTRACT, "address": address,
            "page": 1, "offset": FETCH_LIMIT, "sort": "desc",
            "apikey": settings["explorer_api_key"],
        }
        data = _http_json(ETHERSCAN_V2_BASE + "?" + urllib.parse.urlencode(query))
        if not isinstance(data, dict):
            raise CryptoNetworkError("explorer returned an unexpected reply")
        result = data.get("result")
        if not isinstance(result, list):
            # status 0 با پیام «No transactions found» خالیه، نه خطا؛
            # هر چیز دیگه (کلید غلط، سقف درخواست) خطای واقعیه.
            if "no transactions" in str(data.get("message", "")).lower():
                return []
            raise CryptoNetworkError("explorer rejected the request")

        transfers = []
        for item in result:
            try:
                if str(item.get("contractAddress", "")).lower() != USDT_BEP20_CONTRACT.lower():
                    continue
                timestamp = int(item["timeStamp"])
                if timestamp < since_ts:
                    continue
                if int(item.get("confirmations", 0)) < settings["min_confirmations"]:
                    continue
                amount = _to_micro(item["value"], item.get("tokenDecimal", 18))
                if amount is None:
                    continue
                transfers.append(Transfer(
                    str(item["hash"]), str(item["to"]), amount, timestamp))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
        return transfers

    def tx_url(self, tx_hash):
        return f"https://bscscan.com/tx/{tx_hash}"


NETWORKS = {net.code: net for net in (_TronNetwork(), _BscNetwork())}


# ---------------------------------------------------------------------------
# در دسترس بودن
# ---------------------------------------------------------------------------

def unavailable_reason(settings=None):
    """None اگه همه‌چیز آماده‌ست، وگرنه یه کد کوتاه: disabled/no_address/bad_network/bad_address."""
    settings = settings or config.crypto_settings()
    if not settings["enabled"]:
        return "disabled"
    if not settings["address"]:
        return "no_address"
    network = NETWORKS.get(settings["network"])
    if network is None:
        return "bad_network"
    if not network.valid_address(settings["address"]):
        return "bad_address"
    return None


def available(settings=None):
    """دکمه‌ی پرداخت با تتر فقط وقتی دیده می‌شه که این True باشه."""
    return unavailable_reason(settings) is None


# ---------------------------------------------------------------------------
# مبلغ
# ---------------------------------------------------------------------------

def usd_to_micro(amount_usd):
    return int((Decimal(str(amount_usd)) * MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_amount(micro):
    """مبلغ برای نمایش: حداقل ۴ رقم اعشار (آفست همیشه مضرب ۰٫۰۰۰۱ه)، بدون صفرِ اضافه‌ی بعدش."""
    text = f"{Decimal(int(micro)) / MICRO:.6f}"
    whole, fraction = text.split(".")
    return f"{whole}.{fraction.rstrip('0').ljust(4, '0')}"


# ---------------------------------------------------------------------------
# ساخت، لغو و تطبیق
# ---------------------------------------------------------------------------

def create_payment(db, order, now=None, rng=random):
    """
    فاکتور تتری برای یه سفارش. اگه همین سفارش فاکتورِ معتبرِ باز داره همونو
    برمی‌گردونه (دوبار زدن دکمه مبلغ تازه نمی‌سازه).
    """
    settings = config.crypto_settings()
    if unavailable_reason(settings) is not None or float(order["amount_usd"]) <= 0:
        raise CryptoUnavailable("crypto payment is not available for this order")
    now = int(now if now is not None else time.time())
    order_id = int(order["id"])

    existing = db.crypto_payment_for_order(order_id)
    if existing is not None and existing["status"] == "pending":
        if int(existing["expires_at"]) > now:
            return existing
        db.set_crypto_payment_status(int(existing["id"]), "expired")

    address = settings["address"]
    taken = {int(row["amount_micro"]) for row in db.pending_crypto_payments()
             if row["network"] == settings["network"] and row["address"] == address}
    base = usd_to_micro(order["amount_usd"])
    free = [base + step * OFFSET_STEP_MICRO for step in range(1, OFFSET_MAX_STEPS + 1)
            if base + step * OFFSET_STEP_MICRO not in taken]

    expires_at = now + settings["expiry_minutes"] * 60
    while free:
        amount = rng.choice(free)
        free.remove(amount)
        try:
            payment = db.create_crypto_payment(
                order_id, int(order["user_id"]), settings["network"], address, amount, expires_at)
        except sqlite3.IntegrityError:
            # بین خوندنِ taken و نوشتن، یه درخواستِ هم‌زمان همین مبلغ رو گرفت.
            continue
        db.update_order(order_id, status="awaiting_crypto")
        db.log_event("crypto_invoice", user_id=int(order["user_id"]), order_id=order_id,
                     detail={"network": settings["network"], "amount_micro": amount,
                             "expires_at": expires_at})
        return payment
    raise CryptoBusy("no free unique amount for this price")


def cancel_for_order(db, order_id):
    """سفارش لغو شد: فاکتور تتریش دیگه تطبیق نمی‌خوره."""
    payment = db.crypto_payment_for_order(order_id)
    if payment is not None:
        db.set_crypto_payment_status(int(payment["id"]), "cancelled")


def close_for_order(db, order_id):
    """
    ادمین سفارش رو دستی تأیید کرد (مثلاً مبلغِ اشتباه): فاکتورِ باز بسته می‌شه
    تا بعداً با یه تراکنشِ دیررسیده دوباره تأیید نشه.
    """
    payment = db.crypto_payment_for_order(order_id)
    if payment is not None:
        db.set_crypto_payment_status(int(payment["id"]), "manual")


def _matches(payment, transfer, network):
    return (transfer.amount_micro == int(payment["amount_micro"])
            and network.same_address(transfer.to_address, payment["address"])
            and int(payment["created_at"]) <= transfer.timestamp <= int(payment["expires_at"]))


def _expire_overdue(db, now):
    expired = []
    for payment in db.pending_crypto_payments():
        if int(payment["expires_at"]) + EXPIRY_GRACE_SECONDS >= now:
            continue
        if not db.set_crypto_payment_status(int(payment["id"]), "expired"):
            continue
        order = db.get_order(int(payment["order_id"]))
        if order is not None and order["status"] == "awaiting_crypto":
            db.update_order(int(order["id"]), status="expired")
            db.log_event("order_expired", user_id=int(order["user_id"]),
                         order_id=int(order["id"]), detail={"method": "crypto"})
        expired.append(db.get_crypto_payment(int(payment["id"])))
    return expired


def check_pending(db, now=None):
    """
    همه‌ی پرداخت‌های تتریِ در انتظار رو با شبکه تطبیق می‌ده. همگامه (I/O)؛
    از توی ترد صداش بزن. خطای شبکه استثنا نمی‌ده (failed=True می‌شه)، چون
    حلقه‌ی پس‌زمینه باید دور بعدی دوباره امتحان کنه.

    منقضی‌کردن *بعد از* تطبیق انجام می‌شه تا پرداختِ لحظه‌ی آخر جا نمونه.
    """
    now = int(now if now is not None else time.time())
    matched, failed = [], False

    groups = {}
    for payment in db.pending_crypto_payments():
        groups.setdefault((payment["network"], payment["address"]), []).append(payment)

    settings = config.crypto_settings()
    for (code, address), payments in groups.items():
        network = NETWORKS.get(code)
        if network is None:
            continue
        since = min(int(p["created_at"]) for p in payments)
        try:
            transfers = network.fetch_incoming(address, settings, since)
        except CryptoNetworkError as e:
            logging_setup.log_debug(f"crypto poll failed ({code}): {e}")
            failed = True
            continue
        transfers.sort(key=lambda t: t.timestamp)
        for payment in payments:
            for transfer in transfers:
                if not _matches(payment, transfer, network):
                    continue
                if db.claim_crypto_payment(int(payment["id"]), transfer.tx_hash):
                    matched.append((db.get_crypto_payment(int(payment["id"])), transfer))
                    break

    return CheckResult(matched, _expire_overdue(db, now), failed)
