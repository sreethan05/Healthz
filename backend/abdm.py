"""ABDM client: mock default, real sandbox handshake when credentials are set.

Sandbox flow (per NHA docs):
  1. POST {GATEWAY}/sessions              -> session token (clientId + clientSecret)
  2. POST {GATEWAY}/v1/consent/requests   -> consent request via HIE-CM (auth header)
  3. Patient approves in PHR app          -> signed artefact delivered on callback
  4. HIP validates artefact, releases FHIR R4 bundle to HIU over mTLS

Without ABDM_CLIENT_ID/ABDM_CLIENT_SECRET the client stays in mock mode and
says so explicitly — never pretends a real handshake happened.
"""
import os
import time
import uuid

import requests

from backend.config import ABDM_MODE, ABDM_SANDBOX

GATEWAY = os.getenv("ABDM_GATEWAY", "https://dev.abdm.gov.in/gateway")
CLIENT_ID = os.getenv("ABDM_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("ABDM_CLIENT_SECRET", "")
CALLBACK_URL = os.getenv("ABDM_CALLBACK_URL", "http://127.0.0.1:8000/abdm/callback")


def mode() -> str:
    if ABDM_MODE == "sandbox" and CLIENT_ID and CLIENT_SECRET:
        return "sandbox-live"
    return "mock"


def create_session() -> dict:
    """Step 1: gateway session. Credential-gated; refuses without creds."""
    if mode() != "sandbox-live":
        return {"ok": False, "mode": "mock",
                "reason": "Set ABDM_MODE=sandbox + ABDM_CLIENT_ID/ABDM_CLIENT_SECRET from sandbox.abdm.gov.in"}
    r = requests.post(f"{GATEWAY.rstrip('/')}/sessions",
                      json={"clientId": CLIENT_ID, "clientSecret": CLIENT_SECRET}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if "accessToken" not in body:
        return {"ok": False, "reason": "gateway did not return accessToken"}
    return {"ok": True, "access_token": body["accessToken"], "expires_in": body.get("expiresIn", 0)}


def request_consent(access_token: str, abha_address: str, hiu_id: str, hip_id: str,
                    purpose: str, hi_types: list, hours: int = 24) -> dict:
    """Step 2: consent request through HIE-CM."""
    now = int(time.time())
    payload = {
        "requestId": str(uuid.uuid4()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "consent": {
            "purpose": {"code": "CAREMGT", "text": purpose},
            "patient": {"id": abha_address},
            "hiu": {"id": hiu_id},
            "requester": {"name": "Cliniva", "identifier": {"value": hiu_id}},
            "hiTypes": hi_types,
            "permission": {
                "accessMode": "VIEW",
                "dateRange": {"from": "2024-01-01T00:00:00.000Z",
                              "to": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())},
                "dataEraseAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + hours * 3600)),
                "frequency": {"unit": "HOUR", "value": 1, "repeats": 1},
            },
        },
    }
    if mode() != "sandbox-live":
        return {"ok": True, "mode": "mock", "payload": payload,
                "note": "Mock: would POST /v1/consent/requests with Bearer token in sandbox."}
    r = requests.post(f"{GATEWAY.rstrip('/')}/v1/consent/requests", headers={
        "Authorization": f"Bearer {access_token}", "X-HIP-ID": hip_id,
    }, json=payload, timeout=15)
    r.raise_for_status()
    return {"ok": True, "mode": "sandbox-live", "gateway_response": r.json()}


def consent_artefact(patient_abha: str, hiu_id: str, hip_id: str, purpose: str, records: list, hours: int = 24) -> dict:
    now = int(time.time())
    m = mode()
    return {
        "artefact_id": str(uuid.uuid4())[:12],
        "mode": m,
        "patient_abha": patient_abha,
        "hiu": hiu_id,
        "hip": hip_id,
        "purpose": purpose,
        "records": records,
        "valid_from": now,
        "valid_until": now + hours * 3600,
        "status": "GRANTED-mock" if m == "mock" else "REQUESTED",
        "sandbox": ABDM_SANDBOX,
        "gateway": GATEWAY,
        "note": ("Mock artefact for demo. Sandbox path: create_session() -> request_consent() "
                 "-> PHR approval -> HIP validates signed artefact, releases FHIR bundle."),
    }


def hip_release_bundle(artefact: dict, fhir_bundle: dict) -> dict:
    if artefact.get("status", "").startswith("GRANTED") or mode() == "mock":
        return {"released": True, "bundle_id": fhir_bundle.get("id"), "via": f"HIP->HIU ({mode()}, mTLS in sandbox)"}
    return {"released": False, "reason": "Consent not granted. Complete PHR approval first."}
