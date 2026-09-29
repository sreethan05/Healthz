"""Auth/RBAC demo: MCI format check + hashed passwords + JWT roles. Swap with Keycloak/ABDM HPR in prod."""
import hashlib
import hmac
import os
import re
import time
import jwt
from fastapi import HTTPException
from backend.config import ENV

SECRET = os.getenv("CLINIVA_AUTH_SECRET", "")
if not SECRET:
    if ENV == "prod":
        raise RuntimeError("CLINIVA_AUTH_SECRET must be set in prod")
    SECRET = "cliniva-auth-demo-change-in-prod"
if ENV == "prod" and len(SECRET) < 32:
    raise RuntimeError("CLINIVA_AUTH_SECRET must be at least 32 characters in prod")
MCI_RE = re.compile(r"^(MCI|KMC|TNMC|MMC)-[A-Z0-9-]{4,20}$", re.I)

USERS = {
    "dr-demo": {"pw_hash": hashlib.sha256(b"demo123").hexdigest(), "role": "doctor", "reg": "MCI-12345"},
    "pharm-demo": {"pw_hash": hashlib.sha256(b"demo123").hexdigest(), "role": "pharmacist", "reg": "PCI-999"},
    "patient-demo": {"pw_hash": hashlib.sha256(b"demo123").hexdigest(), "role": "patient", "patient_id": "demo-001"},
    "patient-demo-2": {"pw_hash": hashlib.sha256(b"demo123").hexdigest(), "role": "patient", "patient_id": "demo-002"},
}


def valid_mci(reg: str) -> bool:
    return bool(MCI_RE.match((reg or "").strip()))


def login(username: str, password: str) -> dict:
    if ENV == "prod":
        return {"ok": False, "reason": "Demo credential login is disabled in prod; configure an identity provider."}
    u = USERS.get(username)
    if not isinstance(password, str) or len(password) > 1024:
        return {"ok": False, "reason": "bad credentials"}
    candidate = hashlib.sha256(password.encode()).hexdigest()
    if not u or not hmac.compare_digest(u["pw_hash"], candidate):
        return {"ok": False, "reason": "bad credentials"}
    tok = jwt.encode({"sub": username, "role": u["role"], "reg": u.get("reg"),
                      "patient_id": u.get("patient_id"), "exp": int(time.time()) + 8 * 3600}, SECRET, algorithm="HS256")
    return {"ok": True, "token": tok, "role": u["role"]}


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
