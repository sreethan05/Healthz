"""Append-only audit log (DPDP/ABDM evidence). JSONL at data/audit.jsonl"""
import json
import pathlib
import time

AUDIT = pathlib.Path(__file__).resolve().parent.parent / "data" / "audit.jsonl"


def log(event: str, patient_id: str = "", actor: str = "", detail: dict | None = None) -> dict:
    rec = {"ts": int(time.time()), "event": event, "patient_id": patient_id, "actor": actor, "detail": detail or {}}
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def read_all(limit: int = 100) -> list:
    limit = max(0, int(limit))
    if limit == 0:
        return []
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text(encoding="utf-8").strip().split("\n")
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out


def dpdp_notice(purpose: str = "OPD consultation at Cliniva Demo Clinic") -> dict:
    return {
        "title": "How we use your health data (DPDP Notice)",
        "language": ["en", "hi (on request)"],
        "collects": ["name, age, ABHA ID", "allergies, conditions, prescriptions", "consult transcript (with mic consent)"],
        "purposes": [purpose, "safety check (allergy/drug-interaction)", "follow-up reminders"],
        "sharing": "Local demo only. No live ABDM connection or external sharing is configured by default.",
        "rights": "This prototype demonstrates a local consent record, correction workflow, and revocation lock; it is not a complete rights-request process.",
        "retention": "Demo files are stored locally until removed. No production retention schedule is configured.",
        "contact": "Demo contact: dpo@cliniva.demo (not a monitored service)",
        "storage": "Local demo storage by default. Encryption, transport security, residency, and immutable audit storage depend on deployment and are not provided by this prototype.",
    }
