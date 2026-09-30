# Cliniva — Frontend / UI-UX Demo (Hackathon)

Frontend-only demo of the consult-to-prescription flow. **All data is mock data**
behind simple function contracts — no backend, no real STT, auth, Hindsight calls
or QR crypto. The backend will replace the contracts later.

## Live demo

**https://sreethan05.github.io/Healthz/cliniva/**

Hosted via GitHub Pages — open it on any device, no setup needed. The QR codes
in the demo encode this live URL, so scanning one with a phone camera opens the
pharmacy verify screen directly.

## Run it locally

No build step. Either open `index.html` directly in a browser, or serve the folder:

```
python3 -m http.server 8000
# open http://localhost:8000
```

Routes use hash-based paths (`#/login`, `#/doctor`, `#/patient?id=P-1024`, `#/rx/8F3A`)
so the demo works from any static host or the local filesystem.

## 3-minute demo script

1. **Login as Doctor** → `/doctor` consult console.
2. **Start Consult** → transcript streams (with typing indicator). The
   *Amoxicillin* line triggers the critical safety popup (Penicillin allergy) →
   **Change prescription** swaps to Azithromycin and the stream resumes.
3. **End Consult** → draft Rx (editable). In the sign panel, first enter a wrong
   patient ID (e.g. `P-9999`) → inline error. Then enter **P-1024** → signed,
   Rx ID `RX-8F3A-2026`, QR preview appears.
4. **Logout → Log in as Patient** → visit summary, current e-Rx with large QR,
   follow-up cards with reminder toggles (toast confirms each reminder).
5. Scan the QR with a phone (any network) or click it → **pharmacy verifier**:
   VALID → **Mark as Dispensed** → DISPENSED. Try `#/rx/XXXX` for INVALID.
6. Access-denied demo: while logged in as patient, open `#/doctor`, or
   `#/patient?id=P-9999`.

## Mock contracts (backend replaces later)

In `mocks.js`: `getMockPatient`, `streamMockTranscript`, `checkMockSafety`,
`buildMockDraftRx`, `signMockRx`, `getMockFollowUps`, `verifyMockRx`,
`dispenseMockRx`, `getMockRx`, `getMockVisitSummary`.

## Notes

- RBAC is a client-side demo guard only (sessionStorage `cliniva_role`) — no
  real security claims.
- QR codes are **real and scannable**: `qr.js` (qrcode-generator, MIT licence —
  Copyright Kazuhiko Arase) renders genuine QR codes. Served over http (or the
  live Pages URL above), a phone camera opens the pharmacy verify screen
  directly from the QR tile. From `file://` the code falls back to the short
  verify code.
- Micro-animations respect `prefers-reduced-motion`.
- Statuses reset on page reload (in-memory only).
