"""Auth hardening checks: PBKDF2 salted hashes, lockout, password rotation."""
import pathlib
import time

import pytest

from backend import users as users_module


@pytest.fixture
def user_db(tmp_path, monkeypatch):
    db = tmp_path / "users.db"
    monkeypatch.setattr(users_module, "DB_PATH", db)
    monkeypatch.setattr(users_module, "_initialized", False)
    users_module.init_db()
    return db


def test_demo_accounts_seed_once_and_login(user_db):
    result = users_module.authenticate("dr-demo", "demo123")
    assert result["ok"] and result["user"]["role"] == "doctor"
    assert result["user"]["reg"] == "MCI-12345"
    # Re-running init must not duplicate or reset accounts.
    users_module.init_db()
    assert users_module.authenticate("dr-demo", "demo123")["ok"]


def test_hashes_are_salted_pbkdf2(user_db):
    row1 = users_module._user_row("patient-demo")
    row2 = users_module._user_row("patient-demo-2")
    assert row1[1] != row2[1], "each account must have its own salt"
    assert row1[2] != row2[2], "same password must not produce the same hash"
    assert row1[3] >= 100_000, "PBKDF2 iteration count must be substantial"
    assert "demo123" not in (row1[2], row2[2]), "plaintext must never be stored"
    assert users_module.authenticate("patient-demo", "demo123")["ok"]
    assert not users_module.authenticate("patient-demo", "wrong")["ok"]


def test_lockout_after_repeated_failures(user_db, monkeypatch):
    monkeypatch.setattr(users_module, "LOCK_SECONDS", 0.05)
    for _ in range(users_module.LOCK_THRESHOLD):
        assert users_module.authenticate("dr-demo", "wrong")["ok"] is False
    status = users_module.lockout_status("dr-demo")
    assert status["failures"] == users_module.LOCK_THRESHOLD
    assert status["locked_for"] > 0
    # Correct credentials are also rejected while locked.
    locked = users_module.authenticate("dr-demo", "demo123")
    assert locked["ok"] is False and "locked" in locked["reason"]
    time.sleep(0.06)
    assert users_module.authenticate("dr-demo", "demo123")["ok"], "lock must expire"


def test_lockout_counts_unknown_usernames_to_prevent_enumeration(user_db):
    for _ in range(users_module.LOCK_THRESHOLD):
        users_module.authenticate("ghost-user", "nope")
    assert users_module.lockout_status("ghost-user")["failures"] == users_module.LOCK_THRESHOLD
    # A real account is unaffected by failures aimed at another username.
    assert users_module.authenticate("pharm-demo", "demo123")["ok"]


def test_successful_login_clears_failure_count(user_db):
    users_module.authenticate("patient-demo-2", "wrong")
    users_module.authenticate("patient-demo-2", "wrong")
    assert users_module.authenticate("patient-demo-2", "demo123")["ok"]
    assert users_module.lockout_status("patient-demo-2")["failures"] == 0


def test_change_password_rotates_salt_and_rejects_reuse(user_db):
    before = users_module._user_row("patient-demo")
    assert users_module.change_password("patient-demo", "demo123", "new-strong-pw-1")["ok"]
    after = users_module._user_row("patient-demo")
    assert after[1] != before[1], "a password change must generate a fresh salt"
    assert not users_module.authenticate("patient-demo", "demo123")["ok"]
    assert users_module.authenticate("patient-demo", "new-strong-pw-1")["ok"]
    # Wrong current password is rejected and counted.
    assert not users_module.change_password("patient-demo", "demo123", "another-pw-123")["ok"]


def test_change_password_policy(user_db):
    assert not users_module.change_password("patient-demo", "demo123", "short")["ok"]
    assert not users_module.change_password("patient-demo", "demo123", "demo123")["ok"]
    assert not users_module.change_password("missing-user", "x", "whatever-long")["ok"]
