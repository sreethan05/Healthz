"""Signed QR e-prescription. QR = verify URL with hash. Tamper-evident."""
import base64
import hashlib
import io
import json
import time
import uuid

import jwt  # PyJWT
from backend.config import RX_SECRET, VERIFY_BASE

SECRET = RX_SECRET


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def qr_png_base64(payload: str) -> str:
    import qrcode

    img = qrcode.make(payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def sign_prescription(patient_id: str, doctor_id: str, doctor_reg: str, meds: list, soap: dict,
                      verify_base: str | None = None) -> dict:
    rx_id = str(uuid.uuid4())
    body = {
        "rx_id": rx_id,
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "doctor_reg": doctor_reg,
        "meds": meds,
        "soap_summary": {k: (soap or {}).get(k) for k in ("assessment", "plan")},
        "issued_at": int(time.time()),
        "format": "PCI/FHIR-PrescriptionRecord-demo",
    }
    digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
    token = jwt.encode({**body, "hash": digest}, SECRET, algorithm="HS256")
    qr_payload = f"{verify_base or VERIFY_BASE}/{rx_id}?h={digest[:16]}"
    try:
        qr_b64 = qr_png_base64(qr_payload)
    except Exception:
        qr_b64 = ""
    return {
        "rx_id": rx_id,
        "body": body,
        "hash": digest,
        "token": token,
        "qr_payload": qr_payload,
        "qr_png_base64": qr_b64,
        "verify_hint": "Pharmacy scans QR -> opens verify screen -> hash recomputed. Mismatch = TAMPERED.",
    }


def verify_prescription(token: str) -> dict:
    try:
        data = jwt.decode(token, SECRET, algorithms=["HS256"])
    except Exception as e:
        return {"valid": False, "reason": f"bad signature: {e}"}
    claimed = data.pop("hash", "")
    recomputed = hashlib.sha256(_canonical({k: v for k, v in data.items()}).encode()).hexdigest()
    if claimed != recomputed:
        return {"valid": False, "reason": "hash mismatch — TAMPERED"}
    return {"valid": True, "rx": data, "hash": recomputed}
