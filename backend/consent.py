"""Consent-gated access. DPDP + ABDM HIE-CM aligned (demo)."""
from dataclasses import dataclass
import json
import pathlib
import threading

@dataclass
class Consent:
    history: bool = True
    allergies: bool = True
    medications: bool = True
    purpose: str = "OPD consultation"
    revoked: bool = False

    def can_access(self, scope: str) -> bool:
        if self.revoked:
            return False
        return bool(getattr(self, scope, False))

    def revoke(self):
        self.revoked = True

    def grant(self):
        self.revoked = False

def filter_memory_by_consent(memory: dict, consent: Consent) -> dict:
    """Strip scopes without consent before showing timeline to doctor."""
    if consent.revoked:
        return {"locked": True, "lock_reason": "Consent revoked — timeline locked. Re-consent required."}
    out = dict(memory)
    allowed_scopes = set()
    if consent.history:
        allowed_scopes.update(("history", "preferences"))
    if consent.allergies:
        allowed_scopes.add("allergies")
    if consent.medications:
        allowed_scopes.add("medications")
    if not consent.history:
        if "patient" in out:
            out["patient"] = {"patient_id": out["patient"].get("patient_id")}
    # Free-text memory can't be reliably classified by keyword. Hide untagged
    # records whenever any scope is withheld; only return explicitly scoped facts.
    if not (consent.history and consent.allergies and consent.medications):
        out["facts"] = [
            fact for fact in out.get("facts", [])
            if fact.get("metadata", {}).get("scope") in allowed_scopes
        ]
        out["observations"] = []
        out["mental_models"] = []
    if not consent.can_access("allergies"):
        out["allergies"] = []
    if not consent.can_access("medications"):
        out["medications"] = []
        out["patient"] = dict(out.get("patient", {}))
        out["patient"].pop("current_meds", None)
    elif not consent.history and "patient" in memory:
        out["patient"]["current_meds"] = memory["patient"].get("current_meds", [])
    return out


CONSENT_FILE = pathlib.Path(__file__).resolve().parent.parent / "data" / "consents.json"
_CONSENT_LOCK = threading.RLock()


def get_consent(patient_id: str) -> Consent:
    try:
        records = json.loads(CONSENT_FILE.read_text(encoding="utf-8"))
        if not isinstance(records, dict):
            raise ValueError("Consent store root must be an object")
        row = records.get(patient_id, {})
        if not isinstance(row, dict):
            raise ValueError("Consent record must be an object")
        # Only literal JSON booleans can grant a scope. Truthy strings such as
        # "false" must never accidentally open access after manual corruption.
        return Consent(history=row.get("history") is True, allergies=row.get("allergies") is True,
                       medications=row.get("medications") is True, revoked=row.get("revoked") is not False)
    except (OSError, ValueError, TypeError, AttributeError):
        return Consent(history=False, allergies=False, medications=False, revoked=True)


def set_consent(patient_id: str, scopes: dict, revoked: bool = False) -> dict:
    with _CONSENT_LOCK:
        if CONSENT_FILE.exists():
            records = json.loads(CONSENT_FILE.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                raise ValueError("Consent store root must be an object")
        else:
            records = {}
        row = {key: scopes.get(key) is True for key in ("history", "allergies", "medications")}
        row["revoked"] = bool(revoked) or not any(row[key] for key in ("history", "allergies", "medications"))
        records[patient_id] = row
        CONSENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONSENT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2), encoding="utf-8")
        tmp.replace(CONSENT_FILE)
        return row

def booking_suggestion(preferences: dict, memory_obs: list) -> dict:
    day = (preferences.get("followup_days") or ["Saturday"])[0]
    slot = preferences.get("slot", "morning")
    lang = preferences.get("language", "en")
    extra = ""
    if any("missed" in (o.get("content", "").lower()) for o in memory_obs):
        extra = " (priority: missed last follow-up)"
    return {"suggested": f"{day} {slot}{extra}", "channel": preferences.get("channel", "sms"), "language": lang}
