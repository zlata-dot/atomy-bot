import sqlite3
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    checks_used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS skin_profiles (
    user_id INTEGER PRIMARY KEY,
    skin_type TEXT,
    barrier_state TEXT,
    sensitivity TEXT,
    concerns TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    is_premium INTEGER DEFAULT 0,
    premium_until TEXT,
    payment_method_id TEXT,
    last_payment_id TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    yk_payment_id TEXT NOT NULL,
    status TEXT,
    amount_rub INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    user_id INTEGER NOT NULL,
    yk_payment_id TEXT,
    amount_rub INTEGER,
    status TEXT,              -- "issued"
    issued_at TEXT NOT NULL
);
"""

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class DB:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init(self):
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()

    def _migrate(self):
        # добавляем колонки в старую users если нужно
        cur = self._conn.execute("PRAGMA table_info(users)")
        cols = {r["name"] for r in cur.fetchall()}
        if "checks_used" not in cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN checks_used INTEGER DEFAULT 0")
        self._conn.commit()

    def ensure_user(self, user_id: int):
        cur = self._conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if cur.fetchone() is None:
            self._conn.execute(
                "INSERT INTO users(user_id, created_at, checks_used) VALUES(?,?,0)",
                (user_id, utcnow_iso()),
            )
            self._conn.commit()

    # ---- profiles ----
    def save_profile(self, user_id: int, skin_type: str, barrier_state: str, sensitivity: str, concerns: str):
        self.ensure_user(user_id)
        self._conn.execute(
            """
            INSERT INTO skin_profiles(user_id, skin_type, barrier_state, sensitivity, concerns, updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                skin_type=excluded.skin_type,
                barrier_state=excluded.barrier_state,
                sensitivity=excluded.sensitivity,
                concerns=excluded.concerns,
                updated_at=excluded.updated_at
            """,
            (user_id, skin_type, barrier_state, sensitivity, concerns, utcnow_iso()),
        )
        self._conn.commit()

    def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM skin_profiles WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    # ---- free checks ----
    def get_checks_used(self, user_id: int) -> int:
        self.ensure_user(user_id)
        cur = self._conn.execute("SELECT checks_used FROM users WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return int(row["checks_used"]) if row else 0

    def inc_checks_used(self, user_id: int):
        self.ensure_user(user_id)
        self._conn.execute("UPDATE users SET checks_used = checks_used + 1 WHERE user_id=?", (user_id,))
        self._conn.commit()

    # ---- subscriptions ----
    def get_subscription(self, user_id: int) -> Dict[str, Any]:
        self.ensure_user(user_id)
        cur = self._conn.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row)

        self._conn.execute(
            """
            INSERT INTO subscriptions(user_id, is_premium, premium_until, payment_method_id, last_payment_id, updated_at)
            VALUES(?,0,NULL,NULL,NULL,?)
            """,
            (user_id, utcnow_iso()),
        )
        self._conn.commit()
        return self.get_subscription(user_id)

    def set_premium(self, user_id: int, premium_until_iso: str, payment_method_id: Optional[str], last_payment_id: Optional[str]):
        self.ensure_user(user_id)
        self._conn.execute(
            """
            INSERT INTO subscriptions(user_id, is_premium, premium_until, payment_method_id, last_payment_id, updated_at)
            VALUES(?,1,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_premium=1,
                premium_until=excluded.premium_until,
                payment_method_id=COALESCE(excluded.payment_method_id, subscriptions.payment_method_id),
                last_payment_id=COALESCE(excluded.last_payment_id, subscriptions.last_payment_id),
                updated_at=excluded.updated_at
            """,
            (user_id, premium_until_iso, payment_method_id, last_payment_id, utcnow_iso()),
        )
        self._conn.commit()

    def disable_premium(self, user_id: int):
        self._conn.execute(
            "UPDATE subscriptions SET is_premium=0, updated_at=? WHERE user_id=?",
            (utcnow_iso(), user_id),
        )
        self._conn.commit()

    def list_subscriptions(self) -> list[Dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM subscriptions")
        return [dict(r) for r in cur.fetchall()]

    # ---- payments ----
    def save_payment(self, user_id: int, yk_payment_id: str, status: str, amount_rub: int):
        self.ensure_user(user_id)
        self._conn.execute(
            "INSERT INTO payments(user_id, yk_payment_id, status, amount_rub, created_at) VALUES(?,?,?,?,?)",
            (user_id, yk_payment_id, status, amount_rub, utcnow_iso()),
        )
        self._conn.commit()

    def update_payment_status(self, yk_payment_id: str, status: str):
        self._conn.execute("UPDATE payments SET status=? WHERE yk_payment_id=?", (status, yk_payment_id))
        self._conn.commit()

    def get_last_payment_for_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM payments WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    # ---- receipts ----
    def mark_receipt_issued(self, user_id: int, yk_payment_id: Optional[str], amount_rub: Optional[int]):
        self.ensure_user(user_id)
        self._conn.execute(
            """
            INSERT INTO receipts(user_id, yk_payment_id, amount_rub, status, issued_at)
            VALUES(?,?,?,?,?)
            """,
            (user_id, yk_payment_id, amount_rub, "issued", utcnow_iso()),
        )
        self._conn.commit()

    def get_last_receipt(self, user_id: int) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM receipts WHERE user_id=? ORDER BY issued_at DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None