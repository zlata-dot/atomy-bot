import sqlite3
from typing import Optional, Dict, Any


class DB:
    def __init__(self, path: str = "cosmo.sqlite3"):
        self.path = path

    def _con(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def init(self):
        with self._con() as con:
            cur = con.cursor()
            # Основная таблица пользователей
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    age INTEGER,
                    gender TEXT,
                    skin_type TEXT,
                    barrier_state TEXT,
                    sensitivity TEXT,
                    concerns TEXT,
                    checks_used INTEGER DEFAULT 0,
                    is_premium INTEGER DEFAULT 0,
                    premium_until TEXT,
                    payment_method_id TEXT,
                    last_payment_id TEXT,
                    receipt_issued INTEGER DEFAULT 0,
                    receipt_amount_rub INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            # На случай если таблица была старой — добавим колонки безопасно
            self._ensure_column(cur, "users", "age", "INTEGER")
            self._ensure_column(cur, "users", "gender", "TEXT")
            self._ensure_column(cur, "users", "skin_type", "TEXT")
            self._ensure_column(cur, "users", "barrier_state", "TEXT")
            self._ensure_column(cur, "users", "sensitivity", "TEXT")
            self._ensure_column(cur, "users", "concerns", "TEXT")
            self._ensure_column(cur, "users", "checks_used", "INTEGER DEFAULT 0")
            self._ensure_column(cur, "users", "is_premium", "INTEGER DEFAULT 0")
            self._ensure_column(cur, "users", "premium_until", "TEXT")
            self._ensure_column(cur, "users", "payment_method_id", "TEXT")
            self._ensure_column(cur, "users", "last_payment_id", "TEXT")
            self._ensure_column(cur, "users", "receipt_issued", "INTEGER DEFAULT 0")
            self._ensure_column(cur, "users", "receipt_amount_rub", "INTEGER DEFAULT 0")
            self._ensure_column(cur, "users", "created_at", "TEXT")

            con.commit()

    def _ensure_column(self, cur, table: str, col: str, col_def: str):
        cur.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}")

    # ---- users ----

    def ensure_user(self, user_id: int):
        with self._con() as con:
            con.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            con.commit()

    def set_demographics(self, user_id: int, age: int, gender: str):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute(
                "UPDATE users SET age = ?, gender = ? WHERE user_id = ?",
                (age, gender, user_id),
            )
            con.commit()

    def save_profile(self, user_id: int, skin_type: str, barrier_state: str, sensitivity: str, concerns: str):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute(
                """
                UPDATE users
                SET skin_type = ?, barrier_state = ?, sensitivity = ?, concerns = ?
                WHERE user_id = ?
                """,
                (skin_type, barrier_state, sensitivity, concerns, user_id),
            )
            con.commit()

    def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        self.ensure_user(user_id)
        with self._con() as con:
            row = con.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    # ---- free checks ----

    def get_checks_used(self, user_id: int) -> int:
        self.ensure_user(user_id)
        with self._con() as con:
            row = con.execute("SELECT checks_used FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return int(row["checks_used"] or 0) if row else 0

    def inc_checks_used(self, user_id: int) -> int:
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute("UPDATE users SET checks_used = COALESCE(checks_used, 0) + 1 WHERE user_id = ?", (user_id,))
            con.commit()
        return self.get_checks_used(user_id)

    # ---- premium ----

    def get_subscription(self, user_id: int) -> Dict[str, Any]:
        self.ensure_user(user_id)
        with self._con() as con:
            row = con.execute(
                "SELECT is_premium, premium_until, payment_method_id, last_payment_id FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return dict(row) if row else {"is_premium": 0, "premium_until": None, "payment_method_id": None, "last_payment_id": None}

    def set_premium(self, user_id: int, premium_until_iso: str, payment_method_id: Optional[str], last_payment_id: Optional[str]):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute(
                """
                UPDATE users
                SET is_premium = 1,
                    premium_until = ?,
                    payment_method_id = ?,
                    last_payment_id = ?
                WHERE user_id = ?
                """,
                (premium_until_iso, payment_method_id, last_payment_id, user_id),
            )
            con.commit()

    def disable_premium(self, user_id: int):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
            con.commit()

    # ---- receipts ----

    def mark_receipt_issued(self, user_id: int, yk_payment_id: Optional[str], amount_rub: int):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute(
                """
                UPDATE users
                SET receipt_issued = 1,
                    last_payment_id = COALESCE(?, last_payment_id),
                    receipt_amount_rub = ?
                WHERE user_id = ?
                """,
                (yk_payment_id, int(amount_rub), user_id),
            )
            con.commit()