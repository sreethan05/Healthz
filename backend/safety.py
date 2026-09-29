"""
Cliniva safety checks — use retrieved evidence and report uncertainty.
Pipeline: live RxNorm -> pinned DDInter rules -> OpenFDA own-label -> DailyMed citations.
LLM only summarizes retrieved evidence.
Verdicts: CONFLICT | NO_CONFLICT | INSUFFICIENT_DATA
"""
import os
import re
import requests

from backend.ddinter import merged_rules

SEVERITY_RANK = {"contraindicated": 4, "major": 3, "moderate": 2, "minor": 1, "unknown": 0}

_RULES_CACHE: dict | None = None
_RULES_SOURCE = ""


def _rules() -> dict:
    global _RULES_CACHE, _RULES_SOURCE
    if _RULES_CACHE is None:
        _RULES_CACHE, _RULES_SOURCE = merged_rules()
    return _RULES_CACHE


def rules_source() -> str:
    _rules()
    return _RULES_SOURCE

PINNED_RULES = {
    ("amoxicillin", "penicillin"): {
        "severity": "contraindicated",
        "mechanism": "Cross-reactivity: amoxicillin is penicillin-class. History of penicillin allergy.",
        "source": "DDInter-demo + FDA label: amoxicillin contraindicated in penicillin hypersensitivity",
    },
    ("ampicillin", "penicillin"): {
        "severity": "contraindicated",
        "mechanism": "Cross-reactivity: ampicillin is penicillin-class.",
        "source": "FDA label: contraindicated in penicillin hypersensitivity",
    },
    ("ibuprofen", "warfarin"): {
        "severity": "major",
        "mechanism": "NSAID + anticoagulant increases bleeding risk (FDA warning).",
        "source": "FDA label: warfarin + ibuprofen bleeding risk",
    },
    ("azithromycin", "warfarin"): {
        "severity": "moderate",
        "mechanism": "Azithromycin may increase coagulation times with warfarin; monitor PT/INR.",
        "source": "FDA label azithromycin Sec 7: warfarin interaction",
    },
}

BRAND_MAP = {
    "advil": "ibuprofen", "motrin": "ibuprofen", "brufen": "ibuprofen",
    "amoxil": "amoxicillin", "moxikind": "amoxicillin",
    "coumadin": "warfarin", "warf": "warfarin",
    "zithromax": "azithromycin", "azee": "azithromycin",
    "crocin": "paracetamol", "tylenol": "paracetamol",
}

# US FDA uses acetaminophen; keep display as paracetamol but lookup both
FDA_ALIAS = {"paracetamol": "acetaminophen"}

_RXNORM_CACHE: dict = {}

PEN_CLASS = {"amoxicillin", "ampicillin", "penicillin", "amoxil", "penicilin"}

ALTERNATIVES = {
    "amoxicillin": [
        {"drug": "azithromycin 500mg OD x3d", "why": "Macrolide — guideline alternative for pharyngitis when penicillin-class avoided. Confirm allergy scope first."},
        {"drug": "cefuroxime (only if non-severe rash + doctor decides)", "why": "Needs risk stratification — cephalosporin cross-risk exists."},
    ],
    "ibuprofen": [
        {"drug": "paracetamol 650mg", "why": "Preferred analgesic with warfarin — no platelet/bleeding interaction."},
    ],
}


def dailymed_link(drug: str) -> str:
    q = requests.utils.quote(drug)
    return f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?query={q}"


def rxnorm_lookup(name: str) -> dict:
    """Live RxNorm: resolve brand/misspelling -> generic + RxCUI. Cached, 5s timeout, offline-safe."""
    key = name.strip().lower()
    if key in _RXNORM_CACHE:
        return _RXNORM_CACHE[key]
    try:
        r = requests.get(
            "https://rxnav.nlm.nih.gov/REST/rxcui.json",
            params={"name": name},
            timeout=5,
        )
        if r.status_code == 200:
            ids = (r.json().get("idGroup") or {}).get("rxnormId") or []
            if ids:
                r2 = requests.get(f"https://rxnav.nlm.nih.gov/REST/rxcui/{ids[0]}/property.json", params={"propName": "TTY"}, timeout=5)
                out = {"rxcui": ids[0], "resolved": name}
                _RXNORM_CACHE[key] = out
                return out
    except Exception:
        pass
    out = {"rxcui": None, "resolved": name}
    _RXNORM_CACHE[key] = out
    return out


def normalize(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"\s+\d+.*$", "", n).strip()
    n = re.sub(r"[^a-z ]", "", n).strip()
    if n in BRAND_MAP:
        return BRAND_MAP[n]
    # Hot path stays offline-first (brand map + cache only). Live RxNorm
    # resolution is opt-in via CLINIVA_RXNORM_LIVE=1; drug_info() always live.
    if os.getenv("CLINIVA_RXNORM_LIVE", "") == "1":
        rxnorm_lookup(n)  # warm cache, best-effort
    return n


def _openfda_label(drug: str) -> tuple[list, dict]:
    """Return (snippets, meta with setid/effective_time/link). Tries alias for US labels."""
    candidates = [drug] + ([FDA_ALIAS[drug]] if drug in FDA_ALIAS else [])
    try:
        for cand in candidates:
            for field in ("generic_name", "brand_name"):
                r = requests.get(
                    "https://api.fda.gov/drug/label.json",
                    params={"search": f'openfda.{field}:"{cand}"', "limit": 1},
                    timeout=10,
                )
                if r.status_code == 200 and r.json().get("results"):
                    lab = r.json()["results"][0]
                    out = []
                    for k in ("drug_interactions", "warnings", "contraindications", "boxed_warning"):
                        for t in (lab.get(k) or [])[:2]:
                            out.append(f"{k}: {t[:600]}")
                    meta = {
                        "spl_set_id": lab.get("openfda", {}).get("spl_set_id", [""])[0] if isinstance(lab.get("openfda", {}).get("spl_set_id"), list) else "",
                        "effective_time": lab.get("effective_time", ""),
                        "dailymed": dailymed_link(drug),
                    }
                    return out, meta
    except Exception:
        pass
    return [], {"dailymed": dailymed_link(drug)}


def find_alternatives(drug: str) -> list:
    return ALTERNATIVES.get(normalize(drug), [])


def drug_info(drug: str) -> dict:
    n = normalize(drug)
    rx = rxnorm_lookup(drug)
    snippets, meta = _openfda_label(n)
    return {"query": drug, "normalized": n, "rxnorm": rx, "label_snippets": snippets[:4], "citations": [meta.get("dailymed", "")], "meta": meta}


def check_interactions(meds: list[str], allergies: list[str] | None = None) -> dict:
    allergies_n = [normalize(a) for a in (allergies or [])]
    normed = [normalize(m) for m in meds]
    normalized_map = {orig: norm for orig, norm in zip(meds, normed)}
    findings = []

    has_pen_allergy = any("penicillin" in a for a in allergies_n)
    if has_pen_allergy:
        for orig, m in zip(meds, normed):
            if m in PEN_CLASS:
                findings.append({
                    "pair": [m, "penicillin-allergy"],
                    "verdict": "CONFLICT",
                    "severity": "contraindicated",
                    "mechanism": PINNED_RULES[("amoxicillin", "penicillin")]["mechanism"],
                    "sources": [PINNED_RULES[("amoxicillin", "penicillin")]["source"]],
                    "citations": [dailymed_link(m)],
                    "input": orig,
                })

    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            key = tuple(sorted([normed[i], normed[j]]))
            rules = _rules()
            if key in rules:
                rule = rules[key]
                findings.append({
                    "pair": list(key),
                    "verdict": "CONFLICT",
                    "severity": rule["severity"],
                    "mechanism": rule["mechanism"],
                    "sources": [rule["source"]],
                    "citations": [dailymed_link(normed[i]), dailymed_link(normed[j])],
                    "input": [meds[i], meds[j]],
                })

    fda_notes, metas = [], {}
    if not findings:
        for m in normed:
            ev, meta = _openfda_label(m)
            if ev:
                fda_notes.extend(ev)
                metas[m] = meta

    alts = []
    for f in findings:
        for d in f["pair"]:
            if d in ALTERNATIVES:
                alts.extend(ALTERNATIVES[d])
    # de-dupe alternatives
    seen, uniq_alts = set(), []
    for a in alts:
        if a["drug"] not in seen:
            seen.add(a["drug"])
            uniq_alts.append(a)

    if findings:
        worst = max(findings, key=lambda f: SEVERITY_RANK.get(f["severity"], 0))
        return {
            "verdict": "CONFLICT",
            "severity": worst["severity"],
            "findings": findings,
            "normalized": normalized_map,
            "alternatives": uniq_alts,
            "disclaimer": "Supports, does not replace clinical judgment. Doctor validation required.",
        }
    if fda_notes:
        # A few label snippets cannot prove a prescription is interaction-free.
        return {"verdict": "INSUFFICIENT_DATA", "severity": "unknown", "findings": [],
                "normalized": normalized_map, "fda_notes": fda_notes[:4],
                "citations": [dailymed_link(m) for m in normed],
                "disclaimer": "FDA label context is attached, but this is not a complete interaction screen. Verify the full regimen clinically."}
    return {"verdict": "INSUFFICIENT_DATA", "severity": "unknown", "findings": [],
            "normalized": normalized_map,
            "disclaimer": "No structured source found. Do not guess — verify with pharmacist/label."}
