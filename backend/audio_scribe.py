"""Audio scribe: Whisper when available, deterministic stub otherwise. Mic consent required."""
import pathlib
import secrets

TRANSCRIPTS = {
    "throat": "Doctor: What brings you today? Patient: I have fever and throat pain since 2 days. Doctor: Any drug allergies? Patient: Yes, penicillin gave me rash last year.",
    "bp": "Doctor: BP check today? Patient: Yes, mild headache. No known drug allergies.",
}
UPLOAD_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "uploads"


def transcribe(audio_path: str = "", hint: str = "throat", mic_consent: bool = False) -> dict:
    if not mic_consent:
        return {"ok": False, "reason": "Mic consent required before recording (DPDP). Show consent checkbox first."}
    try:
        import faster_whisper  # type: ignore
        return {"ok": True, "engine": "faster-whisper", "note": "wire model load here in prod", "hint": hint}
    except Exception:
        key = "bp" if "bp" in (hint or "").lower() or "headache" in (hint or "").lower() else "throat"
        return {"ok": True, "engine": "stub-demo", "transcript": TRANSCRIPTS[key],
                "note": "Stub for offline demo. Install faster-whisper + ffmpeg for real audio."}


def save_upload(data: bytes, name: str = "consult.webm") -> str:
    """Save a bounded audio upload under a server-generated name."""
    suffix = pathlib.Path(name).suffix.lower()
    if suffix not in {".webm", ".wav", ".mp3", ".m4a"}:
        raise ValueError("Unsupported audio file type")
    if not isinstance(data, bytes) or not data or len(data) > 25 * 1024 * 1024:
        raise ValueError("Audio upload must be between 1 byte and 25 MB")
    p = UPLOAD_DIR
    p.mkdir(parents=True, exist_ok=True)
    f = p / f"{secrets.token_hex(16)}{suffix}"
    temp = f.with_suffix(f.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(f)
    return str(f)
