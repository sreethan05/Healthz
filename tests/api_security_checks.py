"""HTTP-level checks for authorization, consent, validation, and prescription access."""
import json
import pathlib
import shutil

import pytest
from fastapi.testclient import TestClient

from backend import audit as audit_module
from backend import audio_scribe as audio_module
from backend import consent as consent_module
from backend import main as api
from backend import ops as ops_module
from backend import safety as safety_module
from memory import hindsight_client

PROJECT = pathlib.Path(__file__).resolve().parents[1]
ALL_SCOPES = {"history": True, "allergies": True, "medications": True}


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for filename in ("demo_patient.json", "demo_patient_2.json"):
        shutil.copy2(PROJECT / "data" / filename, data_dir / filename)

    monkeypatch.setattr(api, "DATA", data_dir)
    monkeypatch.setattr(api, "RX_STORE", data_dir / "rx_store.json")
    monkeypatch.setattr(audit_module, "AUDIT", data_dir / "audit.jsonl")
    monkeypatch.setattr(consent_module, "CONSENT_FILE", data_dir / "consents.json")
    monkeypatch.setattr(ops_module, "DATA", data_dir)
    monkeypatch.setattr(ops_module, "CHAIN", data_dir / "audit_chain.jsonl")
    monkeypatch.setattr(hindsight_client, "LOCAL_DIR", data_dir / "banks")
    hindsight_client.LOCAL_DIR.mkdir()
    monkeypatch.setattr(hindsight_client, "HINDSIGHT_URL", "")
    monkeypatch.setattr(safety_module, "rxnorm_lookup", lambda name: {"rxcui": None, "resolved": name})
    monkeypatch.setattr(safety_module, "_openfda_label", lambda drug: ([], {"dailymed": safety_module.dailymed_link(drug)}))
    monkeypatch.setattr(api, "check_interactions", lambda meds, allergies: {"verdict": "NO_CONFLICT", "findings": []})
    api._HITS.clear()
    return TestClient(api.app)


def login(client, username):
    response = client.post("/auth/login", json={"username": username, "password": "demo123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def grant(client, patient_id="demo-001", scopes=None, revoked=False):
    patient_user = "patient-demo-2" if patient_id == "demo-002" else "patient-demo"
    headers = login(client, patient_user)
    return client.post(
        f"/consent/{patient_id}",
        headers=headers,
        json={"scopes": scopes or ALL_SCOPES, "revoked": revoked},
    )


def test_patient_list_requires_doctor_and_returns_minimal_records(client):
    assert client.get("/patients").status_code == 401
    patient_headers = login(client, "patient-demo")
    assert client.get("/patients", headers=patient_headers).status_code == 403

    response = client.get("/patients", headers=login(client, "dr-demo"))
    assert response.status_code == 200
    assert response.json()[0].keys() == {"patient_id", "name"}
    assert "allergies" not in json.dumps(response.json())
    assert "past_prescriptions" not in json.dumps(response.json())


def test_consent_defaults_closed_and_revocation_removes_timeline_data(client):
    doctor = login(client, "dr-demo")
    assert client.get("/timeline/demo-001", headers=doctor).json()["locked"] is True
    assert client.post("/consult", headers=doctor, json={"patient_id": "demo-001", "transcript": "throat pain"}).status_code == 403

    assert grant(client).status_code == 200
    timeline = client.get("/timeline/demo-001", headers=doctor)
    assert timeline.status_code == 200
    assert "penicillin" in json.dumps(timeline.json()).lower()

    assert grant(client, revoked=True).status_code == 200
    locked = client.get("/timeline/demo-001", headers=doctor).json()
    assert locked == {"locked": True, "lock_reason": "Consent revoked — timeline locked. Re-consent required."}
    assert client.post("/consult", headers=doctor, json={"patient_id": "demo-001", "transcript": "throat pain"}).status_code == 403


def test_patient_account_cannot_change_another_patient_consent(client):
    headers = login(client, "patient-demo")
    response = client.post("/consent/demo-002", headers=headers, json={"scopes": ALL_SCOPES})
    assert response.status_code == 403


def test_sign_requires_consent_and_blocks_detected_conflicts(client, monkeypatch):
    doctor = login(client, "dr-demo")
    payload = {"patient_id": "demo-001", "doctor_id": "dr-demo", "doctor_reg": "MCI-12345", "meds": ["amoxicillin"], "soap": {}}
    assert client.post("/sign", json=payload).status_code == 401
    assert client.post("/sign", headers=doctor, json=payload).status_code == 403

    grant(client)
    monkeypatch.setattr(api, "check_interactions", lambda meds, allergies: {"verdict": "CONFLICT", "findings": [{"severity": "major"}]})
    blocked = client.post("/sign", headers=doctor, json=payload)
    assert blocked.status_code == 409
    assert not (api.RX_STORE.exists() and json.loads(api.RX_STORE.read_text()))


def test_sign_requires_explicit_review_when_screening_is_incomplete(client, monkeypatch):
    doctor = login(client, "dr-demo")
    grant(client)
    monkeypatch.setattr(api, "check_interactions", lambda meds, allergies: {"verdict": "INSUFFICIENT_DATA", "findings": []})
    payload = {"patient_id": "demo-001", "doctor_id": "dr-demo", "doctor_reg": "MCI-12345", "meds": ["unresolved medicine"], "soap": {}}
    assert client.post("/sign", headers=doctor, json=payload).status_code == 409
    assert not (api.RX_STORE.exists() and json.loads(api.RX_STORE.read_text()))
    payload["clinician_confirmed_insufficient_data"] = True
    assert client.post("/sign", headers=doctor, json=payload).status_code == 200


def test_signed_prescription_access_stops_after_consent_revocation(client):
    doctor = login(client, "dr-demo")
    grant(client, patient_id="demo-002")
    payload = {"patient_id": "demo-002", "doctor_id": "dr-demo", "doctor_reg": "MCI-12345", "meds": ["paracetamol"], "soap": {}}
    signed = client.post("/sign", headers=doctor, json=payload)
    assert signed.status_code == 200
    rx_id = signed.json()["rx_id"]

    assert grant(client, patient_id="demo-002", revoked=True).status_code == 200
    assert client.get(f"/rx/{rx_id}", headers=doctor).status_code == 403
    assert client.get(f"/fhir-rx/{rx_id}", headers=doctor).status_code == 403
    assert "unavailable" in client.get(f"/verify-page/{rx_id}").text.lower()


def test_malformed_inputs_are_rejected_and_html_is_escaped(client):
    doctor = login(client, "dr-demo")
    malformed = client.post("/sign", headers=doctor, json={"patient_id": "../demo-001", "meds": []})
    assert malformed.status_code == 422
    page = client.get("/verify-page/%3Csvg%20onload%3Dalert(1)%3E")
    assert page.status_code == 200
    assert "<svg" not in page.text


def test_only_live_allowed_patient_ids_can_map_to_memory_banks():
    with pytest.raises(ValueError):
        hindsight_client.bank_id_for_patient("../outside")
    assert hindsight_client.bank_id_for_patient("demo-001") == "cliniva-patient-demo-001"


def test_malformed_consent_store_fails_closed(tmp_path, monkeypatch):
    store = tmp_path / "consents.json"
    store.write_text(json.dumps({"demo-001": None}), encoding="utf-8")
    monkeypatch.setattr(consent_module, "CONSENT_FILE", store)
    consent = consent_module.get_consent("demo-001")
    assert consent.revoked is True
    assert consent.history is consent.allergies is consent.medications is False


def test_truthy_strings_cannot_grant_consent(tmp_path, monkeypatch):
    store = tmp_path / "consents.json"
    store.write_text(json.dumps({"demo-001": {"history": "false", "allergies": 1, "medications": True, "revoked": "false"}}), encoding="utf-8")
    monkeypatch.setattr(consent_module, "CONSENT_FILE", store)
    consent = consent_module.get_consent("demo-001")
    assert consent.revoked is True
    assert consent.history is False
    assert consent.allergies is False
    assert consent.medications is True


def test_audit_does_not_copy_prescription_details(client):
    doctor = login(client, "dr-demo")
    grant(client)
    payload = {"patient_id": "demo-001", "doctor_id": "dr-demo", "doctor_reg": "MCI-12345", "meds": ["sensitive-medication-name"], "soap": {}}
    assert client.post("/sign", headers=doctor, json=payload).status_code == 200
    audit_text = audit_module.AUDIT.read_text(encoding="utf-8")
    assert "sensitive-medication-name" not in audit_text
    assert '"medication_count": 1' in audit_text


def test_audio_upload_uses_generated_safe_name_and_size_limit(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(audio_module, "UPLOAD_DIR", upload_dir)
    saved = pathlib.Path(audio_module.save_upload(b"audio", "../../outside.webm"))
    assert saved.parent == upload_dir
    assert saved.name.endswith(".webm")
    assert saved.read_bytes() == b"audio"
    with pytest.raises(ValueError):
        audio_module.save_upload(b"x" * (25 * 1024 * 1024 + 1), "large.webm")


def test_rate_limiter_discards_stale_ip_buckets(client):
    api._HITS.clear()
    api._HITS.update({f"old-{i}": [0.0] for i in range(4096)})
    assert client.post("/auth/login", json={"username": "dr-demo", "password": "demo123"}).status_code == 200
    assert len(api._HITS) == 1


def test_label_snippet_alone_never_claims_a_clean_interaction_screen(monkeypatch):
    monkeypatch.setattr(safety_module, "rxnorm_lookup", lambda name: {"rxcui": None, "resolved": name})
    monkeypatch.setattr(safety_module, "_openfda_label", lambda drug: (["warnings: sample label text"], {"dailymed": "https://example.test/label"}))
    result = safety_module.check_interactions(["unknown medicine"], [])
    assert result["verdict"] == "INSUFFICIENT_DATA"
