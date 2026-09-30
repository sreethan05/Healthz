"""SQLite-backed user accounts: PBKDF2-SHA256 salted hashes + brute-force lockout.

Design notes:
- One DB file (data/cliniva.db, overridable via CLINIVA_USER_DB) with WAL mode.
- Passwords are never stored or compared in plain text; each user gets a random
  128-bit salt and a PBKDF2-SHA256 hash (200k iterations).
- Failed logins are counted per username for ANY attempted username (existing
  or not) so the lockout cannot be used to enumerate accounts. Five consecutive
  failures lock the username for 15 minutes; a successful login clears the count.
- The seeded demo accounts are created only when absent; password changes take
  effect immediately and survive restarts.
"""
import hashlib
import hmac
import os
import pathlib
import secrets
import sqlite3
import threading
import time

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "data" / "cliniva.db"
DB_PATH = pathlib.Path(os.getenv("CLINIVA_USER_DB", str(DEFAULT_DB)))

_ITERATIONS = 200_000
_SALT_BYTES = 16
LOCK_THRESHOLD = 5
LOCK_SECONDS = 15 * 60

_LOCK = threading.RLock()
_initialized = False

# username, password, role, reg, patient_id — evaluation accounts only.
DEMO_USERS = [
    ("dr-demo", "demo123", "doctor", "MCI-12345", None),
    ("pharm-demo", "demo123", "pharmacist", "PCI-999", None),
    ("patient-demo", "demo123", "patient", None, "demo-001"),
    ("patient-demo-2", "demo123", "patient", None, "demo-002"),
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db() -> None:
    global _initialized
    with _LOCK:
        if _initialized:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    salt TEXT NOT NULL,
                    pw_hash TEXT NOT NULL,
                    iterations INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    reg TEXT,
                    patient_id TEXT)"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS login_attempts (
                    username TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL DEFAULT 0,
                    locked_until REAL NOT NULL DEFAULT 0)"""
            )
            for username, password, role, reg, pid in DEMO_USERS:
                row = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
                if not row:
                    conn.execute(
                        "INSERT INTO users (username, salt, pw_hash, iterations, role, reg, patient_id) VALUES (?,?,?,?,?,?,?)",
                        (username, *hash_password(password), _ITERATIONS, role, reg, pid),
                    )
            conn.commit()
        finally:
            conn.close()
        _initialized = True


def hash_password(password: str, salt: str | None = None, iterations: int = _ITERATIONS) -> tuple[str, str]:
    """Return (salt, hash). Generates a fresh salt when none is supplied."""
    if salt is None:
        salt = secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return salt, digest


def _user_row(username: str):
    conn = _connect()
    try:
        return conn.execute(
            "SELECT username, salt, pw_hash, iterations, role, reg, patient_id FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    finally:
        conn.close()


def _lockout_remaining(conn: sqlite3.Connection, username: str) -> float:
    row = conn.execute("SELECT locked_until FROM login_attempts WHERE username = ?", (username,)).fetchone()
    return max(0.0, (row[0] or 0) - time.time()) if row else 0.0


def _record_failure(conn: sqlite3.Connection, username: str) -> None:
    row = conn.execute("SELECT failures FROM login_attempts WHERE username = ?", (username,)).fetchone()
    failures = (row[0] + 1) if row else 1
    locked_until = time.time() + LOCK_SECONDS if failures >= LOCK_THRESHOLD else 0
    conn.execute(
        """INSERT INTO login_attempts (username, failures, locked_until) VALUES (?,?,?)
           ON CONFLICT(username) DO UPDATE SET failures = excluded.failures, locked_until = excluded.locked_until""",
        (username, failures, locked_until),
    )


def _clear_failures(conn: sqlite3.Connection, username: str) -> None:
    conn.execute("DELETE FROM login_attempts WHERE username = ?", (username,))


def authenticate(username: str, password: str) -> dict:
    """Verify credentials with lockout. Returns {'ok': bool, 'reason': str, 'user': dict?}."""
    init_db()
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
        return {"ok": False, "reason": "bad credentials"}
    with _LOCK:
        conn = _connect()
        try:
            if _lockout_remaining(conn, username) > 0:
                return {"ok": False, "reason": "Account temporarily locked after repeated failed sign-ins. Try again later."}
            row = _user_row(username)
            if row:
                _username, salt, expected, iterations, role, reg, pid = row
                candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
                if hmac.compare_digest(candidate, expected):
                    _clear_failures(conn, username)
                    conn.commit()
                    return {"ok": True, "user": {"username": username, "role": role, "reg": reg, "patient_id": pid}}
            # Count failures for unknown usernames too (prevents account enumeration).
            _record_failure(conn, username)
            conn.commit()
            return {"ok": False, "reason": "bad credentials"}
        finally:
            conn.close()


def change_password(username: str, old_password: str, new_password: str) -> dict:
    """Rotate a user's password: verifies the current one, then re-salts and re-hashes."""
    init_db()
    if not isinstance(new_password, str) or len(new_password) < 8 or len(new_password) > 1024:
        return {"ok": False, "reason": "New password must be 8-1024 characters."}
    if old_password == new_password:
        return {"ok": False, "reason": "New password must differ from the current one."}
    with _LOCK:
        conn = _connect()
        try:
            if _lockout_remaining(conn, username) > 0:
                return {"ok": False, "reason": "Account temporarily locked after repeated failed sign-ins. Try again later."}
            row = _user_row(username)
            if not row:
                return {"ok": False, "reason": "Unknown account."}
            _username, salt, expected, iterations, *_ = row
            candidate = hashlib.pbkdf2_hmac("sha256", old_password.encode(), salt.encode(), iterations).hex()
            if not hmac.compare_digest(candidate, expected):
                _record_failure(conn, username)
                conn.commit()
                return {"ok": False, "reason": "Current password is incorrect."}
            new_salt, new_hash = hash_password(new_password)
            conn.execute(
                "UPDATE users SET salt = ?, pw_hash = ?, iterations = ? WHERE username = ?",
                (new_salt, new_hash, _ITERATIONS, username),
            )
            _clear_failures(conn, username)
            conn.commit()
            return {"ok": True}
        finally:
            conn.close()


def lockout_status(username: str) -> dict:
    """Remaining lockout (seconds) and consecutive-failure count for a username."""
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT failures, locked_until FROM login_attempts WHERE username = ?", (username,)).fetchone()
        if not row:
            return {"failures": 0, "locked_for": 0.0}
        return {"failures": row[0], "locked_for": max(0.0, (row[1] or 0) - time.time())}
    finally:
        conn.close()
