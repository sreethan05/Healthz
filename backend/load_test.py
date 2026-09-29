"""Chaos run: 60 concurrent mixed requests, zero 500s allowed. Run: python backend/load_test.py"""
import pathlib
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
CONFLICT_TX = "fever and throat pain, penicillin rash allergy"


def _auth():
    d = client.post("/auth/login", json={"username": "dr-demo", "password": "demo123"}).json()
    doctor = {"Authorization": f"Bearer {d['token']}"}
    p = client.post("/auth/login", json={"username": "patient-demo", "password": "demo123"}).json()
    patient = {"Authorization": f"Bearer {p['token']}"}
    r = client.post("/consent/demo-001", headers=patient,
                    json={"scopes": {"history": True, "allergies": True, "medications": True}, "revoked": False})
    assert r.status_code == 200, r.text
    return doctor


HEADERS = _auth()


def work(i: int) -> tuple:
    t0 = time.time()
    try:
        kind = i % 6
        if kind in (0, 1, 2):
            r = client.post("/consult", headers=HEADERS, json={"patient_id": "demo-001", "transcript": CONFLICT_TX})
            ok = r.status_code == 200 and r.json()["safety"]["verdict"] == "CONFLICT"
        elif kind in (3, 4):
            r = client.get("/timeline/demo-001", headers=HEADERS)
            ok = r.status_code == 200
        else:
            r = client.post("/sign", headers=HEADERS, json={"patient_id": "demo-001", "doctor_id": "dr-demo",
                                           "doctor_reg": "MCI-12345", "meds": ["azithromycin 500mg"],
                                           "soap": {"assessment": "load", "plan": "load"},
                                           "clinician_confirmed_insufficient_data": True})
            j = r.json()
            v = client.post("/verify", headers=HEADERS, json={"token": j["token"]}).json()
            ok = r.status_code == 200 and v.get("valid") is True
        return (ok, time.time() - t0, None)
    except Exception as e:  # noqa: BLE001 — chaos run must record, not crash
        return (False, time.time() - t0, repr(e)[:200])


def main(n: int = 60):
    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(work, range(n)))
    oks = [r for r in results if r[0]]
    lats = sorted(r[1] for r in results)
    print(f"requests={n} ok={len(oks)} failed={n - len(oks)}")
    print(f"p50={statistics.median(lats):.2f}s p95={lats[int(0.95 * n) - 1]:.2f}s max={lats[-1]:.2f}s")
    for ok, lat, err in results:
        if not ok:
            print("FAIL:", err)
    if len(oks) != n:
        sys.exit(1)
    print("CHAOS RUN CLEAN — no 500s, all verdicts/signatures correct")


if __name__ == "__main__":
    main()
