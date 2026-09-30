"""Cliniva API — auth, memory, safety checks, signed prescriptions, consent, dispense."""
import json
import os
import pathlib
import sys
import time
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.abdm import consent_artefact, hip_release_bundle
from backend.audit import dpdp_notice, log, read_all
from backend.auth import login as auth_login, current_actor, valid_mci
from backend.audio_scribe import transcribe
from backend.config import DATA_RESIDENCY
from backend.consent import booking_suggestion, filter_memory_by_consent, get_consent, set_consent
from backend.fhir import fhir_bundle
from backend.ops import chain_log, retention_check, send_reminder, suggest_slots, verify_chain
from backend.rx_sign import sign_prescription, verify_prescription
from backend.safety import check_interactions, drug_info, find_alternatives, rules_source
from backend.scribe import apply_correction, draft_soap
from memory.hindsight_client import bank_id_for_patient, bank_summary, recall, reflect, retain

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RX_STORE = DATA / "rx_store.json"
RX_STORE_LOCK = threading.RLock()
RX_VALIDITY_DAYS = 30

app = FastAPI(title="Cliniva API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv("CLINIVA_CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if x.strip()], allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

FRONTEND = ROOT / "cliniva"
if FRONTEND.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND), html=True), name="app")


def _load_patients() -> dict:
    out = {}
    for f in sorted(DATA.glob("demo_patient*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
            out[p["patient_id"]] = p
        except Exception:
            pass
    return out


def _load_rx() -> dict:
    if RX_STORE.exists():
        try:
            store = json.loads(RX_STORE.read_text(encoding="utf-8"))
            if not isinstance(store, dict):
                raise ValueError("Rx store root must be an object")
            return store
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail="Prescription store is unreadable; refusing to replace it") from exc
    return {}


def _save_rx(store: dict):
    RX_STORE.parent.mkdir(parents=True, exist_ok=True)
    temp_path = RX_STORE.with_suffix(".tmp")
    temp_path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    temp_path.replace(RX_STORE)


def _actor(authorization: str | None, roles: list[str] | None = None) -> dict:
    return current_actor(authorization, roles)


def _patient_exists(patient_id: str) -> dict:
    patient = _load_patients().get(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Unknown patient")
    return patient


def _rx_status(rec: dict, verification: dict) -> str:
    if rec.get("dispensed_at"):
        return "DISPENSED"
    issued = verification.get("rx", {}).get("issued_at", 0)
    if issued and time.time() > issued + RX_VALIDITY_DAYS * 86400:
        return "EXPIRED"
    return "VALID"


class ConsultIn(BaseModel):
    patient_id: str = Field(default="demo-001", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    transcript: str = Field(min_length=1, max_length=30000)
    allergies: list[str] | None = Field(default=None, max_length=100)

class CorrectIn(BaseModel):
    patient_id: str = Field(default="demo-001", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    draft: dict
    correction: str = Field(min_length=1, max_length=10000)

class SignIn(BaseModel):
    patient_id: str = Field(default="demo-001", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    doctor_id: str = Field(default="dr-demo", min_length=1, max_length=100)
    doctor_reg: str = Field(default="MCI-12345", min_length=1, max_length=40)
    meds: list[str] = Field(default_factory=lambda: ["azithromycin 500mg OD x3d"], min_length=1, max_length=50)
    soap: dict = Field(default_factory=lambda: {"assessment": "Pharyngitis", "plan": "Azithro post-correction"})
    clinician_confirmed_insufficient_data: bool = False

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)

class ConsentUpdateIn(BaseModel):
    scopes: dict[str, bool] = Field(default_factory=dict)
    revoked: bool = False

class VerifyIn(BaseModel):
    token: str = Field(min_length=1, max_length=10000)

class DrugIn(BaseModel):
    drug: str = Field(min_length=1, max_length=200)

class MciCheckIn(BaseModel):
    reg: str = Field(default="", max_length=40)

class AudioIn(BaseModel):
    hint: str = Field(default="throat", max_length=100)
    mic_consent: bool = False

class BookingSlotsIn(BaseModel):
    patient_id: str = Field(default="demo-001", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    booked: list[str] = Field(default_factory=list, max_length=100)

class ReminderIn(BaseModel):
    channel: str = Field(default="sms", min_length=1, max_length=40)
    to: str = Field(default="+91-00000", min_length=1, max_length=100)
    text: str = Field(default="Follow-up reminder", min_length=1, max_length=1000)

class AbdmConsentIn(BaseModel):
    patient_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    hiu: str = Field(default="cliniva-hiu", min_length=1, max_length=100)
    hip: str = Field(default="demo-clinic", min_length=1, max_length=100)
    purpose: str = Field(default="OPD consultation", min_length=1, max_length=300)
    records: list[str] = Field(default_factory=lambda: ["Prescription", "OPConsult"], min_length=1, max_length=20)

class TamperIn(BaseModel):
    token: str = Field(min_length=1, max_length=10000)


@app.get("/health")
def health():
    return {"ok": True, "service": "cliniva"}


@app.get("/patients")
def patients(authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return [{"patient_id": p["patient_id"], "name": p.get("name", "")} for p in _load_patients().values()]


@app.get("/consent-notice")
def consent_notice():
    return dpdp_notice()


@app.get("/audit")
def audit(limit: int = 50, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return read_all(max(1, min(limit, 200)))


@app.post("/consult")
def consult(inp: ConsultIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["doctor"])
    p = _patient_exists(inp.patient_id)
    consent = get_consent(inp.patient_id)
    if consent.revoked or not consent.history or not consent.allergies or not consent.medications:
        raise HTTPException(status_code=403, detail="Active history, allergy, and medication consent required")
    allergies = [a["agent"] for a in p.get("allergies", [])]
    allergies.extend(a for a in (inp.allergies or []) if a.lower() not in {x.lower() for x in allergies})
    bank = bank_id_for_patient(inp.patient_id)
    mem = reflect(bank, inp.transcript)
    draft = draft_soap(inp.transcript, mem)
    safety = check_interactions(draft.get("draft_meds", []), allergies)
    log("consult", inp.patient_id, actor.get("sub", "doctor"), {"verdict": safety.get("verdict"), "severity": safety.get("severity")})
    return {"bank": bank, "patient": {"patient_id": inp.patient_id, "allergies": allergies},
            "memory": mem, "draft": draft, "safety": safety}


@app.post("/correct")
def correct(inp: CorrectIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["doctor"])
    _patient_exists(inp.patient_id)
    consent = get_consent(inp.patient_id)
    if consent.revoked or not consent.history or not consent.allergies or not consent.medications:
        raise HTTPException(status_code=403, detail="Active history, allergy, and medication consent required")
    bank = bank_id_for_patient(inp.patient_id)
    updated = apply_correction(inp.draft, inp.correction)
    retain(bank, inp.correction, kind="correction", metadata={"actor": "doctor"})
    pmap = _load_patients()
    p = pmap.get(inp.patient_id, {})
    allergies = [a["agent"] for a in p.get("allergies", [])] or ["penicillin"]
    safety2 = check_interactions(updated.get("draft_meds", []), allergies)
    mem = recall(bank, "followup preferences")
    booking = booking_suggestion(p.get("preferences", {"followup_days": ["Saturday"], "slot": "morning"}), mem.get("observations", []))
    summary = bank_summary(bank)
    # Keep free-text clinical content out of the broadly readable audit log.
    log("correction", inp.patient_id, actor.get("sub", "doctor"), {"correction_length": len(inp.correction), "recheck": safety2.get("verdict")})
    return {"updated": updated, "safety_recheck": safety2, "booking": booking,
            "memory": filter_memory_by_consent(mem, consent),
            "learning": filter_memory_by_consent(summary, consent)}


@app.post("/sign")
def sign(inp: SignIn, request: Request, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["doctor"])
    _patient_exists(inp.patient_id)
    consent = get_consent(inp.patient_id)
    if consent.revoked or not consent.history or not consent.allergies or not consent.medications:
        raise HTTPException(status_code=403, detail="Active patient consent required before signing")
    if inp.doctor_id != actor.get("sub") or inp.doctor_reg != actor.get("reg"):
        raise HTTPException(status_code=403, detail="Prescription identity must match the authenticated doctor")
    if not valid_mci(actor.get("reg", "")):
        raise HTTPException(status_code=403, detail="Authenticated clinician registration is invalid")
    patient = _load_patients()[inp.patient_id]
    allergies = [a["agent"] for a in patient.get("allergies", [])]
    safety = check_interactions(inp.meds, allergies)
    if safety.get("verdict") == "CONFLICT":
        raise HTTPException(status_code=409, detail={"message": "Unsafe prescription blocked", "safety": safety})
    if safety.get("verdict") != "NO_CONFLICT" and not inp.clinician_confirmed_insufficient_data:
        raise HTTPException(status_code=409, detail={
            "message": "Interaction screening is incomplete. Review the full regimen and explicitly confirm before signing.",
            "safety": safety,
        })
    env_verify = os.getenv("CLINIVA_VERIFY_BASE", "").strip()
    verify_base = env_verify or f"{str(request.base_url).rstrip('/')}/app/#/rx"
    signed = sign_prescription(inp.patient_id, actor["sub"], actor["reg"], inp.meds, inp.soap, verify_base=verify_base)
    with RX_STORE_LOCK:
        store = _load_rx()
        store[signed["rx_id"]] = {"token": signed["token"], "body": signed["body"], "hash": signed["hash"],
                                  "qr_payload": signed["qr_payload"], "qr_png_base64": signed["qr_png_base64"]}
        _save_rx(store)
    # The prescription record contains the clinical details; the audit stores only an identifier and count.
    log("rx_sign", inp.patient_id, actor.get("sub", "doctor"), {
        "rx_id": signed["rx_id"], "medication_count": len(inp.meds),
        "safety_verdict": safety.get("verdict"),
        "clinician_confirmed_insufficient_data": inp.clinician_confirmed_insufficient_data,
    })
    return signed


@app.post("/verify")
def verify(token: VerifyIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["doctor", "pharmacist"])
    v = verify_prescription(token.token)
    patient_id = v.get("rx", {}).get("patient_id")
    if v.get("valid"):
        consent = get_consent(patient_id or "")
        if not patient_id or consent.revoked or not consent.medications:
            v = {"valid": False, "reason": "Patient medication consent is revoked or unavailable"}
    log("rx_verify", v.get("rx", {}).get("patient_id", ""), actor.get("sub", "unknown"), {"valid": v.get("valid"), "role": actor.get("role")})
    return v


@app.get("/timeline/{patient_id}")
def timeline(patient_id: str, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["doctor"])
    p = _patient_exists(patient_id)
    c = get_consent(patient_id)
    if c.revoked:
        log("timeline_access", patient_id, actor.get("sub", "doctor"), {"revoked": True})
        return filter_memory_by_consent({}, c)
    bank = bank_id_for_patient(patient_id)
    mem = recall(bank, "patient history allergies meds")
    base = {"facts": mem.get("facts", []), "observations": mem.get("observations", []),
            "mental_models": mem.get("mental_models", []),
            "allergies": [a["agent"] for a in p.get("allergies", [])],
            "patient": {k: p.get(k) for k in ("patient_id", "name", "age", "conditions", "current_meds", "preferences")}}
    log("timeline_access", patient_id, actor.get("sub", "doctor"), {"revoked": c.revoked})
    return filter_memory_by_consent(base, c)


@app.get("/memory/{patient_id}")
def memory_view(patient_id: str, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    _patient_exists(patient_id)
    consent = get_consent(patient_id)
    if consent.revoked:
        raise HTTPException(status_code=403, detail="Consent revoked")
    return filter_memory_by_consent(bank_summary(bank_id_for_patient(patient_id)), consent)


@app.post("/alternatives")
def alternatives(d: DrugIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return {"drug": d.drug, "alternatives": find_alternatives(d.drug)}


@app.post("/drug-info")
def drug_info_ep(d: DrugIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor", "pharmacist"])
    return drug_info(d.drug)


@app.get("/rx/{rx_id}")
def get_rx(rx_id: str, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor", "pharmacist"])
    store = _load_rx()
    if rx_id not in store:
        return {"found": False}
    verification = verify_prescription(store[rx_id]["token"])
    pid = verification.get("rx", {}).get("patient_id")
    if not verification.get("valid") or not pid or get_consent(pid).revoked or not get_consent(pid).medications:
        raise HTTPException(status_code=403, detail="Prescription access requires active patient medication consent")
    rec = store[rx_id]
    out = {"found": True, "stored": {k: rec.get(k) for k in ("body", "hash", "qr_payload", "qr_png_base64", "dispensed_at")}, "verification": verification}
    return out


@app.get("/fhir-rx/{rx_id}")
def fhir_rx(rx_id: str, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor", "pharmacist"])
    store = _load_rx()
    rec = store.get(rx_id)
    if not rec:
        return {"found": False}
    v = verify_prescription(rec["token"])
    if not v.get("valid"):
        return {"found": True, "valid": False}
    rx = v["rx"]
    consent = get_consent(rx.get("patient_id", ""))
    if consent.revoked or not consent.medications:
        raise HTTPException(status_code=403, detail="FHIR export requires active patient medication consent")
    pmap = _load_patients()
    p = pmap.get(rx.get("patient_id"), {})
    bundle = fhir_bundle(rx.get("patient_id"), p.get("abha_id", ""), rx.get("doctor_id"), rx.get("doctor_reg"), rx.get("meds", []), rx_id, rx.get("issued_at", 0))
    return {"found": True, "valid": True, "fhir_bundle": bundle}


@app.post("/tamper-demo")
def tamper_demo(d: TamperIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor", "pharmacist"])
    # Flip one character of a valid token to demonstrate tamper detection.
    tok = d.token
    bad = tok[:-1] + ("a" if tok[-1] != "a" else "b")
    original = verify_prescription(tok)
    rx = original.get("rx", {})
    if original.get("valid"):
        consent = get_consent(rx.get("patient_id", ""))
        if consent.revoked or not consent.medications:
            original = {"valid": False, "reason": "Patient medication consent is revoked or unavailable"}
    return {"original": original, "tampered": verify_prescription(bad)}


@app.get("/verify-page/{rx_id}", response_class=HTMLResponse)
def verify_page(rx_id: str):
    from html import escape
    store = _load_rx()
    rec = store.get(rx_id)
    if not rec:
        return f"<h2>Rx {escape(str(rx_id))} not found</h2>"
    v = verify_prescription(rec["token"])
    pid = v.get("rx", {}).get("patient_id")
    if not v.get("valid") or not pid or get_consent(pid).revoked or not get_consent(pid).medications:
        return "<h2>Prescription unavailable: active patient medication consent is required.</h2>"
    status = _rx_status(rec, v)
    rx = v.get("rx", {})
    rx_id, patient_id = escape(str(rx_id)), escape(str(rx.get("patient_id", "")))
    doctor_id, doctor_reg = escape(str(rx.get("doctor_id", ""))), escape(str(rx.get("doctor_reg", "")))
    meds = escape(", ".join(map(str, rx.get("meds", []))))
    digest = escape(str(v.get("hash", "")))
    return f"""<html><body style="font-family:sans-serif;max-width:680px;margin:40px auto">
    <h2>Cliniva e-Prescription: {status}</h2>
    <p><b>Rx:</b> {rx_id} | <b>Patient:</b> {patient_id} | <b>Doctor:</b> {doctor_id} ({doctor_reg})</p>
    <p><b>Meds:</b> {meds}</p>
    <p><b>Hash:</b> <code>{digest}</code></p>
    <p>FHIR export requires an authenticated clinician or pharmacist session in the app.</p>
    <p style="color:#666">PCI format / FHIR PrescriptionRecord demo. Supports, does not replace clinical judgment.</p>
    </body></html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    return '<html><body style="font-family:sans-serif;margin:40px"><h2>Cliniva API running</h2><p>Open <a href="/app/">/app/</a> for the Cliniva application.</p></body></html>'


# ---------- Patient self-service ----------

@app.get("/me")
def me(authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["patient"])
    pid = actor.get("patient_id") or ""
    p = _load_patients().get(pid)
    if not p:
        raise HTTPException(status_code=404, detail="No patient record linked to this account")
    consent = get_consent(pid)
    return {
        "patient_id": pid,
        "name": p.get("name", ""),
        "age": p.get("age"),
        "conditions": p.get("conditions", []),
        "current_meds": p.get("current_meds", []),
        "allergies": [a.get("agent") for a in p.get("allergies", [])],
        "preferences": p.get("preferences", {}),
        "consent": {"history": consent.history, "allergies": consent.allergies,
                    "medications": consent.medications, "revoked": consent.revoked},
    }


@app.post("/me/consent")
def me_consent(d: ConsentUpdateIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["patient"])
    pid = actor.get("patient_id") or ""
    if not _load_patients().get(pid):
        raise HTTPException(status_code=404, detail="No patient record linked to this account")
    saved = set_consent(pid, d.scopes, revoked=d.revoked)
    log("consent_update", pid, actor.get("sub", "patient"),
        {"revoked": saved["revoked"], "scopes": {k: saved[k] for k in ("history", "allergies", "medications")}})
    return saved


@app.get("/me/rx")
def me_rx(authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["patient"])
    pid = actor.get("patient_id") or ""
    consent = get_consent(pid)
    if consent.revoked or not consent.medications:
        raise HTTPException(status_code=403, detail="Medication consent is required to view prescriptions")
    out = []
    with RX_STORE_LOCK:
        store = _load_rx()
        for rx_id, rec in store.items():
            v = verify_prescription(rec["token"])
            if not v.get("valid") or v.get("rx", {}).get("patient_id") != pid:
                continue
            rx = v["rx"]
            out.append({
                "rx_id": rx_id,
                "meds": rx.get("meds", []),
                "doctor_id": rx.get("doctor_id"),
                "doctor_reg": rx.get("doctor_reg"),
                "soap_summary": rx.get("soap_summary", {}),
                "issued_at": rx.get("issued_at", 0),
                "expires_at": rx.get("issued_at", 0) + RX_VALIDITY_DAYS * 86400,
                "hash": rec["hash"],
                "qr_payload": rec.get("qr_payload", ""),
                "qr_png_base64": rec.get("qr_png_base64", ""),
                "status": _rx_status(rec, v),
            })
    out.sort(key=lambda r: r["issued_at"], reverse=True)
    return out


# ---------- Doctor prescription history ----------

@app.get("/doctor/rx")
def doctor_rx(authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    pmap = _load_patients()
    out = []
    with RX_STORE_LOCK:
        store = _load_rx()
        for rx_id, rec in store.items():
            v = verify_prescription(rec["token"])
            if not v.get("valid"):
                continue
            rx = v["rx"]
            pid = rx.get("patient_id", "")
            consent = get_consent(pid)
            if consent.revoked or not consent.medications:
                continue
            out.append({
                "rx_id": rx_id,
                "patient_id": pid,
                "patient_name": (pmap.get(pid, {}) or {}).get("name", ""),
                "meds": rx.get("meds", []),
                "doctor_id": rx.get("doctor_id"),
                "issued_at": rx.get("issued_at", 0),
                "expires_at": rx.get("issued_at", 0) + RX_VALIDITY_DAYS * 86400,
                "status": _rx_status(rec, v),
            })
    out.sort(key=lambda r: r["issued_at"], reverse=True)
    return out


# ---------- Public pharmacy verification + dispense ----------

@app.get("/public/rx/{rx_id}")
def public_rx(rx_id: str, h: str = ""):
    with RX_STORE_LOCK:
        store = _load_rx()
        rec = store.get(rx_id)
    if not rec:
        return {"found": False}
    v = verify_prescription(rec["token"])
    rx = v.get("rx", {})
    pid = rx.get("patient_id", "")
    if not v.get("valid") or not pid:
        log("rx_public_view", pid, "anonymous", {"valid": False, "rx_id": rx_id})
        return {"found": True, "valid": False, "reason": "Signature verification failed — prescription cannot be trusted"}
    consent = get_consent(pid)
    if consent.revoked or not consent.medications:
        log("rx_public_view", pid, "anonymous", {"valid": False, "rx_id": rx_id})
        return {"found": True, "valid": False, "reason": "Patient medication consent is revoked or unavailable"}
    if not h or not rec["hash"].startswith(h):
        log("rx_public_view", pid, "anonymous", {"valid": False, "reason": "hash mismatch", "rx_id": rx_id})
        return {"found": True, "valid": False, "reason": "Verification code mismatch — possible tampering. Do not dispense."}
    status = _rx_status(rec, v)
    log("rx_public_view", pid, "anonymous", {"valid": True, "rx_id": rx_id, "status": status})
    return {"found": True, "valid": True, "rx_id": rx_id,
            "meds": rx.get("meds", []),
            "doctor_id": rx.get("doctor_id"), "doctor_reg": rx.get("doctor_reg"),
            "issued_at": rx.get("issued_at", 0),
            "expires_at": rx.get("issued_at", 0) + RX_VALIDITY_DAYS * 86400,
            "status": status}


@app.post("/dispense/{rx_id}")
def dispense(rx_id: str, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["pharmacist"])
    with RX_STORE_LOCK:
        store = _load_rx()
        rec = store.get(rx_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Unknown prescription")
        v = verify_prescription(rec["token"])
        if not v.get("valid"):
            raise HTTPException(status_code=409, detail="Prescription fails verification — cannot dispense")
        pid = v.get("rx", {}).get("patient_id", "")
        consent = get_consent(pid)
        if consent.revoked or not consent.medications:
            raise HTTPException(status_code=403, detail="Patient medication consent is revoked")
        if rec.get("dispensed_at"):
            out = {"rx_id": rx_id, "status": "DISPENSED", "dispensed_at": rec["dispensed_at"]}
        else:
            if time.time() > v.get("rx", {}).get("issued_at", 0) + RX_VALIDITY_DAYS * 86400:
                raise HTTPException(status_code=409, detail="Prescription expired — cannot dispense")
            rec["dispensed_at"] = int(time.time())
            store[rx_id] = rec
            _save_rx(store)
            out = {"rx_id": rx_id, "status": "DISPENSED", "dispensed_at": rec["dispensed_at"]}
    log("rx_dispense", pid, actor.get("sub", "pharmacist"), {"rx_id": rx_id})
    return out


# Rate limits are process-local safeguards.
_HITS: dict = {}
_HITS_LOCK = threading.Lock()


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    if request.url.path in ("/consult", "/sign", "/auth/login"):
        ip = request.client.host if request.client else "local"
        now = time.time()
        with _HITS_LOCK:
            # Bound memory use when the service is reached from many distinct addresses.
            if len(_HITS) >= 4096 and ip not in _HITS:
                cutoff = now - 60
                for key in list(_HITS):
                    recent = [hit for hit in _HITS[key] if hit > cutoff]
                    if recent:
                        _HITS[key] = recent
                    else:
                        del _HITS[key]
            if len(_HITS) >= 4096 and ip not in _HITS:
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "rate limited. Retry later."}, status_code=429)
            bucket = _HITS.setdefault(ip, [])
            while bucket and now - bucket[0] > 60:
                bucket.pop(0)
            if len(bucket) >= (20 if request.url.path == "/auth/login" else 60):
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": "rate limited. Retry later."}, status_code=429)
            bucket.append(now)
    return await call_next(request)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


@app.get("/ops/health")
def ops_health(authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return {"ok": True, "residency": DATA_RESIDENCY, "rules": rules_source(), "chain": verify_chain()}


@app.post("/auth/login")
def auth_login_ep(d: LoginIn):
    result = auth_login(d.username, d.password)
    if not result.get("ok"):
        raise HTTPException(status_code=401, detail=result.get("reason", "bad credentials"))
    return result


@app.post("/auth/check-mci")
def check_mci(d: MciCheckIn):
    return {"reg": d.reg, "valid_format": valid_mci(d.reg)}


@app.post("/consent/{patient_id}")
def update_patient_consent(patient_id: str, d: ConsentUpdateIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["patient"])
    _patient_exists(patient_id)
    if actor.get("patient_id") != patient_id:
        raise HTTPException(status_code=403, detail="Patient account cannot change another patient's consent")
    saved = set_consent(patient_id, d.scopes, revoked=d.revoked)
    log("consent_update", patient_id, actor.get("sub", "patient"), {"revoked": saved["revoked"], "scopes": {k: saved[k] for k in ("history", "allergies", "medications")}})
    return saved


@app.post("/abdm/consent")
def abdm_consent(d: AbdmConsentIn, authorization: str | None = Header(default=None)):
    actor = _actor(authorization, ["patient"])
    patient_id = d.patient_id
    p = _patient_exists(patient_id)
    if actor.get("patient_id") != patient_id:
        raise HTTPException(status_code=403, detail="Patient account cannot authorize another patient's record")
    consent = get_consent(patient_id)
    if consent.revoked or not consent.history or not consent.allergies or not consent.medications:
        raise HTTPException(status_code=403, detail="Active consent required")
    art = consent_artefact(p.get("abha_id", ""), d.hiu, d.hip, d.purpose, d.records)
    chain_log("abdm_consent", patient_id, actor.get("sub", "patient"), {"artefact": art["artefact_id"]})
    return art


@app.post("/audio/transcribe")
def audio_transcribe(d: AudioIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return transcribe(d.hint, d.hint, d.mic_consent)


@app.post("/booking/slots")
def booking_slots(d: BookingSlotsIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    patient_id = d.patient_id
    _patient_exists(patient_id)
    slot_consent = get_consent(patient_id)
    if slot_consent.revoked or not slot_consent.history:
        raise HTTPException(status_code=403, detail="Active history consent required")
    pmap = _load_patients()
    prefs = pmap.get(patient_id, {}).get("preferences", {})
    return suggest_slots(prefs, d.booked)


@app.post("/booking/remind")
def booking_remind(d: ReminderIn, authorization: str | None = Header(default=None)):
    _actor(authorization, ["doctor"])
    return send_reminder(d.channel, d.to, d.text)
