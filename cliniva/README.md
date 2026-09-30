# Cliniva — Production e-Prescription Platform

[![CI](https://github.com/sreethan05/Healthz/actions/workflows/ci.yml/badge.svg)](https://github.com/sreethan05/Healthz/actions/workflows/ci.yml)

Consult-to-prescription platform: JWT authentication with role-based access
(doctor / patient / pharmacist), patient-controlled consent (DPDP-aligned),
memory-assisted SOAP drafting, drug-interaction safety screening, HMAC-signed
e-prescriptions with scannable QR codes, pharmacy verification and dispense
tracking, audit logging, and FHIR export.

**No mock data.** The frontend talks to the real FastAPI backend for every action.

## Architecture

```
cliniva/               production web app (served by the API at /app)
  index.html             shell
  api.js                 API client: base-URL resolution, JWT session, error handling
  app.js                 screens: login, doctor console, patient portal, pharmacy verifier
  styles.css             design system
  qr.js                  qrcode-generator (MIT, Kazuhiko Arase) — client QR fallback
backend/               FastAPI service (auth, consent, consult, safety, sign, dispense…)
data/                  patient records, memory banks, consent store, Rx store, DDInter rules
memory/                Hindsight memory client (local JSON banks; HINDSIGHT_URL for remote)
```

## Quick start

```
run.bat                      (Windows)
# or
pip install -r backend/requirements.txt
python backend/seed.py       # seed patient memory banks
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/app/**

### Accounts (evaluation set, password `demo123`)

| Username        | Role       | Notes                                    |
|-----------------|------------|------------------------------------------|
| `dr-demo`       | doctor     | reg MCI-12345; consult, sign, audit      |
| `patient-demo`  | patient    | demo-001; penicillin allergy (conflict case) |
| `patient-demo-2`| patient    | demo-002; safe case                      |
| `pharm-demo`    | pharmacist | verify and dispense                      |

## Production flow

1. **Patient grants consent** in the portal (history / allergies / medications). Without it the API refuses every clinical action (HTTP 403).
2. **Doctor**: pick patient → type or dictate the consult (browser speech-to-text) → the API drafts a SOAP note from memory, screens the regimen against allergies + DDInter/FDA rules.
3. **Unsafe medication** (e.g. amoxicillin with penicillin allergy) → critical modal with mechanism, sources and safer alternatives; switching applies a server-side correction and re-screens.
4. **Sign**: the API blocks unsafe prescriptions (409), requires explicit clinician confirmation when screening is incomplete, then issues an HMAC-signed prescription (Rx ID, SHA-256 hash, QR with verify URL + hash prefix). Valid 30 days.
5. **Patient portal**: profile, consent switches (revoking a scope locks doctor access immediately), prescriptions with QR codes.
6. **Pharmacy**: scan the QR (or open the link) → public verifier checks signature + hash prefix → VALID/DISPENSED/EXPIRED; a pharmacist signs in to mark dispensed. Tampered hashes are rejected.
7. Doctor console extras: issued-prescription history with status, FHIR bundle export (downloadable JSON), printable prescriptions, and a live audit trail viewer. Every step is audit-logged; FHIR bundles are exportable per prescription.

## API surface (selected)

`POST /auth/login` · `GET /patients` · `POST /consult` · `POST /correct` · `POST /sign` ·
`POST /verify` · `GET /rx/{id}` · `GET /fhir-rx/{id}` · `GET /timeline/{id}` ·
`GET /me` · `POST /me/consent` · `GET /me/rx` · `GET /public/rx/{id}?h=` · `POST /dispense/{id}` ·
`GET /doctor/rx` · `GET /audit` · `GET /ops/health`

## Production hardening notes

- Set `CLINIVA_ENV=prod` — this disables demo credentials and enforces secret requirements.
- Set `CLINIVA_AUTH_SECRET` and `CLINIVA_RX_SECRET` (32+ chars each).
- Set `CLINIVA_VERIFY_BASE` to your public origin so QR links are correct behind proxies (defaults to the request host).
- Set `CLINIVA_CORS_ORIGINS` if the app is hosted separately from the API.
- Serve over HTTPS (reverse proxy); the API sets HSTS-grade security headers, rate limits auth/consult/sign, and stores no secrets in code.
- Swap the local auth users for a real identity provider (Keycloak / ABDM HPR) before real clinical use; set `ABDM_MODE=sandbox|prod` for ABDM consent artefacts.

## Deployment

The included `Dockerfile` containerises the API. Any host works (Render, Railway, Fly.io, your own VM): run uvicorn behind TLS, mount `data/` on a persistent volume, set the env vars above. The QR verify links derive from the serving host automatically.

## Verification

`e2e_prod.js` (happy-dom) drives the real app against the real API: login → consult → conflict → correction → sign → patient portal → pharmacy verify → dispense → tamper rejection.

---
Cliniva supports, does not replace, clinical judgment. Not certified for real patient care.
