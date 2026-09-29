"""Isolated module-level checks. Run: python test_e2e.py"""
import atexit
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from backend.abdm import consent_artefact, hip_release_bundle
from backend.audit import dpdp_notice, log, read_all
from backend.auth import login, valid_mci
from backend.audio_scribe import transcribe
from backend.consent import Consent, filter_memory_by_consent
from backend.fhir import fhir_bundle
from backend.ops import chain_log, memory_regression, retention_check, send_reminder, suggest_slots, verify_chain
from backend.rx_sign import sign_prescription, verify_prescription
from backend.safety import check_interactions, drug_info, find_alternatives, rules_source
from backend.scribe import apply_correction, draft_soap
from memory.hindsight_client import bank_id_for_patient, bank_summary, recall, reflect, retain
import backend.audit as audit_module
import backend.ops as ops_module
import backend.safety as safety_module
import memory.hindsight_client as memory_module

# Keep check runs away from real ignored patient, prescription, and audit data.
_test_data = tempfile.TemporaryDirectory(prefix="cliniva-checks-")
atexit.register(_test_data.cleanup)
_test_root = pathlib.Path(_test_data.name)
memory_module.LOCAL_DIR = _test_root / "banks"
memory_module.LOCAL_DIR.mkdir()
memory_module.HINDSIGHT_URL = ""
audit_module.AUDIT = _test_root / "audit.jsonl"
ops_module.DATA = _test_root
ops_module.CHAIN = _test_root / "audit_chain.jsonl"
# Keep these checks deterministic and offline.
safety_module.rxnorm_lookup = lambda name: {"rxcui": None, "resolved": name}
safety_module._openfda_label = lambda drug: ([], {"dailymed": safety_module.dailymed_link(drug)})

pid = "demo-001"
bank = bank_id_for_patient(pid)
n = 0

def ok(msg):
    global n
    n += 1
    print(f"{n} PASS {msg}")

s1 = check_interactions(["amoxicillin 500mg TDS x5d"], ["penicillin"])
assert s1["verdict"] == "CONFLICT" and s1.get("alternatives"), s1
ok(f"conflict + alternatives: {s1['alternatives'][0]['drug']}")

assert any("dailymed" in str(c).lower() for f in s1["findings"] for c in f.get("citations", [])), s1
ok("DailyMed citations present")

assert "curated" in rules_source() or "sqlite" in rules_source(), rules_source()
ok(f"safety rules source: {rules_source()}")

mem = reflect(bank, "fever throat pain penicillin rash")
d = draft_soap("Patient has fever and throat pain, penicillin allergy", mem)
assert d.get("icd_hints"), d
ok(f"scribe + ICD: {d['icd_hints'][0]['code']}")

upd = apply_correction(d, "Stop amoxicillin — penicillin allergy. Use azithromycin 500mg OD x3d.")
retain(bank, "Stop amoxicillin — penicillin allergy. Use azithromycin.", kind="correction", metadata={"actor": "doctor"})
assert any(m["id"] == "avoid-penicillin-class" for m in bank_summary(bank)["mental_models"])
ok("correction learned mental model")

signed = sign_prescription(pid, "dr-demo", "MCI-12345", ["azithromycin 500mg OD x3d"], {"assessment": "Pharyngitis", "plan": "Azithro"})
assert verify_prescription(signed["token"])["valid"] and not verify_prescription(signed["token"] + "x")["valid"]
ok(f"sign/verify/tamper: {signed['rx_id']}")

b = fhir_bundle(pid, "91-1234-5678-9012", "dr-demo", "MCI-12345", ["azithromycin 500mg OD x3d"], signed["rx_id"], signed["body"]["issued_at"])
assert b["resourceType"] == "Bundle" and b["entry"][0]["resource"]["date"].endswith("Z")
art = consent_artefact("91-1234-5678-9012", "cliniva-hiu", "demo-clinic", "OPD", ["Prescription"])
assert hip_release_bundle(art, b)["released"]
ok("FHIR + ABDM consent artefact release")

assert filter_memory_by_consent({"facts": [], "observations": [], "allergies": ["penicillin"]}, Consent(revoked=True)).get("locked")
ok("consent revoke locks")

scoped = filter_memory_by_consent({
    "facts": [
        {"content": "allergy fact", "metadata": {"scope": "allergies"}},
        {"content": "medication fact", "metadata": {"scope": "medications"}},
        {"content": "unclassified free text", "metadata": {}},
    ],
    "observations": [{"content": "may contain any scope"}],
    "mental_models": [{"content": "may contain any scope"}],
    "allergies": ["penicillin"],
}, Consent(history=True, allergies=False, medications=True))
assert scoped["allergies"] == [] and [f["content"] for f in scoped["facts"]] == ["medication fact"]
assert scoped["observations"] == [] and scoped["mental_models"] == []
ok("withheld scopes strip unclassified memory")

assert login("dr-demo", "demo123")["ok"] and valid_mci("MCI-12345") and not valid_mci("FAKE")
ok("auth login + MCI format check")

assert not transcribe(hint="throat", mic_consent=False)["ok"] and transcribe(hint="throat", mic_consent=True)["ok"]
ok("audio requires mic consent, stub transcribes")

chain_log("e2e", pid, "tester", {"ok": True})
assert verify_chain(20)["ok"] and retention_check("prescription", 0)["expired"] is True
ok("hash-chained audit + retention policy")

chain_before = ops_module.CHAIN.read_bytes()
try:
    ops_module.CHAIN.write_bytes(chain_before.replace(b'"event": "e2e"', b'"event": "bad"', 1))
    assert not verify_chain()["ok"]
    try:
        chain_log("must-not-append", pid, "tester")
        raise AssertionError("damaged audit chain accepted an append")
    except RuntimeError:
        pass
finally:
    ops_module.CHAIN.write_bytes(chain_before)
ok("audit chain detects tampering and refuses append")

assert suggest_slots({"followup_days": ["Saturday"]})["suggested"] and send_reminder("sms", "+91-1", "hi")["simulated"]
ok("booking slots + reminder")

assert memory_regression()["recall_hit"] and drug_info("azithromycin")["citations"]
ok("memory regression + drug-info grounded")

s3 = check_interactions(["paracetamol"], ["penicillin"])
assert s3["verdict"] in ("NO_CONFLICT", "INSUFFICIENT_DATA")
ok(f"safe case: {s3['verdict']}")

log("module_checks_complete", pid, "test_e2e")
assert len(read_all(5)) >= 1 and "revocation" in str(dpdp_notice()).lower()
ok("audit log + DPDP notice")

print(f"ALL {n} MODULE CHECKS PASSED (HTTP API policy is not covered)")
