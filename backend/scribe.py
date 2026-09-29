"""Cliniva demo scribe: transcript -> SOAP draft + ICD-10 hints for clinician review."""
ICD_HINTS = [
    ("throat pain", "J02.9", "Acute pharyngitis, unspecified"),
    ("fever", "R50.9", "Fever, unspecified"),
    ("headache", "R51", "Headache"),
    ("cough", "R05", "Cough"),
    ("rash", "R21", "Rash"),
    ("hypertension", "I10", "Essential hypertension"),
    ("asthma", "J45.909", "Asthma, uncomplicated"),
]


def draft_soap(transcript: str, memory_context: dict | None = None) -> dict:
    t = transcript or ""
    tl = t.lower()
    ctx, mms = "", []
    if memory_context:
        ac = memory_context.get("answer_context", {})
        obs = ac.get("observations", []) or []
        mms = ac.get("mental_models", []) or []
        bits = [o.get("content", "")[:120] for o in obs[:3]]
        bits += [m.get("content", "")[:120] for m in mms[:2]]
        ctx = " | ".join(b for b in bits if b)
    symptoms = [kw for kw in ["fever", "throat pain", "cough", "headache", "rash", "breath", "hypertension", "asthma"] if kw in tl]
    icd = [{"code": c, "display": d, "matched": k} for k, c, d in ICD_HINTS if k in tl][:3]
    if "throat" in tl:
        assessment = "Acute pharyngitis (?) — to be confirmed by doctor."
        plan = "Consider throat exam. Draft Rx pending safety check."
        draft_meds = ["amoxicillin 500mg TDS x5d (DRAFT — unsafe if penicillin allergy, needs safety check)"]
    elif "hypertension" in tl or "bp" in tl or "headache" in tl:
        assessment = "Hypertension follow-up (?) — confirm with BP reading."
        plan = "Measure BP, review adherence. Draft Rx pending safety check."
        draft_meds = []
    else:
        assessment = "Assessment TBD by doctor."
        plan = "Exam + history review. Draft Rx pending safety check."
        draft_meds = []
    return {
        "subjective": f"Patient reports: {', '.join(symptoms) or 'as transcribed'}.",
        "objective": "Vitals: TBD. Exam: TBD.",
        "assessment": assessment,
        "plan": plan,
        "icd_hints": icd,
        "draft_meds": draft_meds,
        "memory_used": ctx,
        "status": "DRAFT — requires doctor review, edit and digital signature",
    }


def apply_correction(draft: dict, correction_text: str) -> dict:
    draft = dict(draft)
    cl = (correction_text or "").lower()
    draft["doctor_correction"] = correction_text
    if "penicillin" in cl or "azithro" in cl:
        draft["plan"] = correction_text
        draft["draft_meds"] = ["azithromycin 500mg OD x3d (DRAFT — post-correction)"]
    elif correction_text and "draft_meds" not in draft:
        draft["draft_meds"] = []
    draft["status"] = "CORRECTED — ready for safety re-check + sign"
    return draft
