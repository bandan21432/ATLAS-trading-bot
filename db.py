import os
import sqlite3
import time
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                email TEXT PRIMARY KEY,
                salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                capital REAL NOT NULL DEFAULT 10000.0,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                broker TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                order_type TEXT NOT NULL,
                status TEXT NOT NULL,
                fill_price REAL,
                order_id TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (email) REFERENCES users(email)
            )
        """)


def create_user(email: str, salt: str, password_hash: str, capital: float = 10_000.0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (email, salt, password_hash, capital, created_at) VALUES (?, ?, ?, ?, ?)",
            (email, salt, password_hash, capital, time.time()),
        )


def get_user(email: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def user_exists(email: str) -> bool:
    return get_user(email) is not None


def log_trade(email: str, broker: str, symbol: str, side: str, quantity: float,
              order_type: str, status: str, fill_price: float = None, order_id: str = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO trades
               (email, broker, symbol, side, quantity, order_type, status, fill_price, order_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, broker, symbol, side, quantity, order_type, status, fill_price, order_id, time.time()),
        )


def get_trades(email: str = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        if email:
            rows = conn.execute(
                "SELECT * FROM trades WHERE email = ? ORDER BY created_at DESC LIMIT ?",
                (email, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]