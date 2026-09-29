"""Hash-chained audit (tamper-evident) + retention policies + booking engine + eval."""
import hashlib
import json
import pathlib
import time

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
CHAIN = DATA / "audit_chain.jsonl"

RETENTION = {
    "opd_note": {"years": 10, "basis": "demo setting; confirm with applicable requirements"},
    "prescription": {"years": 10, "basis": "demo setting; confirm with applicable requirements"},
    "audio": {"years": 3, "basis": "demo setting; not a production policy"},
    "analytics": {"years": 1, "basis": "demo setting; not a production policy"},
}


def chain_log(event: str, patient_id: str = "", actor: str = "", detail: dict | None = None) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    prev = "GENESIS"
    if CHAIN.exists():
        verified = verify_chain()
        if not verified["ok"]:
            raise RuntimeError("Audit chain is damaged; refusing to append")
        lines = CHAIN.read_text(encoding="utf-8").splitlines()
        if lines:
            prev = json.loads(lines[-1])["hash"]
    rec = {"ts": int(time.time()), "event": event, "patient_id": patient_id, "actor": actor, "detail": detail or {}, "prev": prev}
    rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
    with CHAIN.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def verify_chain(limit: int = 200) -> dict:
    """Verify the complete chain. `limit` remains accepted for older callers."""
    if not CHAIN.exists():
        return {"ok": True, "checked": 0}
    try:
        lines = CHAIN.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return {"ok": False, "bad_index": 0}
    prev = "GENESIS"
    for i, ln in enumerate(lines):
        try:
            record = json.loads(ln)
            h = record.pop("hash")
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
            return {"ok": False, "bad_index": i}
        if not isinstance(record, dict) or not isinstance(h, str):
            return {"ok": False, "bad_index": i}
        if hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest() != h:
            return {"ok": False, "bad_index": i}
        if record.get("prev") != prev:
            return {"ok": False, "bad_link": i}
        prev = h
    return {"ok": True, "checked": len(lines)}


def retention_check(record_type: str, created_ts: int) -> dict:
    pol = RETENTION.get(record_type, {"years": 3, "basis": "default"})
    due = created_ts + pol["years"] * 365 * 24 * 3600
    return {"type": record_type, "keep_until": due, "expired": int(time.time()) > due, "basis": pol["basis"]}


SLOTS = ["Sat 10:00", "Sat 11:00", "Sun 18:00", "Mon 09:30"]


def suggest_slots(preferences: dict, booked: list | None = None) -> dict:
    booked = booked or []
    pref_days = preferences.get("followup_days", [])
    ranked = sorted(SLOTS, key=lambda s: 0 if any(d[:3].lower() in s.lower() for d in pref_days) else 1)
    free = [s for s in ranked if s not in booked]
    return {"suggested": free[:3], "channel": preferences.get("channel", "sms"), "reminder": "T-24h + T-2h"}


def send_reminder(channel: str, to: str, text: str) -> dict:
    # Deliberately simulate delivery; no message is sent by this prototype.
    return {"sent": False, "simulated": True, "channel": channel, "to": to, "preview": text[:120], "provider": "mock"}


def memory_regression() -> dict:
    """Tiny LongMemEval-style check: correction must be recallable."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from memory.hindsight_client import bank_id_for_patient, recall, retain
    b = bank_id_for_patient("eval-probe")
    retain(b, "Probe allergy: test-penicillin avoid", kind="correction", metadata={"eval": True})
    hit = any("test-penicillin" in f.get("content", "").lower() for f in recall(b, "test-penicillin allergy")["facts"])
    stale = recall(b, "followup")  # exercises path
    return {"recall_hit": hit, "recall_path_ok": "facts" in stale}
