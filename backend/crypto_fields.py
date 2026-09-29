"""Field encryption helper: Fernet when available, reversible-xor stub otherwise (flagged non-prod)."""
import base64
import os


def _fernet():
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("CLINIVA_FIELD_KEY", "")
        if not key:
            return None
        return Fernet(key.encode())
    except Exception:
        return None


def encrypt(text: str) -> dict:
    f = _fernet()
    if f:
        return {"alg": "fernet", "data": f.encrypt(text.encode()).decode()}
    return {"alg": "stub-base64-NOT-PROD", "data": base64.b64encode(text.encode()).decode()}


def decrypt(payload: dict) -> str:
    if payload.get("alg") == "fernet":
        f = _fernet()
        return f.decrypt(payload["data"].encode()).decode()
    return base64.b64decode(payload["data"].encode()).decode()
