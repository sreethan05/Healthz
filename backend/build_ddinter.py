"""Mine FDA labels into a local DDInter-style SQLite (drug_a, drug_b, severity, mechanism, source).

Usage: python backend/build_ddinter.py
Output: data/ddinter.sqlite (used automatically by backend/ddinter.py loader).

Method (honest, no guessing): for each vocab drug, fetch its own FDA label,
split interaction/warning text into sentences, keep sentences that mention
another vocab drug, grade severity from label language, store the sentence
as evidence. Pairs are directional in labels, so both directions are stored
as one sorted pair.
"""
import pathlib
import re
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import requests

VOCAB = [
    "amoxicillin", "ampicillin", "penicillin", "azithromycin", "cefuroxime",
    "ibuprofen", "aspirin", "paracetamol", "acetaminophen", "warfarin",
    "amlodipine", "simvastatin", "digoxin", "methotrexate", "lithium",
    "metformin", "atorvastatin", "omeprazole", "losartan", "salbutamol",
]

SECTIONS = ("drug_interactions", "warnings", "contraindications", "boxed_warning")


def label_for(drug: str) -> dict | None:
    for field in ("generic_name", "brand_name"):
        try:
            r = requests.get("https://api.fda.gov/drug/label.json",
                             params={"search": f'openfda.{field}:"{drug}"', "limit": 1}, timeout=15)
            if r.status_code == 200 and r.json().get("results"):
                return r.json()["results"][0]
        except Exception:
            pass
    return None


def grade(sentence: str) -> str:
    s = sentence.lower()
    if "contraindicat" in s:
        return "contraindicated"
    if any(k in s for k in ("avoid concomitant", "should not be co", "life-threatening", "fatal", "boxed warning")):
        return "major"
    if any(k in s for k in ("monitor", "dose adjust", "dose reduction", "may increase", "increased risk", "caution")):
        return "moderate"
    return "minor"


def mine() -> list:
    rows = {}
    for drug in VOCAB:
        lab = label_for(drug)
        if not lab:
            print(f"  no label: {drug}")
            continue
        setid = ""
        try:
            setid = (lab.get("openfda", {}).get("spl_set_id") or [""])[0]
        except Exception:
            pass
        eff = lab.get("effective_time", "")
        text = " ".join(" ".join(lab.get(k) or []) for k in SECTIONS)
        for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text):
            low = sent.lower()
            if len(sent) < 40 or len(sent) > 600:
                continue
            for other in VOCAB:
                if other == drug or other not in low:
                    continue
                # avoid self-mention noise: sentence must read like an interaction
                if not re.search(r"interact|concomitant|co-admin|increase|decrease|monitor|avoid|contra|effect of|with ", low):
                    continue
                key = tuple(sorted([drug, other]))
                cand = (grade(sent), sent.strip()[:400], f"FDA label spl:{setid} eff:{eff}")
                rank = {"contraindicated": 4, "major": 3, "moderate": 2, "minor": 1}
                if key not in rows or rank[cand[0]] > rank[rows[key][0]]:
                    rows[key] = cand
        print(f"  {drug}: {sum(1 for k in rows if drug in k)} pairs so far")
    return [(a, b, sev, mech, src) for (a, b), (sev, mech, src) in rows.items()]


def main():
    print("Mining FDA labels...")
    rows = mine()
    out = pathlib.Path(__file__).resolve().parent.parent / "data" / "ddinter.sqlite"
    con = sqlite3.connect(str(out))
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS interactions")
    cur.execute("CREATE TABLE interactions (drug_a TEXT, drug_b TEXT, severity TEXT, mechanism TEXT, source TEXT)")
    cur.executemany("INSERT INTO interactions VALUES (?,?,?,?,?)", rows)
    cur.execute("CREATE INDEX idx_pair ON interactions (drug_a, drug_b)")
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    con.close()
    print(f"Wrote {n} pairs -> {out}")


if __name__ == "__main__":
    main()
