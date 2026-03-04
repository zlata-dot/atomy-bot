import sqlite3
from typing import Optional, Dict, Any, List


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

            # USERS
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

            # FAVORITES / MY SET
            cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT,
                    step TEXT,
                    price_after_rub INTEGER,
                    price_before_rub INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

            con.commit()

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

    # ---- favorites / my set ----
    def add_favorite(self, user_id: int, name: str, url: str, step: str, price_after_rub: int | None, price_before_rub: int | None):
        self.ensure_user(user_id)
        with self._con() as con:
            # антидубликат: по user_id + name
            existing = con.execute(
                "SELECT id FROM favorites WHERE user_id = ? AND name = ?",
                (user_id, name),
            ).fetchone()
            if existing:
                return
            con.execute(
                """
                INSERT INTO favorites (user_id, name, url, step, price_after_rub, price_before_rub)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, name, url, step, price_after_rub, price_before_rub),
            )
            con.commit()

    def list_favorites(self, user_id: int) -> List[Dict[str, Any]]:
        self.ensure_user(user_id)
        with self._con() as con:
            rows = con.execute(
                "SELECT * FROM favorites WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_favorites(self, user_id: int):
        self.ensure_user(user_id)
        with self._con() as con:
            con.execute("DELETE FROM favorites WHERE user_id = ?", (user_id,))
            con.commit()