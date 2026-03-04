import sqlite3
from datetime import datetime


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def init(self):
        cur = self.conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            created_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS profile (
            user_id INTEGER PRIMARY KEY,
            age INTEGER,
            gender TEXT,
            skin_type TEXT,
            barrier_state TEXT,
            sensitivity TEXT,
            concerns TEXT,
            updated_at TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS subscription (
            user_id INTEGER PRIMARY KEY,
            is_premium INTEGER DEFAULT 0,
            premium_until TEXT,
            payment_method_id TEXT,
            last_payment_id TEXT
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            user_id INTEGER PRIMARY KEY,
            inci_checks_used INTEGER DEFAULT 0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER,
            product_id TEXT,
            step TEXT,
            name TEXT,
            url TEXT,
            price_after_rub INTEGER,
            price_before_rub INTEGER,
            added_at TEXT,
            PRIMARY KEY (user_id, product_id)
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            user_id INTEGER,
            yk_payment_id TEXT,
            amount_rub INTEGER,
            issued_at TEXT
        )
        """)

        self.conn.commit()

    # ---------- users ----------
    def ensure_user(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO users(user_id, created_at) VALUES(?, ?)",
                        (user_id, datetime.utcnow().isoformat()))
        cur.execute("SELECT user_id FROM usage WHERE user_id=?", (user_id,))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO usage(user_id, inci_checks_used) VALUES(?, 0)", (user_id,))
        cur.execute("SELECT user_id FROM subscription WHERE user_id=?", (user_id,))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO subscription(user_id, is_premium, premium_until) VALUES(?, 0, NULL)", (user_id,))
        self.conn.commit()

    # ---------- profile ----------
    def save_profile(self, user_id: int, skin_type: str, barrier_state: str, sensitivity: str, concerns: str,
                     age: int | None = None, gender: str | None = None):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO profile(user_id, age, gender, skin_type, barrier_state, sensitivity, concerns, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            age=excluded.age,
            gender=excluded.gender,
            skin_type=excluded.skin_type,
            barrier_state=excluded.barrier_state,
            sensitivity=excluded.sensitivity,
            concerns=excluded.concerns,
            updated_at=excluded.updated_at
        """, (
            user_id, age, gender, skin_type, barrier_state, sensitivity, concerns, datetime.utcnow().isoformat()
        ))
        self.conn.commit()

    def set_age_gender(self, user_id: int, age: int | None, gender: str | None):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO profile(user_id, age, gender, updated_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            age=excluded.age,
            gender=excluded.gender,
            updated_at=excluded.updated_at
        """, (user_id, age, gender, datetime.utcnow().isoformat()))
        self.conn.commit()

    def get_profile(self, user_id: int) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM profile WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else {}

    # ---------- subscription ----------
    def get_subscription(self, user_id: int) -> dict:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM subscription WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else {"is_premium": 0, "premium_until": None}

    def set_premium(self, user_id: int, premium_until_iso: str, payment_method_id=None, last_payment_id=None):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO subscription(user_id, is_premium, premium_until, payment_method_id, last_payment_id)
        VALUES(?, 1, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            is_premium=1,
            premium_until=excluded.premium_until,
            payment_method_id=excluded.payment_method_id,
            last_payment_id=excluded.last_payment_id
        """, (user_id, premium_until_iso, payment_method_id, last_payment_id))
        self.conn.commit()

    def disable_premium(self, user_id: int):
        cur = self.conn.cursor()
        cur.execute("UPDATE subscription SET is_premium=0 WHERE user_id=?", (user_id,))
        self.conn.commit()

    # ---------- usage (INCI checks) ----------
    def get_checks_used(self, user_id: int) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT inci_checks_used FROM usage WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return int(row["inci_checks_used"]) if row else 0

    def inc_checks_used(self, user_id: int, delta: int = 1):
        cur = self.conn.cursor()
        cur.execute("UPDATE usage SET inci_checks_used = COALESCE(inci_checks_used, 0) + ? WHERE user_id=?",
                    (delta, user_id))
        self.conn.commit()

    # ---------- favorites ----------
    def add_favorite(self, user_id: int, product_id: str, step: str, name: str, url: str | None,
                     price_after_rub: int | None, price_before_rub: int | None):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT OR REPLACE INTO favorites(user_id, product_id, step, name, url, price_after_rub, price_before_rub, added_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, product_id, step, name, url,
            price_after_rub, price_before_rub,
            datetime.utcnow().isoformat()
        ))
        self.conn.commit()

    def remove_favorite(self, user_id: int, product_id: str):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM favorites WHERE user_id=? AND product_id=?", (user_id, product_id))
        self.conn.commit()

    def list_favorites(self, user_id: int) -> list[dict]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM favorites WHERE user_id=? ORDER BY added_at DESC", (user_id,))
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def is_favorite(self, user_id: int, product_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM favorites WHERE user_id=? AND product_id=? LIMIT 1", (user_id, product_id))
        return cur.fetchone() is not None

    # ---------- receipts ----------
    def mark_receipt_issued(self, user_id: int, yk_payment_id: str | None, amount_rub: int):
        cur = self.conn.cursor()
        cur.execute("""
        INSERT INTO receipts(user_id, yk_payment_id, amount_rub, issued_at)
        VALUES(?, ?, ?, ?)
        """, (user_id, yk_payment_id, amount_rub, datetime.utcnow().isoformat()))
        self.conn.commit()