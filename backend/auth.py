"""Auth/RBAC: SQLite PBKDF2 user store + JWT roles + account lockout.

Swap with Keycloak / ABDM HPR in production; the JWT contract stays the same.
"""
import os
import re
import time
import jwt
from fastapi import HTTPException
from backend import users
from backend.config import ENV

SECRET = os.getenv("CLINIVA_AUTH_SECRET", "")
if not SECRET:
    if ENV == "prod":
        raise RuntimeError("CLINIVA_AUTH_SECRET must be set in prod")
    SECRET = "cliniva-auth-demo-change-in-prod"
if ENV == "prod" and len(SECRET) < 32:
    raise RuntimeError("CLINIVA_AUTH_SECRET must be at least 32 characters in prod")
MCI_RE = re.compile(r"^(MCI|KMC|TNMC|MMC)-[A-Z0-9-]{4,20}$", re.I)


def valid_mci(reg: str) -> bool:
    return bool(MCI_RE.match((reg or "").strip()))


def login(username: str, password: str) -> dict:
    if ENV == "prod":
        return {"ok": False, "reason": "Demo credential login is disabled in prod; configure an identity provider."}
    if not isinstance(username, str) or not username:
        return {"ok": False, "reason": "bad credentials"}
    result = users.authenticate(username, password)
    if not result.get("ok"):
        return {"ok": False, "reason": result.get("reason", "bad credentials")}
    u = result["user"]
    tok = jwt.encode({"sub": u["username"], "role": u["role"], "reg": u.get("reg"),
                      "patient_id": u.get("patient_id"), "exp": int(time.time()) + 8 * 3600}, SECRET, algorithm="HS256")
    return {"ok": True, "token": tok, "role": u["role"]}


def change_password(username: str, old_password: str, new_password: str) -> dict:
    return users.change_password(username, old_password, new_password)


def require_role(token: str, roles: list) -> dict:
    try:
        d = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return {"ok": False, "reason": "Invalid or expired token"}
    if d.get("role") not in roles:
        return {"ok": False, "reason": f"role {d.get('role')} not in {roles}"}
    return {"ok": True, "user": d}


def current_actor(authorization: str | None, roles: list[str] | None = None) -> dict:
    """Validate a bearer token and optionally restrict it to the supplied roles."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    result = require_role(authorization[7:].strip(), roles or ["doctor", "pharmacist", "patient"])
    if not result.get("ok"):
        reason = result.get("reason", "forbidden")
        if reason.startswith("role "):
            raise HTTPException(status_code=403, detail="Insufficient role")
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return result["user"]
