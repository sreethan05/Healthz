"""ABDM FHIR R4 minimal PrescriptionRecord bundle builder (Composition + MedicationRequest)."""
from datetime import datetime, timezone


def fhir_bundle(patient_id: str, abha: str, doctor_id: str, doctor_reg: str, meds: list, rx_id: str, issued_ts: int) -> dict:
    issued_at = datetime.fromtimestamp(int(issued_ts), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    med_reqs = []
    entries = [
        {"resourceType": "Patient", "id": patient_id, "identifier": [{"system": "https://abdm.gov.in/abha", "value": abha}]},
        {"resourceType": "Practitioner", "id": doctor_id, "identifier": [{"system": "https://mciindia.org/reg", "value": doctor_reg}]},
    ]
    for i, m in enumerate(meds):
        mid = f"medreq-{rx_id}-{i}"
        mr = {
            "resourceType": "MedicationRequest",
            "id": mid,
            "status": "active",
            "intent": "order",
            "medicationCodeableConcept": {"text": m},
            "subject": {"reference": f"Patient/{patient_id}"},
            "requester": {"reference": f"Practitioner/{doctor_id}"},
        }
        med_reqs.append(mr)
        entries.append(mr)
    comp = {
        "resourceType": "Composition",
        "id": f"rx-{rx_id}",
        "status": "final",
        "type": {"coding": [{"system": "http://snomed.info/sct", "code": "440654001", "display": "Prescription record"}]},
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": issued_at,
        "author": [{"reference": f"Practitioner/{doctor_id}"}],
        "title": "PrescriptionRecord (ABDM FHIR R4 demo)",
        "section": [{"title": "Medications", "entry": [{"reference": f"MedicationRequest/{m['id']}"} for m in med_reqs]}],
    }
    entries.insert(0, comp)
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "id": f"bundle-{rx_id}",
        "entry": [{"resource": e} for e in entries],
    }
