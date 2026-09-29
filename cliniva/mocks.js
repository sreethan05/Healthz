/* Cliniva — mock contracts (frontend-owned; backend replaces these later).
 * Demo scope only: no real STT, auth, Hindsight calls, QR crypto or DB. */

var MOCK_RX_CODE = "8F3A";
var MOCK_RX_ID = "RX-8F3A-2026";
var MOCK_PATIENT_ID = "P-1024";

var MOCK_PATIENT = {
  id: "P-1024",
  name: "Ravi Kumar",
  age: 41,
  allergy: "Penicillin",
  pastVisits: [
    { date: "14 Aug 2026", reason: "Seasonal cough and cold" }
  ]
};

var MOCK_VISIT_SUMMARY = {
  doctor: "Dr. Mehta",
  date: "29 Sep 2026",
  reason: "Sore throat and fever (3 days)"
};

var MOCK_RX = {
  rxId: MOCK_RX_ID,
  code: MOCK_RX_CODE,
  drug: "Azithromycin",
  dosage: "500 mg once daily",
  duration: "5 days",
  doctor: "Dr. Mehta",
  date: "29 Sep 2026",
  expiry: "13 Oct 2026",
  qr: "#/rx/" + MOCK_RX_CODE
};

var MOCK_FOLLOW_UPS = [
  { icon: "🩺", title: "BP check", due: "Due in 7 days" },
  { icon: "🧪", title: "Bring blood test report", due: "Due in 3 days" },
  { icon: "💧", title: "Hydration review", due: "Due in 14 days" }
];

/* --- Contracts --- */

function getMockPatient(id) {
  return id === MOCK_PATIENT_ID ? JSON.parse(JSON.stringify(MOCK_PATIENT)) : null;
}

function getMockVisitSummary() {
  return JSON.parse(JSON.stringify(MOCK_VISIT_SUMMARY));
}

/* Timed transcript lines. The Amoxicillin line carries the safety flag. */
var MOCK_TRANSCRIPT = [
  { speaker: "Dr", text: "Good morning, Ravi. What brings you in today?" },
  { speaker: "Pt", text: "I've had a sore throat and fever for three days, doctor." },
  { speaker: "Dr", text: "Any difficulty swallowing?" },
  { speaker: "Pt", text: "Yes, a little — mostly in the mornings." },
  { speaker: "Dr", text: "We'll start a course of Amoxicillin 500 mg, twice a day for five days.", drug: "Amoxicillin" },
  { speaker: "Pt", text: "Okay, doctor." },
  { speaker: "Dr", text: "Drink warm fluids, rest well. We'll review in a week." }
];

/* Returns a controller: start(onLine) streams lines at demo pace,
 * stop() halts. onLine(index, line) fires for each line. */
function streamMockTranscript(onLine, onDone) {
  var i = 0;
  var stopped = false;
  var timer = null;
  function tick() {
    if (stopped) return;
    if (i >= MOCK_TRANSCRIPT.length) {
      if (onDone) onDone();
      return;
    }
    var idx = i;
    var line = MOCK_TRANSCRIPT[idx];
    i++;
    onLine(idx, line);
    timer = setTimeout(tick, line.drug ? 2200 : 1300);
  }
  timer = setTimeout(tick, 600);
  return {
    stop: function () {
      stopped = true;
      if (timer) clearTimeout(timer);
    },
    isStopped: function () { return stopped; }
  };
}

/* critical | ok — critical when the line names a drug the patient is allergic to. */
function checkMockSafety(line) {
  if (line && line.drug === "Amoxicillin") {
    return {
      status: "critical",
      title: "Critical allergy risk",
      reason: "Patient has a documented Penicillin allergy; Amoxicillin is a penicillin-class drug."
    };
  }
  return { status: "ok" };
}

/* Draft Rx built from whatever drug is pending after the consult. */
function buildMockDraftRx(drug) {
  return {
    drug: drug || "Azithromycin",
    dosage: "500 mg once daily",
    duration: "5 days"
  };
}

/* error if entered ID is wrong, else success payload with Rx ID + QR value */
function signMockRx(enteredId) {
  if (enteredId !== MOCK_PATIENT_ID) {
    return { ok: false, error: "ID mismatch — check patient" };
  }
  return {
    ok: true,
    rxId: MOCK_RX_ID,
    qr: MOCK_RX.qr,
    followUps: MOCK_FOLLOW_UPS.length
  };
}

function getMockFollowUps() {
  return JSON.parse(JSON.stringify(MOCK_FOLLOW_UPS));
}

/* in-memory Rx state: VALID | INVALID | DISPENSED */
var MOCK_RX_DISPENSED = false;

function verifyMockRx(id) {
  if (id !== MOCK_RX_CODE) return "INVALID";
  return MOCK_RX_DISPENSED ? "DISPENSED" : "VALID";
}

function dispenseMockRx(id) {
  if (id === MOCK_RX_CODE) MOCK_RX_DISPENSED = true;
}

function getMockRx() {
  return JSON.parse(JSON.stringify(MOCK_RX));
}
