"""
دیتابیس پلتفرم لایسنس (SQLite).

## چرا SQLite

یه سرور، چند صد مشتری، و نوشتن‌های کم و کوتاه (ثبت سفارش، تأیید پرداخت).
SQLite با WAL این حجم رو راحت جواب می‌ده، بکاپش یه کپی فایله، و هیچ سرویس
جدایی لازم نداره که بتونه بیفته. اگه روزی لازم شد، مهاجرت به پستگرس با
همین لایه‌ی نازک کار سختی نیست.

## نکته‌ی هم‌زمانی

هر ترد کانکشن خودش رو می‌گیره (SQLite objectها بین تردها قابل اشتراک
نیستن) و `check_same_thread=False` استفاده *نمی‌شه*. WAL روشنه تا خوندن و
نوشتن هم‌زمان قفل نکنن، و busy_timeout بالاست تا نوشتن‌های موازیِ کوتاه
به‌جای ارور، صبر کنن.

## پسورد تیم‌تاک

پسورد لاگین ربات به سرور تیم‌تاک باید *قابل استفاده* باشه (ربات باهاش
لاگین می‌کنه)، پس نمی‌شه هش کرد. توی همین دیتابیس ذخیره می‌شه و فایل
دیتابیس با chmod 600 ساخته می‌شه. این همون سطح امنیتیه که identity.json
از قبل داشت -- نه بیشتر، نه کمتر.
"""

import json
import os
import sqlite3
import threading
import time

from core.paths import get_base_dir
from licensing import i18n

DB_DIR = os.path.join(get_base_dir(), "data", "licensing")
DB_PATH = os.path.join(DB_DIR, "licensing.sqlite3")

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    telegram_id           INTEGER PRIMARY KEY,
    username              TEXT,
    first_name            TEXT,
    lang                  TEXT NOT NULL DEFAULT 'en',
    created_at            INTEGER NOT NULL,
    last_seen_at          INTEGER,
    blocked               INTEGER NOT NULL DEFAULT 0,
    personal_bot_token    TEXT,
    personal_bot_username TEXT,
    personal_bot_status   TEXT NOT NULL DEFAULT 'none',
    channel_left_at       INTEGER,
    channel_warned_at     INTEGER
);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'new',
    license_id      INTEGER,
    panel_code      TEXT,
    months          INTEGER NOT NULL,
    users           INTEGER NOT NULL,
    bots            INTEGER NOT NULL,
    features        TEXT NOT NULL DEFAULT '[]',
    amount_usd      REAL NOT NULL,
    amount_irr      INTEGER,
    usd_rate        INTEGER,
    status          TEXT NOT NULL,
    receipt_file_id TEXT,
    receipt_path    TEXT,
    receipt_at      INTEGER,
    check_verdict   TEXT,
    check_score     REAL,
    check_summary   TEXT,
    admin_note      TEXT,
    decided_by      INTEGER,
    decided_at      INTEGER,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS licenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,
    user_id         INTEGER NOT NULL,
    order_id        INTEGER,
    max_bots        INTEGER NOT NULL DEFAULT 1,
    max_users       INTEGER NOT NULL DEFAULT 1,
    features        TEXT NOT NULL DEFAULT '[]',
    starts_at       INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    grace_until     INTEGER,
    warned_stage    TEXT,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    deactivated_at  INTEGER,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_licenses_user ON licenses(user_id);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);
CREATE INDEX IF NOT EXISTS idx_licenses_expiry ON licenses(expires_at);

CREATE TABLE IF NOT EXISTS instances (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id          INTEGER NOT NULL,
    slug                TEXT NOT NULL UNIQUE,
    tt_host             TEXT NOT NULL,
    tt_port             INTEGER NOT NULL DEFAULT 10333,
    tt_nickname         TEXT,
    tt_username         TEXT,
    tt_password         TEXT,
    tt_channel_id       INTEGER NOT NULL DEFAULT 1,
    tt_channel_password TEXT,
    operators           TEXT NOT NULL DEFAULT '[]',
    audio_line          TEXT,
    group_name          TEXT,
    bot_name            TEXT,
    status              TEXT NOT NULL DEFAULT 'created',
    pid                 INTEGER,
    last_started_at     INTEGER,
    last_exit_code      INTEGER,
    created_at          INTEGER NOT NULL,
    updated_at          INTEGER NOT NULL,
    removed_at          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_instances_license ON instances(license_id);
CREATE INDEX IF NOT EXISTS idx_instances_status ON instances(status);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    order_id    INTEGER,
    message     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    admin_reply TEXT,
    created_at  INTEGER NOT NULL,
    closed_at   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

CREATE TABLE IF NOT EXISTS promo_codes (
    code            TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    value           REAL NOT NULL DEFAULT 0,
    features        TEXT NOT NULL DEFAULT '[]',
    max_bots        INTEGER NOT NULL DEFAULT 1,
    max_users       INTEGER NOT NULL DEFAULT 1,
    valid_from      INTEGER NOT NULL,
    valid_until     INTEGER NOT NULL,
    per_user_limit  INTEGER NOT NULL DEFAULT 1,
    per_user_period TEXT NOT NULL DEFAULT 'ever',
    total_limit     INTEGER NOT NULL DEFAULT 0,
    used_count      INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    note            TEXT,
    created_by      INTEGER,
    created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_promo_active ON promo_codes(active, valid_until);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    user_id     INTEGER NOT NULL,
    redeemed_at INTEGER NOT NULL,
    license_id  INTEGER,
    order_id    INTEGER,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_redemption_code_user ON promo_redemptions(code, user_id);
CREATE INDEX IF NOT EXISTS idx_redemption_user ON promo_redemptions(user_id);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    user_id    INTEGER,
    license_id INTEGER,
    order_id   INTEGER,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

-- پرداخت با تتر (licensing/crypto_pay.py). مبلغ به «میکرو» (یک‌میلیونیم
-- تتر) و عدد صحیح ذخیره می‌شه تا مقایسه‌ی مبلغ هیچ‌وقت خطای اعشار نداشته باشه.
-- جدول جدا از orders نگه داشته شده: دیتابیس‌های قدیمی فقط با اجرای همین
-- CREATE TABLE IF NOT EXISTS ارتقا می‌گیرن و ستون orders دست نمی‌خوره.
CREATE TABLE IF NOT EXISTS crypto_payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    network         TEXT NOT NULL,
    address         TEXT NOT NULL,
    amount_micro    INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    tx_hash         TEXT,
    created_at      INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    paid_at         INTEGER
);
CREATE INDEX IF NOT EXISTS idx_crypto_order ON crypto_payments(order_id);
CREATE INDEX IF NOT EXISTS idx_crypto_status ON crypto_payments(status);
-- یه تراکنش فقط یک‌بار می‌تونه پرداخت حساب بشه (ضدِ استفاده‌ی دوباره)...
CREATE UNIQUE INDEX IF NOT EXISTS uq_crypto_tx
    ON crypto_payments(network, tx_hash) WHERE tx_hash IS NOT NULL;
-- ...و دو پرداختِ در انتظار هیچ‌وقت مبلغ یکسان ندارن (تطبیق بر اساس مبلغه).
CREATE UNIQUE INDEX IF NOT EXISTS uq_crypto_pending_amount
    ON crypto_payments(network, address, amount_micro) WHERE status = 'pending';
"""


#: ستون‌هایی که بعد از ساختِ اولیه‌ی جدول users اضافه شدن.
_ADDED_USER_COLUMNS = {
    "channel_left_at": "INTEGER",
    "channel_warned_at": "INTEGER",
    # پیام همگانی (C1): کاربری که ربات رو بلاک کرده تا وقتی دوباره باهاش
    # حرف نزنه، از گیرنده‌های بعدی حذف می‌شه. upsert_user همین ستون رو
    # پاک می‌کنه، پس «دوباره حرف زدن» به‌صورت خودکار رفعش می‌کنه.
    "bot_blocked_at": "INTEGER",
}


def _ensure_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


class Database:
    def __init__(self, path=None):
        self.path = path or DB_PATH
        self._local = threading.local()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_schema()
        self._restrict_permissions()

    # ------------------------------------------------------------ کانکشن

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @property
    def conn(self):
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
        return connection

    def close(self):
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def _init_schema(self):
        with self.conn as conn:
            conn.executescript(_SCHEMA)
            # CREATE TABLE IF NOT EXISTS ستون‌های تازه رو به جدولِ از قبل
            # موجود اضافه نمی‌کنه، پس دیتابیس‌های قدیمی دستی ارتقا می‌گیرن.
            _ensure_columns(conn, "users", _ADDED_USER_COLUMNS)
            row = conn.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_info (version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row[0] or 0) < SCHEMA_VERSION:
                conn.execute("UPDATE schema_info SET version = ?", (SCHEMA_VERSION,))

    def _restrict_permissions(self):
        """
        فایل دیتابیس پسورد لاگین ربات‌ها رو داره؛ روی لینوکس فقط مالک باید
        بخونه. روی ویندوز chmod بی‌اثره و ACL کار خودِ سیستمه.
        """
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    # ------------------------------------------------------------ ابزار

    @staticmethod
    def _now():
        return int(time.time())

    def _execute(self, sql, params=()):
        with self.conn as conn:
            return conn.execute(sql, params)

    def query(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    # ---------------------------------------------------------- settings

    def get_setting(self, key, default=None):
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key, value):
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )

    def all_settings(self):
        return {row["key"]: row["value"] for row in self.query("SELECT key, value FROM settings")}

    # ------------------------------------------------------------- users

    def upsert_user(self, telegram_id, username=None, first_name=None):
        # زبان صریح نوشته می‌شه، نه با تکیه بر DEFAULT ستون: دیتابیس‌هایی
        # که قبل از انگلیسی‌شدنِ پیش‌فرض ساخته شدن هنوز DEFAULT 'fa' دارن
        # (CREATE TABLE IF NOT EXISTS جدول موجود رو عوض نمی‌کنه) و کاربر
        # جدیدشون فارسی می‌افتاد.
        # bot_blocked_at همیشه اینجا پاک می‌شه: این تابع دقیقاً همون‌جاییه
        # که «کاربر با ربات حرف زد» تشخیص داده می‌شه (هر آپدیت تلگرام اول
        # همینو صدا می‌زنه)، پس رفعِ نشونِ «بلاک‌کننده» هم دقیقاً همینجاست --
        # یه چک جدا لازم نیست و پیام همگانیِ بعدی خودکار دوباره می‌رسه.
        now = self._now()
        self._execute(
            "INSERT INTO users (telegram_id, username, first_name, lang, created_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET "
            "  username = COALESCE(excluded.username, users.username), "
            "  first_name = COALESCE(excluded.first_name, users.first_name), "
            "  last_seen_at = excluded.last_seen_at, "
            "  bot_blocked_at = NULL",
            (telegram_id, username, first_name, i18n.DEFAULT_LANGUAGE, now, now),
        )
        return self.get_user(telegram_id)

    def get_user(self, telegram_id):
        return self.query_one("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))

    def set_user_blocked(self, telegram_id, blocked):
        self._execute("UPDATE users SET blocked = ? WHERE telegram_id = ?",
                      (1 if blocked else 0, telegram_id))

    def set_user_lang(self, telegram_id, lang):
        self._execute("UPDATE users SET lang = ? WHERE telegram_id = ?", (lang, telegram_id))

    def set_personal_bot(self, telegram_id, token, username=None, status="pending"):
        self._execute(
            "UPDATE users SET personal_bot_token = ?, personal_bot_username = ?, "
            "personal_bot_status = ? WHERE telegram_id = ?",
            (token, username, status, telegram_id),
        )

    def personal_bots(self, status=None):
        if status:
            return self.query(
                "SELECT * FROM users WHERE personal_bot_token IS NOT NULL AND personal_bot_status = ?",
                (status,),
            )
        return self.query("SELECT * FROM users WHERE personal_bot_token IS NOT NULL")

    def mark_bot_blocked(self, telegram_id):
        """کاربر ربات رو بلاک کرده (Forbidden موقع فرستادن پیام) -- پیام‌های
        همگانیِ بعدی تا وقتی خودش دوباره حرف نزنه، نادیده‌ش می‌گیرن."""
        self._execute("UPDATE users SET bot_blocked_at = ? WHERE telegram_id = ?",
                      (self._now(), telegram_id))

    def broadcast_recipients(self, active_only=None):
        """
        آیدی تلگرامِ گیرنده‌های پیام همگانی؛ بلاک‌کننده‌های ربات همیشه حذفن.

        active_only=None  -> همه
        active_only=True  -> فقط لایسنسِ فعال دارن
        active_only=False -> لایسنسِ فعال ندارن
        """
        now = self._now()
        if active_only is True:
            rows = self.query(
                "SELECT DISTINCT u.telegram_id FROM users u "
                "JOIN licenses l ON l.user_id = u.telegram_id "
                "WHERE u.bot_blocked_at IS NULL AND l.status = 'active' AND l.expires_at > ?",
                (now,),
            )
        elif active_only is False:
            rows = self.query(
                "SELECT u.telegram_id FROM users u WHERE u.bot_blocked_at IS NULL "
                "AND u.telegram_id NOT IN ("
                "  SELECT DISTINCT l.user_id FROM licenses l "
                "  WHERE l.status = 'active' AND l.expires_at > ?)",
                (now,),
            )
        else:
            rows = self.query("SELECT telegram_id FROM users WHERE bot_blocked_at IS NULL")
        return [int(row["telegram_id"]) for row in rows]

    # ------------------------------------------------------------ orders

    def create_order(self, user_id, months, users, bots, features, amount_usd,
                     amount_irr=None, usd_rate=None, panel_code=None,
                     kind="new", license_id=None, status="awaiting_receipt"):
        now = self._now()
        cursor = self._execute(
            "INSERT INTO orders (user_id, kind, license_id, panel_code, months, users, bots, "
            "features, amount_usd, amount_irr, usd_rate, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, kind, license_id, panel_code, months, users, bots,
             json.dumps(features, ensure_ascii=False), amount_usd, amount_irr, usd_rate,
             status, now, now),
        )
        return self.get_order(cursor.lastrowid)

    def get_order(self, order_id):
        return self.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))

    def update_order(self, order_id, **fields):
        if not fields:
            return self.get_order(order_id)
        fields["updated_at"] = self._now()
        if "features" in fields and not isinstance(fields["features"], str):
            fields["features"] = json.dumps(fields["features"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._execute(f"UPDATE orders SET {assignments} WHERE id = ?",
                      tuple(fields.values()) + (order_id,))
        return self.get_order(order_id)

    def orders_by_user(self, user_id, limit=20):
        return self.query(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))

    def orders_by_status(self, status, limit=50):
        return self.query(
            "SELECT * FROM orders WHERE status = ? ORDER BY id ASC LIMIT ?", (status, limit))

    def pending_admin_orders(self, limit=50):
        return self.query(
            "SELECT * FROM orders WHERE status IN ('admin_review', 'check_failed') "
            "ORDER BY id ASC LIMIT ?", (limit,))

    # ---------------------------------------------------- crypto payments

    def create_crypto_payment(self, order_id, user_id, network, address, amount_micro,
                              expires_at):
        """
        اگه مبلغ با یه پرداختِ در انتظارِ دیگه یکی باشه sqlite3.IntegrityError
        می‌ده (ایندکس یکتا)؛ فراخوان مبلغ دیگه‌ای امتحان می‌کنه.
        """
        cursor = self._execute(
            "INSERT INTO crypto_payments (order_id, user_id, network, address, amount_micro, "
            "status, created_at, expires_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
            (order_id, user_id, network, address, amount_micro, self._now(), expires_at),
        )
        return self.get_crypto_payment(cursor.lastrowid)

    def get_crypto_payment(self, payment_id):
        return self.query_one("SELECT * FROM crypto_payments WHERE id = ?", (payment_id,))

    def crypto_payment_for_order(self, order_id):
        """آخرین پرداختِ تتریِ این سفارش، یا None."""
        return self.query_one(
            "SELECT * FROM crypto_payments WHERE order_id = ? ORDER BY id DESC LIMIT 1",
            (order_id,))

    def pending_crypto_payments(self):
        return self.query(
            "SELECT * FROM crypto_payments WHERE status = 'pending' ORDER BY id ASC")

    def recent_crypto_payments(self, statuses, limit=10):
        marks = ", ".join("?" for _ in statuses)
        return self.query(
            f"SELECT * FROM crypto_payments WHERE status IN ({marks}) "
            "ORDER BY id DESC LIMIT ?", tuple(statuses) + (limit,))

    def crypto_received_since(self, timestamp):
        """(تعداد، جمعِ مبلغ به میکرو) پرداخت‌های تتریِ تأییدشده از timestamp به بعد."""
        row = self.query_one(
            "SELECT COUNT(*), COALESCE(SUM(amount_micro), 0) FROM crypto_payments "
            "WHERE status = 'paid' AND paid_at >= ?", (int(timestamp),))
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def set_crypto_payment_status(self, payment_id, status, only_from="pending"):
        """
        وضعیت رو عوض می‌کنه، ولی فقط اگه هنوز توی only_from باشه (اتمیک؛
        دو مسیرِ هم‌زمان نمی‌تونن یه پرداخت رو دو بار ببندن). True اگه عوض شد.
        """
        cursor = self._execute(
            "UPDATE crypto_payments SET status = ? WHERE id = ? AND status = ?",
            (status, payment_id, only_from))
        return cursor.rowcount == 1

    def claim_crypto_payment(self, payment_id, tx_hash):
        """
        پرداخت رو با این تراکنش «پرداخت‌شده» می‌کنه. False یعنی یا قبلاً بسته
        شده یا این تراکنش قبلاً برای پرداخت دیگه‌ای ثبت شده (ایندکس یکتا).
        """
        try:
            cursor = self._execute(
                "UPDATE crypto_payments SET status = 'paid', tx_hash = ?, paid_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (tx_hash, self._now(), payment_id))
        except sqlite3.IntegrityError:
            return False
        return cursor.rowcount == 1

    # ---------------------------------------------------------- licenses

    def create_license(self, key, user_id, order_id, max_bots, max_users, features,
                       starts_at, expires_at, status="active"):
        now = self._now()
        cursor = self._execute(
            "INSERT INTO licenses (key, user_id, order_id, max_bots, max_users, features, "
            "starts_at, expires_at, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, user_id, order_id, max_bots, max_users,
             json.dumps(features, ensure_ascii=False), starts_at, expires_at, status, now, now),
        )
        return self.get_license(cursor.lastrowid)

    def get_license(self, license_id):
        return self.query_one("SELECT * FROM licenses WHERE id = ?", (license_id,))

    def get_license_by_key(self, key):
        return self.query_one("SELECT * FROM licenses WHERE key = ?", (key,))

    def update_license(self, license_id, **fields):
        if not fields:
            return self.get_license(license_id)
        fields["updated_at"] = self._now()
        if "features" in fields and not isinstance(fields["features"], str):
            fields["features"] = json.dumps(fields["features"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._execute(f"UPDATE licenses SET {assignments} WHERE id = ?",
                      tuple(fields.values()) + (license_id,))
        return self.get_license(license_id)

    def licenses_by_user(self, user_id):
        return self.query(
            "SELECT * FROM licenses WHERE user_id = ? ORDER BY id DESC", (user_id,))

    def active_licenses(self):
        return self.query("SELECT * FROM licenses WHERE status = 'active' ORDER BY expires_at ASC")

    def licenses_expiring_before(self, timestamp, status="active"):
        return self.query(
            "SELECT * FROM licenses WHERE status = ? AND expires_at <= ? ORDER BY expires_at ASC",
            (status, timestamp),
        )

    def licenses_by_status(self, status=None, limit=8, offset=0):
        """
        صفحه‌ای از لایسنس‌ها، برای لیستِ ادمین توی تلگرام. status=None یا
        "all" یعنی بدون فیلتر.
        """
        if status and status != "all":
            return self.query(
                "SELECT * FROM licenses WHERE status = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            )
        return self.query("SELECT * FROM licenses ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))

    def count_licenses(self, status=None):
        if status and status != "all":
            row = self.query_one("SELECT COUNT(*) FROM licenses WHERE status = ?", (status,))
        else:
            row = self.query_one("SELECT COUNT(*) FROM licenses")
        return (row[0] if row else 0) or 0

    # --------------------------------------------------------- instances

    def create_instance(self, license_id, slug, tt_host, tt_port, tt_nickname, tt_username,
                        tt_password, tt_channel_id=1, tt_channel_password="",
                        operators=None, audio_line=None, group_name=None, bot_name=None,
                        status="created"):
        now = self._now()
        cursor = self._execute(
            "INSERT INTO instances (license_id, slug, tt_host, tt_port, tt_nickname, tt_username, "
            "tt_password, tt_channel_id, tt_channel_password, operators, audio_line, group_name, "
            "bot_name, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (license_id, slug, tt_host, tt_port, tt_nickname, tt_username, tt_password,
             tt_channel_id, tt_channel_password,
             json.dumps(operators or [], ensure_ascii=False), audio_line, group_name, bot_name,
             status, now, now),
        )
        return self.get_instance(cursor.lastrowid)

    def get_instance(self, instance_id):
        return self.query_one("SELECT * FROM instances WHERE id = ?", (instance_id,))

    def get_instance_by_slug(self, slug):
        return self.query_one("SELECT * FROM instances WHERE slug = ?", (slug,))

    def update_instance(self, instance_id, **fields):
        if not fields:
            return self.get_instance(instance_id)
        fields["updated_at"] = self._now()
        if "operators" in fields and not isinstance(fields["operators"], str):
            fields["operators"] = json.dumps(fields["operators"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._execute(f"UPDATE instances SET {assignments} WHERE id = ?",
                      tuple(fields.values()) + (instance_id,))
        return self.get_instance(instance_id)

    def instances_by_license(self, license_id, include_removed=False):
        if include_removed:
            return self.query(
                "SELECT * FROM instances WHERE license_id = ? ORDER BY id ASC", (license_id,))
        return self.query(
            "SELECT * FROM instances WHERE license_id = ? AND status != 'removed' ORDER BY id ASC",
            (license_id,),
        )

    def instances_by_user(self, user_id, include_removed=False):
        clause = "" if include_removed else "AND i.status != 'removed'"
        return self.query(
            f"SELECT i.* FROM instances i JOIN licenses l ON l.id = i.license_id "
            f"WHERE l.user_id = ? {clause} ORDER BY i.id ASC",
            (user_id,),
        )

    def runnable_instances(self):
        """
        نمونه‌هایی که باید همین الان در حال اجرا باشن: لایسنس فعال و نمونه‌ی
        حذف/متوقف‌نشده. سوپروایزر از همین لیست استفاده می‌کنه، یعنی وقتی
        لایسنس منقضی/معلق می‌شه، دفعه‌ی بعد خودکار بالا نمی‌آد.
        """
        return self.query(
            "SELECT i.* FROM instances i JOIN licenses l ON l.id = i.license_id "
            "WHERE l.status = 'active' AND i.status IN ('created', 'running', 'crashed') "
            "ORDER BY i.id ASC"
        )

    def delete_instance(self, instance_id):
        self._execute("DELETE FROM instances WHERE id = ?", (instance_id,))

    def delete_license(self, license_id):
        """
        لایسنس و ردیف نمونه‌هاش رو کامل پاک می‌کنه.

        *قبل* از این باید deprovision شده باشن (پروسه خاموش، لاین صدا حذف،
        دیتا پاک) -- اینجا فقط ردیف‌های دیتابیسه.

        جدول events دست نمی‌خوره: تاریخچه‌ی «چی صادر شد و کی پاکش کرد» باید
        بمونه، وگرنه پاک‌کردن یه لایسنس هر ردی از خودش رو هم پاک می‌کرد.
        """
        self._execute("DELETE FROM instances WHERE license_id = ?", (license_id,))
        self._execute("DELETE FROM licenses WHERE id = ?", (license_id,))

    def delete_order(self, order_id):
        """فقط برای پاکسازی (licensing/gc.py): سفارشِ تأییدنشده‌ی قدیمی."""
        self._execute("DELETE FROM orders WHERE id = ?", (order_id,))

    def delete_events_before(self, timestamp):
        """فقط برای پاکسازیِ اختیاری (licensing/gc.py)؛ audit trail پیش‌فرض می‌مونه."""
        self._execute("DELETE FROM events WHERE ts < ?", (timestamp,))

    # ----------------------------------------------------------- tickets

    def create_ticket(self, user_id, message, order_id=None):
        cursor = self._execute(
            "INSERT INTO tickets (user_id, order_id, message, created_at) VALUES (?, ?, ?, ?)",
            (user_id, order_id, message, self._now()),
        )
        return self.query_one("SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,))

    def close_ticket(self, ticket_id, admin_reply=None):
        self._execute(
            "UPDATE tickets SET status = 'closed', admin_reply = ?, closed_at = ? WHERE id = ?",
            (admin_reply, self._now(), ticket_id),
        )

    def open_tickets(self, limit=50):
        return self.query(
            "SELECT * FROM tickets WHERE status = 'open' ORDER BY id ASC LIMIT ?", (limit,))

    def get_ticket(self, ticket_id):
        return self.query_one("SELECT * FROM tickets WHERE id = ?", (ticket_id,))

    # ------------------------------------------------------- promo codes

    def create_promo(self, code, kind, value, features, valid_from, valid_until,
                     max_bots=1, max_users=1, per_user_limit=1, per_user_period="ever",
                     total_limit=0, note=None, created_by=None):
        self._execute(
            "INSERT INTO promo_codes (code, kind, value, features, max_bots, max_users, "
            "valid_from, valid_until, per_user_limit, per_user_period, total_limit, "
            "note, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (code.strip().upper(), kind, float(value),
             json.dumps(features or [], ensure_ascii=False),
             int(max_bots), int(max_users), int(valid_from), int(valid_until),
             int(per_user_limit), per_user_period, int(total_limit),
             note, created_by, self._now()),
        )
        return self.get_promo(code)

    def get_promo(self, code):
        return self.query_one("SELECT * FROM promo_codes WHERE code = ?",
                              (str(code).strip().upper(),))

    def update_promo(self, code, **fields):
        if not fields:
            return self.get_promo(code)
        if "features" in fields and not isinstance(fields["features"], str):
            fields["features"] = json.dumps(fields["features"], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in fields)
        self._execute(f"UPDATE promo_codes SET {assignments} WHERE code = ?",
                      tuple(fields.values()) + (str(code).strip().upper(),))
        return self.get_promo(code)

    def delete_promo(self, code):
        self._execute("DELETE FROM promo_codes WHERE code = ?", (str(code).strip().upper(),))

    def list_promos(self, only_active=False):
        if only_active:
            return self.query(
                "SELECT * FROM promo_codes WHERE active = 1 AND valid_until > ? "
                "ORDER BY created_at DESC", (self._now(),))
        return self.query("SELECT * FROM promo_codes ORDER BY created_at DESC")

    def record_redemption(self, code, user_id, license_id=None, order_id=None, detail=None):
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        self._execute(
            "INSERT INTO promo_redemptions (code, user_id, redeemed_at, license_id, order_id, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(code).strip().upper(), int(user_id), self._now(), license_id, order_id, detail),
        )
        self._execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?",
                      (str(code).strip().upper(),))

    def redemptions_by_user(self, code, user_id, since=None):
        if since:
            return self.query(
                "SELECT * FROM promo_redemptions WHERE code = ? AND user_id = ? AND redeemed_at >= ? "
                "ORDER BY id DESC", (str(code).strip().upper(), int(user_id), int(since)))
        return self.query(
            "SELECT * FROM promo_redemptions WHERE code = ? AND user_id = ? ORDER BY id DESC",
            (str(code).strip().upper(), int(user_id)))

    def redemption_count(self, code):
        row = self.query_one("SELECT COUNT(*) FROM promo_redemptions WHERE code = ?",
                             (str(code).strip().upper(),))
        return (row[0] if row else 0) or 0

    # ------------------------------------------------------------ events

    def log_event(self, kind, user_id=None, license_id=None, order_id=None, detail=None):
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        self._execute(
            "INSERT INTO events (ts, kind, user_id, license_id, order_id, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self._now(), kind, user_id, license_id, order_id, detail),
        )

    def recent_events(self, limit=50, kind=None):
        if kind:
            return self.query(
                "SELECT * FROM events WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit))
        return self.query("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))

    # --------------------------------------------------------- آمار کلی

    def stats(self):
        def scalar(sql, params=()):
            row = self.query_one(sql, params)
            return (row[0] if row else 0) or 0

        return {
            "users": scalar("SELECT COUNT(*) FROM users"),
            "licenses_active": scalar("SELECT COUNT(*) FROM licenses WHERE status = 'active'"),
            "licenses_expired": scalar("SELECT COUNT(*) FROM licenses WHERE status = 'expired'"),
            "instances_running": scalar("SELECT COUNT(*) FROM instances WHERE status = 'running'"),
            "instances_total": scalar("SELECT COUNT(*) FROM instances WHERE status != 'removed'"),
            "orders_pending": scalar(
                "SELECT COUNT(*) FROM orders WHERE status IN "
                "('awaiting_receipt', 'checking', 'admin_review', 'check_failed')"),
            "orders_approved": scalar("SELECT COUNT(*) FROM orders WHERE status = 'approved'"),
            "revenue_usd": scalar("SELECT SUM(amount_usd) FROM orders WHERE status = 'approved'"),
            "tickets_open": scalar("SELECT COUNT(*) FROM tickets WHERE status = 'open'"),
            "promos_active": scalar(
                "SELECT COUNT(*) FROM promo_codes WHERE active = 1 AND valid_until > ?",
                (int(time.time()),)),
            "promo_redemptions": scalar("SELECT COUNT(*) FROM promo_redemptions"),
        }


_default = None
_default_lock = threading.Lock()


def get_db():
    """دیتابیس مشترکِ پروسه. ساختنش idempotent و thread-safe است."""
    global _default
    with _default_lock:
        if _default is None:
            _default = Database()
        return _default


def json_list(value, default=None):
    """
    ستون‌های JSON دیتابیس رو به لیست پایتونی تبدیل می‌کنه، بدون این‌که یه
    مقدار خراب کل عملیات رو بخوابونه.
    """
    if value is None or value == "":
        return list(default or [])
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return list(default or [])
    return parsed if isinstance(parsed, list) else list(default or [])
