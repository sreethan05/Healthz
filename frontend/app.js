const $ = (id) => document.getElementById(id);
const API = "";
let lastDraft = null, lastToken = "", lastRxId = "", lastFlagged = "amoxicillin", authToken = "";

async function j(url, opts = {}) {
  const status = $("status");
  if (status) status.textContent = "Working…";
  try {
    const r = await fetch(url, { ...opts, headers: { "Content-Type": "application/json", ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}), ...(opts.headers || {}) } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = Array.isArray(body.detail) ? "Please check the submitted fields." : body.detail || body.error || `Request failed (${r.status})`;
      throw new Error(detail);
    }
    if (status) status.textContent = "Connected · local demo API ready";
    return body;
  } catch (error) {
    if (status) status.textContent = `Could not complete request: ${error.message}`;
    throw error;
  }
}
async function login(username) {
  const out = await j(`${API}/auth/login`, { method: "POST", body: JSON.stringify({ username, password: "demo123" }), headers: {} });
  authToken = out.token;
}
async function init() {
  await login("dr-demo");
  const pts = await j(`${API}/patients`).catch(() => []);
  const patientSelect = $("patient");
  patientSelect.replaceChildren();
  (pts || []).forEach(p => {
    const option = document.createElement("option");
    option.value = p.patient_id;
    option.textContent = `${p.patient_id} — ${p.name}`;
    patientSelect.appendChild(option);
  });
  if (!patientSelect.options.length) {
    const option = document.createElement("option");
    option.value = "demo-001";
    option.textContent = "demo-001";
    patientSelect.appendChild(option);
  }
  document.querySelectorAll("[data-t]").forEach(b => b.onclick = () => $("transcript").value = b.dataset.t);
  $("loadTimeline").onclick = loadTimeline;
  $("saveConsent").onclick = saveConsent;
  $("notice").onclick = async () => $("extra").textContent = JSON.stringify(await j(`${API}/consent-notice`), null, 2);
  $("memoryBtn").onclick = async () => $("extra").textContent = JSON.stringify(await j(`${API}/memory/${$("patient").value}`), null, 2);
  $("consult").onclick = consult;
  $("altBtn").onclick = async () => $("alts").textContent = JSON.stringify(await j(`${API}/alternatives`, { method: "POST", body: JSON.stringify({ drug: lastFlagged }) }), null, 2);
  $("correct").onclick = correct;
  $("sign").onclick = sign;
  $("verifyBtn").onclick = verify;
  $("fhirLink").onclick = downloadFhir;
  $("tamperBtn").onclick = async () => $("verify").textContent = JSON.stringify(await j(`${API}/tamper-demo`, { method: "POST", body: JSON.stringify({ token: lastToken }) }), null, 2);
  $("auditBtn").onclick = async () => $("audit").textContent = JSON.stringify(await j(`${API}/audit?limit=20`), null, 2);
  $("printBtn").onclick = () => window.print();
}
async function loadTimeline() {
  try { $("timeline").textContent = JSON.stringify(await j(`${API}/timeline/${$("patient").value}`), null, 2); }
  catch (e) { $("timeline").textContent = e.message; }
}
async function saveConsent() {
  const id = $("patient").value;
  try {
    await login(id === "demo-002" ? "patient-demo-2" : "patient-demo");
    const out = await j(`${API}/consent/${id}`, { method: "POST", body: JSON.stringify({ revoked: $("cRevoked").checked, scopes: { history: $("cHistory").checked, allergies: $("cAllergies").checked, medications: $("cMeds").checked } }) });
    await login("dr-demo");
    $("extra").textContent = `Consent saved: ${JSON.stringify(out)}`;
    await loadTimeline();
  } catch (e) { await login("dr-demo"); alert(e.message); }
}
async function consult() {
  let out;
  try { out = await j(`${API}/consult`, { method: "POST", body: JSON.stringify({ patient_id: $("patient").value, transcript: $("transcript").value }) }); }
  catch (e) { alert(e.message); return; }
  lastDraft = out.draft;
  $("soap").textContent = JSON.stringify(out.draft, null, 2);
  $("safety").textContent = JSON.stringify(out.safety, null, 2);
  $("mem").textContent = JSON.stringify(out.memory?.answer_context || out.memory, null, 2);
  const f = out.safety?.findings?.[0];
  if (f) { lastFlagged = (f.pair || ["amoxicillin"])[0].replace("-allergy", ""); $("alts").textContent = JSON.stringify({ alternatives: out.safety.alternatives, citations: f.citations }, null, 2); }
  else $("alts").textContent = JSON.stringify({ citations: out.safety?.citations || [], fda_notes: (out.safety?.fda_notes || []).slice(0, 2) }, null, 2);
  $("safety").style.outline = out.safety?.verdict === "CONFLICT" ? "3px solid #ef4444" : "3px solid #22c55e";
}
async function correct() {
  if (!lastDraft) return alert("Run consult first");
  const out = await j(`${API}/correct`, { method: "POST", body: JSON.stringify({ patient_id: $("patient").value, draft: lastDraft, correction: $("correction").value }) });
  lastDraft = out.updated;
  $("corrected").textContent = JSON.stringify(out.updated, null, 2);
  $("recheck").textContent = JSON.stringify({ safety_recheck: out.safety_recheck, booking: out.booking, learning: out.learning?.counts }, null, 2);
  $("meds").value = (out.updated.draft_meds?.[0] || $("meds").value).replace(/ \(DRAFT.*/, "");
}
async function sign() {
  let out;
  try { out = await j(`${API}/sign`, { method: "POST", body: JSON.stringify({ patient_id: $("patient").value, doctor_id: "dr-demo", doctor_reg: "MCI-12345", meds: [$("meds").value], soap: { assessment: lastDraft?.assessment || "", plan: $("correction").value }, clinician_confirmed_insufficient_data: $("uncertainConfirm").checked }) }); }
  catch (e) { alert(e.message); return; }
  lastToken = out.token; lastRxId = out.rx_id;
  $("rx").textContent = JSON.stringify({ rx_id: out.rx_id, qr_payload: out.qr_payload, hash: out.hash }, null, 2);
  if (out.qr_png_base64) $("qr").src = "data:image/png;base64," + out.qr_png_base64;
  $("verifyLink").href = `/verify-page/${out.rx_id}`;
  $("fhirLink").href = `/fhir-rx/${out.rx_id}`;
}
async function verify() {
  $("verify").textContent = JSON.stringify(await j(`${API}/verify`, { method: "POST", body: JSON.stringify({ token: lastToken }) }), null, 2);
}
async function downloadFhir(event) {
  event.preventDefault();
  if (!lastRxId) return alert("Sign a prescription first");
  try {
    const result = await j(`${API}/fhir-rx/${lastRxId}`);
    const blob = new Blob([JSON.stringify(result.fhir_bundle, null, 2)], { type: "application/fhir+json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${lastRxId}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) { alert(e.message); }
}
init();
