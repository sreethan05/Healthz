/* Cliniva production E2E: drives the real app (happy-dom) against the real API.
   Run: npm install happy-dom && start the API, then `node e2e_prod.js`. */
const { Window } = require("happy-dom");
const http = require("http");
const fs = require("fs");

const BASE = "http://127.0.0.1:8000";
let failures = 0;

function check(name, cond) {
  console.log((cond ? "PASS" : "FAIL") + " - " + name);
  if (!cond) failures++;
}

function jfetch(url, opts) {
  opts = opts || {};
  const full = url.startsWith("http") ? url : BASE + url;
  const u = new URL(full);
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search,
      method: opts.method || "GET", headers: opts.headers || {}
    }, res => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", () => resolve({
        ok: res.statusCode >= 200 && res.statusCode < 300,
        status: res.statusCode,
        json: () => Promise.resolve(data ? JSON.parse(data) : null)
      }));
    });
    req.on("error", reject);
    if (opts.body) req.write(opts.body);
    req.end();
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitFor(fn, ms, label) {
  const end = Date.now() + (ms || 15000);
  while (Date.now() < end) {
    let v;
    try { v = fn(); } catch (e) { v = null; }
    if (v) return v;
    await sleep(200);
  }
  throw new Error("timeout waiting for " + (label || "condition"));
}

(async function main() {
  // server-side prep: grant consent
  const pl = await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "patient-demo", password: "demo123" }) });
  const ptok = (await pl.json()).token;
  await jfetch(BASE + "/me/consent", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + ptok }, body: JSON.stringify({ scopes: { history: true, allergies: true, medications: true }, revoked: false }) });

  // boot the app in a DOM
  const window = new Window({ url: BASE + "/app/", settings: { disableJavaScriptFileLoading: true, disableCSSFileLoading: true } });
  const document = window.document;
  window.document.body.innerHTML = '<div id="app"></div>';
  window.fetch = jfetch;
  window.eval(fs.readFileSync(__dirname + "/cliniva/qr.js", "utf8"));
  window.eval(fs.readFileSync(__dirname + "/cliniva/api.js", "utf8"));
  window.eval(fs.readFileSync(__dirname + "/cliniva/app.js", "utf8"));
  await sleep(300);

  check("login screen renders", document.getElementById("login-form") !== null);

  // --- doctor login ---
  document.getElementById("login-user").value = "dr-demo";
  document.getElementById("login-pass").value = "demo123";
  document.getElementById("login-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await waitFor(() => document.getElementById("patient-select"), 15000, "patients loaded");
  check("doctor console renders with patient list", document.querySelector("#patient-select option") !== null);
  const pInfo = await waitFor(() => { const el = document.getElementById("patient-info"); return el ? (el.textContent || "") : null; }, 20000, "patient info");
  check("timeline loads patient record", pInfo.indexOf("Demo Patient") >= 0);
  check("penicillin allergy tag shown", document.getElementById("patient-info").textContent.indexOf("penicillin") >= 0);

  // --- consult with unsafe plan ---
  document.getElementById("transcript").value = "Patient has fever and throat pain since 2 days. Penicillin allergy last year. Plan: amoxicillin 500mg TDS x5d.";
  document.getElementById("consult-btn").dispatchEvent(new window.Event("click", { cancelable: true }));
  await waitFor(() => document.querySelector("#draft-card .safety-row"), 30000, "consult result");
  check("safety verdict CONFLICT shown", document.querySelector("#draft-card .safety-row").textContent.indexOf("CONFLICT") >= 0);
  check("SOAP note drafted", document.getElementById("consult-result").textContent.indexOf("pharyngitis") >= 0);
  await waitFor(() => document.querySelector(".modal .alt"), 10000, "conflict modal");
  check("conflict modal shows alternatives", document.querySelectorAll(".modal .alt").length >= 1);

  // --- apply alternative ---
  document.querySelector(".modal .alt").dispatchEvent(new window.Event("click", { cancelable: true }));
  const draftText = await waitFor(() => document.getElementById("draft-card").textContent.indexOf("azithromycin") >= 0 ? 1 : 0, 30000, "correction");
  check("draft switched to azithromycin", !!draftText);
  check("safety re-screened (no conflict)", document.querySelector("#draft-card .safety-row").textContent.indexOf("CONFLICT") < 0);

  // --- sign ---
  const confirm = document.getElementById("sign-confirm");
  if (confirm) confirm.checked = true;
  document.getElementById("sign-btn").dispatchEvent(new window.Event("click", { cancelable: true }));
  await waitFor(() => document.querySelector(".signed-card"), 30000, "signed card");
  check("prescription SIGNED with QR", document.querySelector(".signed-card img.qr") !== null || document.querySelector(".signed-card .qr-fallback svg") !== null);
  const link = document.querySelector('.signed-card a[href*="#/rx/"]');
  check("verify link present", !!link);
  const href = link ? link.getAttribute("href") : "";
  const m = href.match(/#\/rx\/([^?]+)\?h=([0-9a-f]+)/);
  check("verify link carries rx id + hash", !!m);
  check("FHIR + print actions on signed card", document.getElementById("fhir-btn") !== null && document.getElementById("print-btn") !== null);

  // --- FHIR bundle export (API-level) ---
  const dtok = window.sessionStorage.getItem("cliniva_token");
  const fh = await jfetch(BASE + "/fhir-rx/" + m[1], { headers: { Authorization: "Bearer " + dtok } });
  const fhj = await fh.json();
  check("FHIR bundle exportable", !!(fhj && fhj.fhir_bundle && (fhj.fhir_bundle.resourceType === "Bundle" || Array.isArray(fhj.fhir_bundle.entry))));

  // --- doctor extras: rx history + audit refresh after signing ---
  await waitFor(() => document.querySelector("#rxlist-card .rx-row"), 15000, "rx history");
  check("doctor sees issued prescriptions", document.querySelector("#rxlist-card .rx-row") !== null);
  await waitFor(() => (document.querySelector("#audit-card") || {}).textContent, 10000, "audit card");
  check("audit trail shows rx_sign event", document.querySelector("#audit-card").textContent.indexOf("rx_sign") >= 0);
  check("session expiry shown in header", document.querySelector(".topbar-exp") !== null);

  // --- patient portal ---
  document.getElementById("logout-btn").dispatchEvent(new window.Event("click", { cancelable: true }));
  await sleep(200);
  check("back at login after sign out", document.getElementById("login-form") !== null);
  document.getElementById("login-user").value = "patient-demo";
  document.getElementById("login-pass").value = "demo123";
  document.getElementById("login-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await waitFor(() => document.getElementById("consent-card"), 15000, "patient portal");
  check("patient profile shows name", document.getElementById("profile-card").textContent.indexOf("Demo Patient") >= 0);
  check("consent toggles present", document.getElementById("consent-history") !== null && document.getElementById("consent-medications") !== null);
  await waitFor(() => document.querySelector("#rx-card .rx-item"), 15000, "rx list");
  check("patient sees their e-prescription", document.querySelector("#rx-card .rx-item") !== null);
  check("prescription QR rendered for patient", document.querySelector("#rx-card .rx-item img.qr, #rx-card .rx-item .qr-fallback svg") !== null);

  // --- pharmacy verify + dispense ---
  window.location.hash = "#/rx/" + m[1] + "?h=" + m[2];
  window.dispatchEvent(new window.Event("hashchange"));
  await waitFor(() => document.querySelector(".status"), 15000, "pharmacy status");
  check("pharmacy shows VALID", document.querySelector(".status").textContent.indexOf("VALID") >= 0);
  check("pharmacy lists meds", document.querySelector(".pharm-card").textContent.indexOf("azithromycin") >= 0);
  document.getElementById("pharm-user").value = "pharm-demo";
  document.getElementById("pharm-pass").value = "demo123";
  document.getElementById("pharm-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await waitFor(() => document.querySelector(".status.status-blue"), 20000, "dispensed");
  check("pharmacy shows DISPENSED after dispense", document.querySelector(".status.status-blue") !== null);

  // --- tamper: wrong hash ---
  window.location.hash = "#/rx/" + m[1] + "?h=0000000000000000";
  window.dispatchEvent(new window.Event("hashchange"));
  await waitFor(() => document.querySelector(".status-red"), 15000, "tamper status");
  check("tampered hash rejected", document.querySelector(".status-red") !== null);

  // --- account security: change password (UI) ---
  window.API.logout();
  window.location.hash = "#/login";
  window.dispatchEvent(new window.Event("hashchange"));
  await sleep(300);
  document.getElementById("login-user").value = "patient-demo";
  document.getElementById("login-pass").value = "demo123";
  document.getElementById("login-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await waitFor(() => document.getElementById("consent-card"), 15000, "patient portal (2nd login)");
  check("account security card present", document.getElementById("account-card") !== null);
  document.getElementById("pw-old").value = "demo123";
  document.getElementById("pw-new").value = "rotated-pw-42";
  document.getElementById("pw-btn").dispatchEvent(new window.Event("click", { cancelable: true }));
  await waitFor(() => document.getElementById("pw-out").textContent.indexOf("Password updated") >= 0, 15000, "password changed");
  check("password change succeeds in UI", true);
  // old password must now fail, new one must work (API-level)
  const oldTry = await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "patient-demo", password: "demo123" }) });
  check("old password rejected after change", oldTry.status === 401);
  const newTry = await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "patient-demo", password: "rotated-pw-42" }) });
  check("new password accepted", newTry.status === 200);
  // restore the original password for future runs
  const rtok = (await newTry.json()).token;
  await jfetch(BASE + "/auth/change-password", { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + rtok }, body: JSON.stringify({ old_password: "rotated-pw-42", new_password: "demo123" }) });

  // --- brute-force lockout (uses a probe username so demo accounts stay usable) ---
  for (let i = 0; i < 5; i++) {
    await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "lockout-probe", password: "bad-" + i }) });
  }
  const lockedTry = await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "lockout-probe", password: "anything" }) });
  const lockedBody = await lockedTry.json();
  check("brute-force lockout engages", lockedTry.status === 401 && /locked/i.test(lockedBody.detail || ""));
  const okTry = await jfetch(BASE + "/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: "dr-demo", password: "demo123" }) });
  check("other accounts unaffected by lockout", okTry.status === 200);

  console.log(failures === 0 ? "\nALL E2E CHECKS PASSED" : "\n" + failures + " CHECKS FAILED");
  process.exit(failures === 0 ? 0 : 1);
})().catch(e => { console.error("E2E ERROR:", e.message); process.exit(2); });
