"""Seed all demo patients. Run: python backend/seed.py"""
import json
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from memory.hindsight_client import bank_id_for_patient, retain

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

parser = argparse.ArgumentParser(description="Seed demo patient memory without deleting existing data.")
parser.add_argument("--reset", action="store_true", help="replace only the two demo patient memory files")
args = parser.parse_args()

banks_dir = DATA / "banks"
banks_dir.mkdir(parents=True, exist_ok=True)

for fname in ["demo_patient.json", "demo_patient_2.json"]:
    f = DATA / fname
    if not f.exists():
        continue
    p = json.loads(f.read_text(encoding="utf-8"))
    bank = bank_id_for_patient(p["patient_id"])
    bank_file = banks_dir / f"{bank}.json"
    if args.reset and bank_file.exists():
        bank_file.unlink()
    elif bank_file.exists():
        print("Keeping existing", bank, "(use --reset to replace this demo bank)")
        continue
    print("Seeding", bank, "-", p["name"])
    for a in p.get("allergies", []):
        retain(bank, f"Allergy: {a['agent']} — {a['reaction']} (source: {a.get('source','record')})", kind="world_fact", metadata={"scope": "allergies"})
    if not p.get("allergies"):
        retain(bank, "No known drug allergies (NKDA) per intake.", kind="world_fact", metadata={"scope": "allergies"})
    retain(bank, f"Conditions: {', '.join(p.get('conditions', []))}. Current meds: {', '.join(p.get('current_meds', []))}", kind="world_fact", metadata={"scope": "history"})
    for rx in p.get("past_prescriptions", []):
        retain(bank, f"Past Rx {rx.get('date')}: {rx.get('drug')} — adverse: {rx.get('adverse_event')}. Note: {rx.get('doctor_note')}", kind="world_fact", metadata={"scope": "medications"})
    retain(bank, f"Preference: follow-up {p['preferences'].get('followup_days')} {p['preferences'].get('slot')} via {p['preferences'].get('channel')}", kind="world_fact", metadata={"scope": "preferences"})
print("Done. Banks ready. Try: POST /consult with demo-001 (conflict case) and demo-002 (safe case).")
