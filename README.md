# Cliniva — Consent-Gated Health Memory Demo

Cliniva is a local prototype for a clinical memory and prescribing workflow. It drafts notes and safety checks for clinician review; it is not a clinical system and must not be used with real patient data.

[![CI](https://github.com/sreethan05/Healthz/actions/workflows/ci.yml/badge.svg)](https://github.com/sreethan05/Healthz/actions/workflows/ci.yml)

## Production app (`cliniva/`)

The `cliniva/` web app is the production client for this API: real JWT login, DPDP consent management, memory-assisted consult drafting, drug-interaction safety screening, HMAC-signed e-prescriptions with scannable QR codes, a public pharmacy verifier with dispense tracking, prescription history, FHIR export, and an audit viewer. No mock data — every action hits the real API.

Sign in at `http://127.0.0.1:8000/app/` with `dr-demo` (doctor), `patient-demo` (patient), or `pharm-demo` (pharmacist) — password `demo123`.

`node e2e_prod.js` (after `npm install happy-dom`, with the API running) drives the full app end to end: login → consult → conflict → correction → sign → patient portal → pharmacy verify → dispense → tamper rejection.

## Run locally

```powershell
pip install -r backend/requirements.txt
python backend/seed.py
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/app/`. In this demo, the app uses `dr-demo` / `demo123` for the doctor session and `patient-demo` / `patient-demo-2` (both with `demo123`) to record each demo patient's consent. Select history, allergy, and medication scopes, click **Save patient consent**, then load the timeline or run a consult. Turn on **revoked** and save to lock access. These fixed credentials are for local demonstration only.

The API requires bearer tokens for clinical and operational routes. Patient consent defaults to revoked and must be saved by a matching patient account. Prescription signing checks the authenticated doctor's identity, blocks detected interaction conflicts, and requires explicit clinician review when screening is incomplete. QR verification exposes a prescription to someone possessing the unguessable prescription URL; protect and share that QR accordingly.

Audit entries intentionally keep medication names and correction free text out of the general audit feed. The local audio helper limits uploads and stores them with generated filenames; the provided transcription path remains a deterministic demo stub unless a real transcription integration is configured.

## Project map

- `backend/main.py` — FastAPI routes for consultations, consent, prescriptions, FHIR, audit, and operations
- `backend/safety.py` — drug normalization and interaction lookup, with a curated fallback when DDInter data is not mounted
- `backend/scribe.py`, `backend/audio_scribe.py` — deterministic SOAP drafts and consent-gated audio demo stub
- `memory/hindsight_client.py` — Hindsight integration or local per-patient JSON memory
- `backend/rx_sign.py`, `backend/fhir.py` — signed demo prescriptions and FHIR bundle generation
- `frontend/` — original browser demo
- `cliniva/` — production web app (JWT auth, consent, e-prescriptions, pharmacy verifier)

## Configuration and limits

Copy `.env.example` to `.env` and load its values in your environment as needed. `CLINIVA_ENV=prod` requires unique auth and prescription secrets of at least 32 characters and disables the built-in demo login. Production use also requires replacing the demo identity store with a real identity provider, deploying authenticated consent capture, configuring TLS and secure key storage, and completing clinical, privacy, and regulatory review. The current consent store, ABDM artefacts, reminders, audit storage, local memory fallback, and region value are demonstration implementations; they do not establish legal compliance, encryption at rest, data residency, or production-grade audit guarantees.

`python backend/seed.py` preserves existing memory data. Use `python backend/seed.py --reset` to replace only the two demo patient memory files; prescription records and other patient memory files are preserved.

Run deterministic, offline, isolated module checks with `python test_e2e.py`. They use a temporary directory and do not change project patient, prescription, or audit data. They do not test the HTTP authorization policy.

Install `backend/requirements-dev.txt` and run `pytest tests/api_security_checks.py` for HTTP-level checks of role enforcement, consent defaults and revocation, prescription access, clinical review gating when screening is incomplete, audit minimization, safe upload naming, input validation, and patient-ID handling. The API checks use temporary data stores.

## Interaction database

`safety.py` uses `ddinter.sqlite` breadth (FDA-label-mined pairs with evidence sentences) plus an adjudicated curated overlay that wins on conflict — see `rules_source()` / `/ops/health`. Rebuild it with:

```powershell
python backend/build_ddinter.py
```

Hand-verified pairs live in `backend/ddinter.py` (`CURATED`); verification notes are in git history. The hot path is offline-first — live RxNorm resolution is opt-in via `CLINIVA_RXNORM_LIVE=1`; `POST /drug-info` always enriches live.

## ABDM sandbox path

Default mode is mock. For a real handshake, set `ABDM_MODE=sandbox` plus `ABDM_CLIENT_ID` / `ABDM_CLIENT_SECRET` (from sandbox.abdm.gov.in) and optionally `ABDM_GATEWAY` / `ABDM_CALLBACK_URL`. `backend/abdm.py` implements session → consent-request → PHR approval → FHIR release; `tests/test_abdm_handshake.py` proves the call construction with stubbed HTTP.

## Load test

```powershell
python backend/load_test.py
```

60 concurrent mixed consult/timeline/sign requests. Last clean run: 60/60, p50 ~0.2s, p95 ~2.9s, zero 500s.
