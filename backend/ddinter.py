"""DDInter 2.0 SQLite loader + expanded curated rules. Prod path: mount DDInter sqlite, else curated fallback."""
import pathlib
import sqlite3

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
SQLITE_CANDIDATES = [DATA / "ddinter.sqlite", DATA / "ddinter.db", DATA / "DDInter.sqlite"]

# Adjudicated core: hand-verified against FDA labels (see backend/verify_pairs.py).
# These overlay (win over) any mined SQLite rows for the same pair.
CURATED = [
    ("amoxicillin", "penicillin", "contraindicated", "Penicillin-class cross-reactivity", "FDA label + DDInter"),
    ("ampicillin", "penicillin", "contraindicated", "Penicillin-class cross-reactivity", "FDA label"),
    ("cefuroxime", "penicillin", "moderate", "Cephalosporin cross-risk if severe penicillin allergy; stratify by reaction type", "Guideline: stratify by reaction type"),
    ("ibuprofen", "warfarin", "major", "NSAID + anticoagulant bleeding risk", "FDA boxed/warning"),
    ("aspirin", "warfarin", "major", "Dual anticoagulant/antiplatelet bleeding risk", "FDA label"),
    ("aspirin", "ibuprofen", "moderate", "Ibuprofen may blunt aspirin antiplatelet effect; stagger dosing", "FDA label"),
    ("azithromycin", "warfarin", "moderate", "May raise PT/INR; monitor", "FDA label Sec 7"),
    ("azithromycin", "penicillin", "minor", "Different class; usually tolerated but confirm macrolide allergy history", "Clinical guideline"),
    ("ibuprofen", "lithium", "major", "NSAIDs may raise lithium levels/toxicity; monitor levels", "FDA lithium label Sec 7 (verified)"),
    ("paracetamol", "warfarin", "moderate", "Chronic use may raise INR; consult doctor", "FDA acetaminophen OTC label (verified)"),
    ("simvastatin", "warfarin", "moderate", "Postmarketing bleeding/INR rise with statins + warfarin", "FDA label (verified)"),
    ("amlodipine", "paracetamol", "minor", "No significant interaction expected", "Label review"),
]


def load_sqlite_pairs() -> dict:
    """Try real DDInter sqlite (FTS/pair table). Returns {} if not mounted — honest fallback."""
    for p in SQLITE_CANDIDATES:
        if not p.exists():
            continue
        try:
            con = sqlite3.connect(str(p))
            cur = con.cursor()
            # try common schemas
            for q in [
                "SELECT drug_a, drug_b, severity, mechanism FROM interactions LIMIT 5000",
                "SELECT drug1, drug2, severity, description FROM ddinter LIMIT 5000",
            ]:
                try:
                    rows = cur.execute(q).fetchall()
                    if rows:
                        out = {}
                        for a, b, sev, mech in rows:
                            out[tuple(sorted([str(a).lower(), str(b).lower()]))] = {
                                "severity": str(sev).lower(), "mechanism": str(mech), "source": f"DDInter SQLite {p.name}"}
                        con.close()
                        return out
                except Exception:
                    continue
            con.close()
        except Exception:
            continue
    return {}


def merged_rules() -> tuple[dict, str]:
    """SQLite breadth + adjudicated curated overlay (curated wins on conflict)."""
    out, src = {}, "curated-only"
    db = load_sqlite_pairs()
    if db:
        out.update(db)
        src = "ddinter-sqlite"
    n_cur = 0
    for a, b, sev, mech, s in CURATED:
        out[tuple(sorted([a, b]))] = {"severity": sev, "mechanism": mech, "source": s + " [adjudicated]"}
        n_cur += 1
    if db:
        src = f"ddinter-sqlite ({len(db)} mined) + {n_cur} adjudicated overrides"
    else:
        src = f"curated-fallback ({n_cur} adjudicated; run backend/build_ddinter.py for mined DB)"
    return out, src
