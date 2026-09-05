from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from auth.passwords import hash_password, verify_password

MAX_USERS = 10
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "users.db"


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    display_name: str
    role: str
    created_at: str
    last_login: Optional[str] = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "created_at": self.created_at,
            "last_login": self.last_login,
        }


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        display_name=row["display_name"],
        role=row["role"],
        created_at=row["created_at"],
        last_login=row["last_login"],
    )


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                last_login TEXT
            )
            """
        )
        conn.commit()


def count_users() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"]) if row else 0


def list_users() -> list[User]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY id ASC"
        ).fetchall()
    return [_row_to_user(row) for row in rows]


def get_user_by_id(user_id: int) -> Optional[User]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
        ).fetchone()
    return _row_to_user(row) if row else None


def create_user(
    username: str,
    password: str,
    display_name: str = "",
    role: str = "user",
) -> User:
    if count_users() >= MAX_USERS:
        raise ValueError("max_users")
    username = username.strip().lower()
    if not username or len(username) < 2:
        raise ValueError("invalid_username")
    if len(password) < 6:
        raise ValueError("weak_password")
    if role not in ("admin", "user"):
        raise ValueError("invalid_role")
    if get_user_by_username(username):
        raise ValueError("username_taken")

    now = datetime.now(timezone.utc).isoformat()
    name = display_name.strip() or username
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, hash_password(password), name, role, now),
        )
        conn.commit()
        user_id = int(cursor.lastrowid)
    user = get_user_by_id(user_id)
    if not user:
        raise RuntimeError("Failed to create user")
    return user


def delete_user(user_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0


def record_login(user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user_id))
        conn.commit()


def authenticate(username: str, password: str) -> Optional[User]:
    user = get_user_by_username(username)
    if not user or not verify_password(password, user.password_hash):
        return None
    record_login(user.id)
    return user


def seed_admin(username: str, password: str) -> Optional[User]:
    if count_users() > 0:
        return None
    return create_user(username, password, display_name=username, role="admin")


def init_auth(admin_username: str, admin_password: str) -> Optional[User]:
    init_db()
    return seed_admin(admin_username, admin_password)
