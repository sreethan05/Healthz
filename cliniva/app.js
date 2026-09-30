/* Cliniva application — production client for the Cliniva API. */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var micActive = false;
  var recog = null;

  /* ---------- utilities ---------- */

  var ENT = { "&": "amp", "<": "lt", ">": "gt", '"': "quot", "'": "#39" };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return "&" + ENT[c] + ";";
    });
  }

  function fmtDate(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + ", " +
           d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function jwtReg() {
    try {
      var part = API.token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(atob(part)).reg || "";
    } catch (e) { return ""; }
  }

  function jwtExp() {
    try {
      var part = API.token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(atob(part)).exp || 0;
    } catch (e) { return 0; }
  }

  function toast(msg, kind) {
    var t = document.createElement("div");
    t.setAttribute("role", "status");
    t.className = "toast" + (kind === "err" ? " toast-err" : "");
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(function () { t.classList.add("show"); });
    setTimeout(function () {
      t.classList.remove("show");
      setTimeout(function () { t.remove(); }, 350);
    }, 3200);
  }

  function banner(msg) {
    return '<div class="banner banner-err">' + esc(msg) + "</div>";
  }

  function statusPill(status) {
    var cls = status === "VALID" ? "pill-green" : status === "DISPENSED" ? "pill-blue" : "pill-grey";
    return '<span class="pill ' + cls + '">' + esc(status) + "</span>";
  }

  function verdictPill(v) {
    var cls = v === "NO_CONFLICT" ? "pill-green" : v === "CONFLICT" ? "pill-red" : "pill-amber";
    return '<span class="pill ' + cls + '">' + esc(String(v).replace(/_/g, " ")) + "</span>";
  }

  function spinner(label) {
    return '<div class="spinner-row"><span class="spinner"></span>' + esc(label || "Working…") + "</div>";
  }

  function qrHtml(pngB64, payload, big) {
    if (pngB64) {
      return '<img class="qr' + (big ? " qr-big" : "") + '" alt="Prescription QR" src="data:image/png;base64,' + pngB64 + '">';
    }
    if (window.qrcode && payload) {
      return '<div class="qr-fallback' + (big ? " qr-big" : "") + '" data-qr="' + esc(payload) + '"></div>';
    }
    return '<div class="qr-fallback qr-small">verify code: <b>' + esc((payload || "").split("h=").pop() || "—") + "</b></div>";
  }

  function renderClientQr(root) {
    (root.querySelectorAll(".qr-fallback[data-qr]") || []).forEach(function (el) {
      try {
        var qr = qrcode(0, "M");
        qr.addData(el.getAttribute("data-qr"));
        qr.make();
        el.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2 });
        el.removeAttribute("data-qr");
      } catch (e) { /* leave the verify code fallback */ }
    });
  }

  function handleErr(err, area) {
    var el = document.getElementById(area);
    if (el) el.innerHTML = banner(err && err.error ? err.error : "Something went wrong. Please retry.");
  }

  /* ---------- router ---------- */

  function route() {
    var h = location.hash || "#/login";
    if (h.indexOf("#/rx/") === 0) return renderPharmacy(h.slice(5));
    if (!API.authed) return renderLogin();
    if (h.indexOf("#/doctor") === 0 && API.role === "doctor") return renderDoctor();
    if (h.indexOf("#/patient") === 0 && API.role === "patient") return renderPatient();
    if (API.authed) {
      location.hash = API.role === "doctor" ? "#/doctor" : API.role === "patient" ? "#/patient" : "#/login";
      if (API.role === "pharmacist") {
        app.innerHTML = loginShell("Signed in as pharmacist. Open a prescription QR code to verify and dispense.");
        return;
      }
    }
    renderLogin();
  }

  window.addEventListener("hashchange", route);

  function loginShell(note) {
    return '<div class="shell"><div class="brand">Cliniva<span class="brand-dot">.</span></div>' +
      (note ? '<div class="note-card">' + esc(note) + "</div>" : "") + "</div>";
  }

  /* ---------- login ---------- */

  function renderLogin(msg) {
    app.innerHTML =
      '<div class="auth-wrap">' +
      '<div class="auth-card">' +
      '<div class="brand brand-lg">Cliniva<span class="brand-dot">.</span></div>' +
      '<div class="auth-sub">Consult-to-prescription platform — sign in to continue</div>' +
      (msg ? banner(msg) : "") +
      '<form id="login-form" autocomplete="off">' +
      '<label class="field"><span>Username</span><input id="login-user" required maxlength="100" autofocus aria-label="Username"></label>' +
      '<label class="field"><span>Password</span><input id="login-pass" type="password" required maxlength="1024" aria-label="Password"></label>' +
      '<button class="btn btn-primary btn-block" type="submit">Sign in</button>' +
      "</form>" +
      '<div class="auth-accounts">' +
      '<div class="auth-accounts-title">Evaluation accounts (password: <code>demo123</code>)</div>' +
      '<div class="chips">' +
      '<button class="chip" data-u="dr-demo">dr-demo · doctor</button>' +
      '<button class="chip" data-u="patient-demo">patient-demo · patient</button>' +
      '<button class="chip" data-u="pharm-demo">pharm-demo · pharmacist</button>' +
      "</div></div>" +
      '<div class="auth-foot">Sessions expire after 8 hours. All activity is audit-logged (DPDP-aligned).</div>' +
      "</div></div>";

    app.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () {
        app.querySelector("#login-user").value = c.getAttribute("data-u");
        app.querySelector("#login-pass").value = "demo123";
        app.querySelector("#login-form").requestSubmit();
      });
    });
    app.querySelector("#login-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var u = app.querySelector("#login-user").value.trim();
      var p = app.querySelector("#login-pass").value;
      var btn = app.querySelector(".btn-primary");
      btn.disabled = true; btn.textContent = "Signing in…";
      API.login(u, p).then(function (r) {
        toast("Signed in as " + r.role);
        location.hash = r.role === "doctor" ? "#/doctor" : r.role === "patient" ? "#/patient" : "#/login";
        if (r.role === "pharmacist") renderLogin("Signed in as pharmacist. Open a prescription QR code (or its link) to verify and dispense.");
      }, function (err) {
        renderLogin(err && err.error || "Sign-in failed");
      });
    });
  }

  function header(title, sub) {
    return '<div class="topbar"><div><div class="brand">Cliniva<span class="brand-dot">.</span></div>' +
      '<div class="topbar-sub">' + esc(title) + (sub ? " · " + esc(sub) : "") + "</div></div>" +
      '<div class="topbar-right"><span class="pill pill-outline">' + esc(API.role) + "</span>" +
      (jwtExp() ? '<span class="topbar-exp" title="Session expiry">session ' + Math.max(0, Math.round((jwtExp() - Date.now() / 1000) / 3600)) + "h</span>" : "") +
      '<span class="topbar-user">' + esc(API.user) + "</span>" +
      '<button class="btn btn-ghost" id="logout-btn">Sign out</button></div></div>';
  }

  function bindLogout() {
    app.querySelector("#logout-btn").addEventListener("click", function () {
      API.logout();
      location.hash = "#/login";
      toast("Signed out");
    });
  }

  /* ---------- doctor screen ---------- */

  var doc = { patientId: "", patients: [], timeline: null, consult: null, corrected: null, signed: null };

  function renderDoctor() {
    app.innerHTML = header("Doctor console", API.user) +
      '<main class="grid">' +
      '<section class="card" id="patient-card">' + spinner("Loading patients…") + '</section>' +
      '<section class="card" id="consult-card"></section>' +
      '<section class="card" id="draft-card"></section>' +
      '<section class="card" id="sign-card"></section>' +
      '<section class="card" id="rxlist-card"></section>' +
      '<section class="card" id="audit-card"></section>' +
      "</main>" +
      '<footer class="foot">Cliniva supports, does not replace, clinical judgment. Prescriptions are valid for 30 days. All actions are audit-logged.</footer>';
    bindLogout();
    renderConsultCard();
    loadDoctorRx();
    loadAudit();
    API.get("/patients").then(function (list) {
      doc.patients = list || [];
      doc.patientId = doc.patients.length ? doc.patients[0].patient_id : "";
      renderPatientCard();
    }, function (err) { handleErr(err, "patient-card"); });
  }

  function renderPatientCard() {
    var el = document.getElementById("patient-card");
    var opts = doc.patients.map(function (p) {
      return '<option value="' + esc(p.patient_id) + '"' + (p.patient_id === doc.patientId ? " selected" : "") + ">" +
        esc(p.patient_id) + " — " + esc(p.name) + "</option>";
    }).join("");
    el.innerHTML = '<h2>Patient</h2>' +
      '<select id="patient-select" class="input">' + opts + "</select>" +
      '<div id="patient-info">' + spinner("Loading record…") + "</div>";
    el.querySelector("#patient-select").addEventListener("change", function () {
      doc.patientId = this.value;
      loadPatientInfo();
    });
    loadPatientInfo();
  }

  function loadPatientInfo() {
    var info = document.getElementById("patient-info");
    info.innerHTML = spinner("Loading record…");
    API.get("/timeline/" + encodeURIComponent(doc.patientId)).then(function (t) {
      doc.timeline = t;
      var p = t.patient || {};
      var consentOk = t.history !== false && t.allergies !== false && t.medications !== false && !t.locked;
      var allergyTags = (t.allergies || []).map(function (a) {
        return '<span class="tag tag-red">' + esc(a) + "</span>";
      }).join("") || '<span class="tag tag-grey">none recorded</span>';
      var facts = (t.facts || []).slice(0, 3).map(function (f) {
        return '<li>' + esc(f.content || "") + "</li>";
      }).join("");
      info.innerHTML =
        (t.locked
          ? '<div class="banner banner-amber">Consent revoked — timeline locked. Ask the patient to re-consent in their app.</div>'
          : (!consentOk ? '<div class="banner banner-amber">Consent incomplete — consult and signing will be blocked until the patient grants history, allergy and medication consent.</div>' : "")) +
        '<div class="kv"><span>Name</span><b>' + esc(p.name || "—") + "</b></div>" +
        '<div class="kv"><span>Age</span><b>' + esc(p.age || "—") + "</b></div>" +
        '<div class="kv"><span>Conditions</span><b>' + esc((p.conditions || []).join(", ") || "—") + "</b></div>" +
        '<div class="kv"><span>Current meds</span><b>' + esc((p.current_meds || []).join(", ") || "—") + "</b></div>" +
        '<div class="kv"><span>Allergies</span><span>' + allergyTags + "</span></div>" +
        (facts ? '<div class="mem"><div class="mem-title">Memory (consent-filtered)</div><ul>' + facts + "</ul></div>" : "");
    }, function (err) {
      info.innerHTML = banner((err && err.error) || "Could not load patient record");
    });
  }

  function renderConsultCard() {
    var el = document.getElementById("consult-card");
    if (doc.signed) { el.innerHTML = ""; return; }
    var sr = window.SpeechRecognition || window.webkitSpeechRecognition;
    el.innerHTML = '<h2>Consult</h2>' +
      '<textarea id="transcript" class="input transcript" rows="7" placeholder="Type or dictate the consult — symptoms, history, assessment and planned medication. e.g. Fever and throat pain since 2 days. Penicillin allergy last year. Plan: amoxicillin 500mg TDS x5d.">' +
      esc(doc.transcript || "") + "</textarea>" +
      (sr ? '<div class="mic-row"><button class="btn btn-ghost" id="mic-btn">🎙 Dictate</button><span class="mic-hint">Browser speech-to-text (Chrome/Edge)</span></div>' : "") +
      '<button class="btn btn-primary" id="consult-btn">Analyse & draft note</button>' +
      '<div id="consult-result"></div>';
    if (sr) bindMic(el.querySelector("#transcript"));
    el.querySelector("#consult-btn").addEventListener("click", runConsult);
  }

  function bindMic(textarea) {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var btn = document.getElementById("mic-btn");
    btn.addEventListener("click", function () {
      if (micActive) { recog && recog.stop(); return; }
      recog = new SR();
      recog.continuous = true;
      recog.interimResults = false;
      recog.lang = "en-IN";
      recog.onresult = function (ev) {
        for (var i = ev.resultIndex; i < ev.results.length; i++) {
          if (ev.results[i].isFinal) {
            textarea.value = (textarea.value ? textarea.value + " " : "") + ev.results[i][0].transcript.trim();
          }
        }
      };
      recog.onend = function () { micActive = false; btn.classList.remove("mic-on"); btn.textContent = "🎙 Dictate"; };
      recog.onerror = function (ev) { toast("Microphone error: " + ev.error, "err"); };
      try { recog.start(); micActive = true; btn.classList.add("mic-on"); btn.textContent = "■ Stop"; } catch (e) { toast("Microphone unavailable", "err"); }
    });
  }

  function runConsult() {
    var ta = document.getElementById("transcript");
    var text = ta.value.trim();
    if (!text) { toast("Enter or dictate the consult first", "err"); return; }
    doc.transcript = text;
    var res = document.getElementById("consult-result");
    var btn = document.getElementById("consult-btn");
    btn.disabled = true; res.innerHTML = spinner("Recalling memory · drafting SOAP note · screening drug interactions…");
    API.post("/consult", { patient_id: doc.patientId, transcript: text }).then(function (r) {
      doc.consult = r; doc.corrected = null; doc.signed = null;
      btn.disabled = false;
      renderConsultResult(res, r, null);
      renderDraftCard();
      renderSignCard();
      if (r.safety && r.safety.verdict === "CONFLICT") showConflictModal(r.safety);
    }, function (err) {
      btn.disabled = false;
      res.innerHTML = banner((err && err.error) || "Consult failed");
      if (err && err.status === 403) res.innerHTML += '<div class="hint">The patient must grant history, allergy and medication consent in their app first.</div>';
    });
  }

  function currentDraft() {
    if (doc.corrected) return doc.corrected.updated;
    if (doc.consult) return doc.consult.draft;
    return null;
  }

  function currentSafety() {
    if (doc.corrected) return doc.corrected.safety_recheck;
    if (doc.consult) return doc.consult.safety;
    return null;
  }

  function currentBooking() {
    if (doc.corrected) return doc.corrected.booking;
    return null;
  }

  function renderConsultResult(el, r, extra) {
    var d = r.draft || {};
    var mem = r.memory || {};
    var memBits = ((mem.facts || []).slice(0, 2).map(function (f) { return f.content; }))
      .concat((mem.mental_models || []).slice(0, 1).map(function (m) { return m.content; }));
    el.innerHTML = (extra || "") +
      (d.memory_used ? '<div class="mem"><div class="mem-title">Memory used</div><div class="mem-text">' + esc(d.memory_used) + "</div></div>" : "") +
      soapRow("S", d.subjective) + soapRow("O", d.objective) + soapRow("A", d.assessment) + soapRow("P", d.plan) +
      (memBits.length ? '<div class="hint">Recalled: ' + esc(memBits.join(" · ")) + "</div>" : "");
  }

  function soapRow(k, v) {
    return '<div class="soap-row"><span class="soap-key">' + k + "</span><span>" + esc(v || "—") + "</span></div>";
  }

  function renderDraftCard() {
    var el = document.getElementById("draft-card");
    var d = currentDraft(), safety = currentSafety();
    if (!d) { el.innerHTML = ""; return; }
    var meds = (d.draft_meds || []).join("\n");
    var v = safety ? safety.verdict : null;
    el.innerHTML = '<h2>Draft prescription</h2>' +
      '<div class="safety-row"><span>Safety screen</span>' + verdictPill(v) + "</div>" +
      '<label class="field"><span>Medication lines (edit before signing — one per line)</span>' +
      '<textarea id="meds" class="input" rows="' + Math.max(2, (d.draft_meds || []).length) + '">' + esc(meds) + "</textarea></label>" +
      '<div class="hint">' + esc(d.status || "") + "</div>" +
      (v === "INSUFFICIENT_DATA"
        ? '<div class="banner banner-amber">Interaction screening is incomplete. Review the full regimen and confirm in the signing panel before signing.</div>'
        : "") +
      (currentBooking()
        ? '<div class="booking">Suggested follow-up: <b>' + esc(currentBooking().suggested) + "</b> via " + esc(currentBooking().channel) +
          ' <button class="btn btn-ghost btn-sm" id="remind-btn">Send reminder</button></div>'
        : "");
    var rb = el.querySelector("#remind-btn");
    if (rb) rb.addEventListener("click", function () {
      rb.disabled = true;
      API.post("/booking/remind", { channel: "sms", to: "patient on file", text: "Cliniva follow-up reminder as suggested." })
        .then(function () { toast("Reminder queued"); }, function () { rb.disabled = false; });
    });
  }

  function renderSignCard() {
    var el = document.getElementById("sign-card");
    var safety = currentSafety();
    if (!safety || doc.signed) { el.innerHTML = ""; return; }
    var needConfirm = safety.verdict !== "NO_CONFLICT";
    el.innerHTML = '<h2>Sign prescription</h2>' +
      '<label class="field"><span>Confirm patient ID</span><input id="sign-patient" class="input" value="' + esc(doc.patientId) + '"></label>' +
      (needConfirm
        ? '<label class="check"><input type="checkbox" id="sign-confirm"><span>I have reviewed the full regimen and the safety notes above</span></label>'
        : "") +
      '<button class="btn btn-primary" id="sign-btn">Sign & issue e-prescription</button>' +
      '<div id="sign-result"></div>';
    el.querySelector("#sign-btn").addEventListener("click", function () {
      var pid = el.querySelector("#sign-patient").value.trim();
      if (pid !== doc.patientId) { toast("Patient ID does not match the selected patient", "err"); return; }
      var chk = el.querySelector("#sign-confirm");
      if (needConfirm && chk && !chk.checked) { toast("Please confirm the regimen review first", "err"); return; }
      var meds = document.getElementById("meds").value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
      if (!meds.length) { toast("At least one medication line is required", "err"); return; }
      var d = currentDraft();
      var btn = el.querySelector("#sign-btn");
      btn.disabled = true;
      var out = document.getElementById("sign-result");
      out.innerHTML = spinner("Screening final regimen · signing with clinician identity…");
      API.post("/sign", {
        patient_id: pid,
        doctor_id: API.user,
        doctor_reg: jwtReg(),
        meds: meds,
        soap: { assessment: d.assessment, plan: d.plan },
        clinician_confirmed_insufficient_data: !!(needConfirm && chk && chk.checked)
      }).then(function (r) {
        doc.signed = r;
        renderSignedResult(out, r);
        document.getElementById("draft-card").innerHTML = "";
        document.getElementById("consult-card").innerHTML = "";
        loadDoctorRx();
        loadAudit();
      }, function (err) {
        btn.disabled = false;
        var safetyDetail = err && err.detail && err.detail.safety;
        out.innerHTML = banner((err && err.error) || "Signing failed") +
          (safetyDetail && safetyDetail.findings
            ? safetyDetail.findings.map(function (f) {
                return '<div class="finding"><b>' + esc(f.pair.join(" × ")) + "</b> — " + esc(f.mechanism || "") + "</div>";
              }).join("")
            : "");
      });
    });
  }

  function renderSignedResult(el, r) {
    var b = r.body || {};
    el.innerHTML = '<div class="signed-card">' +
      '<div class="signed-head"><span class="pill pill-green">SIGNED</span>' +
      '<div class="kv"><span>Rx ID</span><b>' + esc(String(r.rx_id).slice(0, 8).toUpperCase()) + "</b></div>" +
      '<div class="kv"><span>Doctor</span><b>' + esc(b.doctor_id) + " (" + esc(b.doctor_reg) + ")</b></div>" +
      '<div class="kv"><span>Issued</span><b>' + fmtTime(b.issued_at) + "</b></div>" +
      '<div class="kv"><span>Valid until</span><b>' + fmtDate(b.issued_at + 30 * 86400) + "</b></div></div>" +
      '<div class="qr-wrap">' + qrHtml(r.qr_png_base64, r.qr_payload, true) +
      '<div class="hint">Pharmacy scans this QR to verify and dispense.<br><a href="' + esc(r.qr_payload) + '" target="_blank" rel="noopener">Open verify link</a> · hash <code>' + esc(String(r.hash).slice(0, 16)) + "</code></div></div>" +
      '<div class="signed-actions">' +
      '<button class="btn btn-ghost" id="fhir-btn">Export FHIR</button>' +
      '<button class="btn btn-ghost" id="print-btn">Print</button>' +
      '<button class="btn btn-ghost" id="new-consult">New consult</button></div></div>';
    renderClientQr(el);
    el.querySelector("#new-consult").addEventListener("click", function () {
      doc.transcript = ""; doc.consult = null; doc.corrected = null; doc.signed = null;
      renderDoctor();
    });
    var fb = el.querySelector("#fhir-btn");
    if (fb) fb.addEventListener("click", function () { exportFhir(r.rx_id, fb); });
    var pb = el.querySelector("#print-btn");
    if (pb) pb.addEventListener("click", function () { window.print(); });
  }

  /* safety conflict modal */
  function showConflictModal(safety) {
    var findings = (safety.findings || []).map(function (f) {
      return '<div class="finding"><div class="finding-pair">' + esc(f.pair.join(" × ")) +
        ' <span class="pill pill-red">' + esc(f.severity) + "</span></div>" +
        "<div>" + esc(f.mechanism || "") + "</div>" +
        '<div class="hint">Sources: ' + esc((f.sources || []).join("; ")) +
        (f.citations && f.citations[0] ? ' · <a href="' + esc(f.citations[0]) + '" target="_blank" rel="noopener">DailyMed</a>' : "") + "</div></div>";
    }).join("");
    var alts = (safety.alternatives || []).map(function (a, i) {
      return '<button class="alt" data-alt="' + esc(a.drug) + '"><b>' + esc(a.drug) + "</b><span>" + esc(a.why) + "</span></button>";
    }).join("") || '<div class="hint">No structured alternative available — choose manually.</div>';
    var m = document.createElement("div");
    m.className = "modal-back";
    m.innerHTML = '<div class="modal">' +
      '<div class="modal-head"><span class="pill pill-red">CRITICAL — ' + esc(safety.severity) + "</span><h3>Unsafe medication detected</h3></div>" +
      findings +
      '<div class="alt-title">Safer alternatives</div>' + alts +
      '<button class="btn btn-ghost btn-sm" id="conflict-close">Review manually</button></div>';
    document.body.appendChild(m);
    m.querySelector("#conflict-close").addEventListener("click", function () { m.remove(); });
    m.querySelectorAll(".alt").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var drug = btn.getAttribute("data-alt");
        m.remove();
        var res = document.getElementById("consult-result");
        res.insertAdjacentHTML("afterbegin", spinner("Applying correction & re-screening…"));
        API.post("/correct", {
          patient_id: doc.patientId,
          draft: doc.consult.draft,
          correction: "Safety conflict: " + drug + " — switch to " + drug
        }).then(function (r) {
          doc.corrected = r;
          renderConsultResult(res, { draft: r.updated, memory: r.memory }, '<div class="banner banner-ok">Prescription changed to ' + esc(drug) + " — safety re-screened.</div>");
          renderDraftCard();
          renderSignCard();
          toast("Draft updated: " + drug);
        }, function (err) { toast((err && err.error) || "Correction failed", "err"); });
      });
    });
  }

  /* ---------- patient screen ---------- */

  var pat = { me: null, rx: [] };

  function renderPatient() {
    app.innerHTML = header("Patient portal", API.user) +
      '<main class="grid">' +
      '<section class="card" id="profile-card">' + spinner("Loading profile…") + '</section>' +
      '<section class="card" id="consent-card"></section>' +
      '<section class="card" id="rx-card"></section>' +
      "</main>" +
      '<footer class="foot">You control your data (DPDP). Revoking consent immediately locks doctor access to the matching scope.</footer>';
    bindLogout();
    API.get("/me").then(function (me) {
      pat.me = me;
      renderProfileCard();
      renderConsentCard(me);
      return API.get("/me/rx");
    }, function (err) { handleErr(err, "profile-card"); })
    .then(function (rx) {
      pat.rx = rx || [];
      renderRxCard();
    }, function (err) {
      document.getElementById("rx-card").innerHTML =
        '<h2>Prescriptions</h2>' + banner((err && err.error) || "Could not load prescriptions") +
        '<div class="hint">Grant medication consent above to see your prescriptions.</div>';
    });
  }

  function renderProfileCard() {
    var me = pat.me;
    document.getElementById("profile-card").innerHTML = '<h2>' + esc(me.name) + "</h2>" +
      '<div class="kv"><span>Patient ID</span><b>' + esc(me.patient_id) + "</b></div>" +
      '<div class="kv"><span>Age</span><b>' + esc(me.age || "—") + "</b></div>" +
      '<div class="kv"><span>Conditions</span><b>' + esc((me.conditions || []).join(", ") || "—") + "</b></div>" +
      '<div class="kv"><span>Current meds</span><b>' + esc((me.current_meds || []).join(", ") || "—") + "</b></div>" +
      '<div class="kv"><span>Allergies</span><b>' + esc((me.allergies || []).join(", ") || "none recorded") + "</b></div>" +
      (me.preferences ? '<div class="kv"><span>Follow-up</span><b>' + esc((me.preferences.followup_days || []).join("/")) + " " + esc(me.preferences.slot || "") + " · " + esc(me.preferences.channel || "") + "</b></div>" : "");
  }

  function renderConsentCard(me) {
    var c = me.consent || {};
    document.getElementById("consent-card").innerHTML = '<h2>Consent (DPDP)</h2>' +
      '<p class="hint">Choose what doctors may access during consultations. Revoking a scope hides the matching records immediately.</p>' +
      consentToggle("history", "Clinical history & preferences", c.history) +
      consentToggle("allergies", "Allergy records", c.allergies) +
      consentToggle("medications", "Medication records & e-prescriptions", c.medications) +
      '<button class="btn btn-primary" id="consent-save">Save consent</button>' +
      '<div id="consent-out"></div>';
    document.getElementById("consent-save").addEventListener("click", function () {
      var scopes = {};
      ["history", "allergies", "medications"].forEach(function (k) {
        scopes[k] = !!(document.getElementById("consent-" + k) || {}).checked;
      });
      var out = document.getElementById("consent-out");
      out.innerHTML = spinner("Saving…");
      API.post("/me/consent", { scopes: scopes, revoked: false }).then(function () {
        out.innerHTML = '<div class="banner banner-ok">Consent saved. Doctors can now access: ' +
          Object.keys(scopes).filter(function (k) { return scopes[k]; }).join(", ") + ".</div>";
        toast("Consent updated");
      }, function (err) { out.innerHTML = banner((err && err.error) || "Failed to save consent"); });
    });
  }

  function consentToggle(key, label, on) {
    return '<label class="toggle-row"><span>' + esc(label) + "</span>" +
      '<span class="toggle"><input type="checkbox" id="consent-' + key + '"' + (on ? " checked" : "") + '><i></i></span></label>';
  }

  function renderRxCard() {
    var el = document.getElementById("rx-card");
    if (!pat.rx.length) {
      el.innerHTML = '<h2>Prescriptions</h2><div class="hint">No prescriptions issued yet. After your doctor signs one, it appears here with its QR code.</div>';
      return;
    }
    el.innerHTML = '<h2>Prescriptions</h2>' + pat.rx.map(function (r, i) {
      return '<div class="rx-item">' +
        '<div class="rx-head">' + statusPill(r.status) +
        '<div class="kv"><span>Issued</span><b>' + fmtDate(r.issued_at) + " · " + esc(r.doctor_id) + "</b></div>" +
        '<div class="kv"><span>Valid until</span><b>' + fmtDate(r.expires_at) + "</b></div>" +
        '<button class="btn btn-ghost btn-sm rx-print" title="Print prescription">Print</button></div>' +
        '<ul class="med-list">' + (r.meds || []).map(function (m) { return "<li>" + esc(m) + "</li>"; }).join("") + "</ul>" +
        '<div class="qr-wrap">' + qrHtml(r.qr_png_base64, r.qr_payload) +
        '<div class="hint">Show this QR at the pharmacy. <a href="' + esc(r.qr_payload) + '" target="_blank" rel="noopener">Open verify link</a></div></div>' +
        "</div>";
    }).join("");
    renderClientQr(el);
    el.querySelectorAll(".rx-print").forEach(function (b) {
      b.addEventListener("click", function () { window.print(); });
    });
  }

  /* ---------- doctor extras: rx history, audit, FHIR export ---------- */

  function loadDoctorRx() {
    var el = document.getElementById("rxlist-card");
    if (!el) return;
    API.get("/doctor/rx").then(function (list) {
      list = list || [];
      if (!list.length) {
        el.innerHTML = '<h2>Issued prescriptions</h2><div class="hint">Nothing issued yet. Signed prescriptions appear here with status and FHIR export.</div>';
        return;
      }
      el.innerHTML = '<h2>Issued prescriptions (' + list.length + ')</h2>' + list.slice(0, 6).map(function (r) {
        return '<div class="rx-row">' + statusPill(r.status) +
          '<div class="rx-row-main"><b>' + esc(r.patient_name || r.patient_id) + '</b>' +
          '<span class="rx-row-meds">' + esc((r.meds || []).join("; ")) + '</span></div>' +
          '<span class="rx-row-side">' + fmtDate(r.issued_at) + '</span>' +
          '<button class="btn btn-ghost btn-sm" data-fhir="' + esc(r.rx_id) + '">FHIR</button>' +
          '</div>';
      }).join("");
      el.querySelectorAll("[data-fhir]").forEach(function (b) {
        b.addEventListener("click", function () { exportFhir(b.getAttribute("data-fhir"), b); });
      });
    }, function () { /* panel stays quiet on failure */ });
  }

  function loadAudit() {
    var el = document.getElementById("audit-card");
    if (!el) return;
    API.get("/audit?limit=15").then(function (rows) {
      rows = rows || [];
      if (!rows.length) {
        el.innerHTML = '<h2>Audit trail</h2><div class="hint">No activity recorded yet.</div>';
        return;
      }
      el.innerHTML = '<h2>Audit trail</h2><div class="audit-list">' + rows.slice().reverse().map(function (r) {
        return '<div class="audit-row"><span class="audit-evt">' + esc(r.event) + '</span>' +
          '<span class="audit-meta">' + esc(r.actor || "—") + (r.patient_id ? " · " + esc(r.patient_id) : "") + '</span>' +
          '<span class="audit-ts">' + fmtTime(r.ts) + '</span></div>';
      }).join("") + "</div>";
    }, function () { /* panel stays quiet on failure */ });
  }

  function exportFhir(rxId, btn) {
    if (btn) btn.disabled = true;
    API.get("/fhir-rx/" + encodeURIComponent(rxId)).then(function (r) {
      if (!r || !r.found || !r.valid) {
        toast("FHIR export unavailable for this prescription", "err");
        if (btn) btn.disabled = false;
        return;
      }
      var text = JSON.stringify(r.fhir_bundle, null, 2);
      try {
        var blob = new Blob([text], { type: "application/fhir+json" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "cliniva-rx-" + String(rxId).slice(0, 8) + ".json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        toast("FHIR bundle exported");
      } catch (e) {
        toast("FHIR download not supported in this browser", "err");
      }
      if (btn) btn.disabled = false;
    }, function (err) {
      toast((err && err.error) || "FHIR export failed", "err");
      if (btn) btn.disabled = false;
    });
  }

  /* ---------- pharmacy screen (public) ---------- */

  var pharmData = null;

  function renderPharmacy(frag) {
    var m = frag.match(/^([^?]+)\?h=([^&]+)/);
    var rxId = m ? m[1] : frag;
    var h = m ? m[2] : "";
    app.innerHTML = '<div class="pharm-wrap">' +
      '<div class="brand brand-lg">Cliniva<span class="brand-dot">.</span></div>' +
      '<div class="auth-sub">Pharmacy e-prescription verifier</div>' +
      '<div class="pharm-card" id="pharm-card">' + spinner("Verifying signature…") + "</div>" +
      '<div class="foot">Prescriptions are cryptographically signed. Status changes (VALID → DISPENSED) are tracked server-side. Supports, does not replace clinical judgment.</div>' +
      "</div>";
    API.get("/public/rx/" + encodeURIComponent(rxId) + (h ? "?h=" + encodeURIComponent(h) : "")).then(function (r) {
      pharmData = r;
      renderPharmResult(r, rxId);
    }, function (err) {
      document.getElementById("pharm-card").innerHTML = banner((err && err.error) || "Verification failed");
    });
  }

  function renderPharmResult(r, rxId) {
    var el = document.getElementById("pharm-card");
    if (!r.found) {
      el.innerHTML = '<div class="status status-red">UNKNOWN</div><div class="hint">No prescription with this ID exists on this server.</div>';
      return;
    }
    if (!r.valid) {
      el.innerHTML = '<div class="status status-red">NOT VERIFIED</div>' +
        '<div class="banner banner-err">' + esc(r.reason || "Signature verification failed") + "</div>" +
        '<div class="hint"><b>Do not dispense.</b> Ask the patient to contact their doctor.</div>';
      return;
    }
    var isPharmacist = API.role === "pharmacist" && API.authed;
    var canDispense = r.status === "VALID";
    el.innerHTML =
      '<div class="status status-' + (r.status === "VALID" ? "green" : r.status === "DISPENSED" ? "blue" : "grey") + '">' + esc(r.status) + "</div>" +
      (r.status === "DISPENSED" ? '<div class="hint">Dispensed on ' + fmtTime(r.dispensed_at || r.issued_at) + "</div>" : "") +
      (r.status === "EXPIRED" ? '<div class="hint">This prescription is no longer valid (30-day limit).</div>' : "") +
      '<div class="kv"><span>Rx</span><b>' + esc(String(r.rx_id).slice(0, 8).toUpperCase()) + "</b></div>" +
      '<div class="kv"><span>Doctor</span><b>' + esc(r.doctor_id) + " (" + esc(r.doctor_reg) + ")</b></div>" +
      '<div class="kv"><span>Issued</span><b>' + fmtTime(r.issued_at) + "</b></div>" +
      '<div class="kv"><span>Expires</span><b>' + fmtDate(r.expires_at) + "</b></div>" +
      '<div class="med-title">Medications</div>' +
      '<ul class="med-list">' + (r.meds || []).map(function (mm) { return "<li>" + esc(mm) + "</li>"; }).join("") + "</ul>" +
      (canDispense
        ? (isPharmacist
            ? '<button class="btn btn-primary btn-block" id="dispense-btn">Mark as dispensed</button>'
            : '<div class="pharm-login" id="pharm-login"><div class="alt-title">Pharmacist sign-in to dispense</div>' +
              '<form id="pharm-form"><input class="input" id="pharm-user" placeholder="Username" required>' +
              '<input class="input" id="pharm-pass" type="password" placeholder="Password" required>' +
              '<button class="btn btn-primary btn-block" type="submit">Sign in & dispense</button></form></div>')
        : "") +
      '<div id="dispense-out"></div>';
    var dbtn = el.querySelector("#dispense-btn");
    if (dbtn) {
      dbtn.addEventListener("click", function () {
        dbtn.disabled = true;
        doDispense(rxId, document.getElementById("dispense-out"));
      });
    }
    var pform = el.querySelector("#pharm-form");
    if (pform) {
      pform.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var out = document.getElementById("dispense-out");
        out.innerHTML = spinner("Signing in…");
        API.login(el.querySelector("#pharm-user").value.trim(), el.querySelector("#pharm-pass").value).then(function (res) {
          if (res.role !== "pharmacist") { throw { error: "This action requires a pharmacist account." }; }
          return doDispense(rxId, out);
        }, function (err) { out.innerHTML = banner((err && err.error) || "Sign-in failed"); });
      });
    }
  }

  function doDispense(rxId, out) {
    out.innerHTML = spinner("Recording dispense…");
    API.post("/dispense/" + encodeURIComponent(rxId), {}).then(function (r) {
      if (pharmData) {
        pharmData.status = "DISPENSED";
        pharmData.dispensed_at = r.dispensed_at;
        renderPharmResult(pharmData, rxId);
      }
      toast("Prescription marked as dispensed");
    }, function (err) {
      out.innerHTML = banner((err && err.error) || "Dispense failed");
      var dbtn = document.querySelector("#dispense-btn");
      if (dbtn) dbtn.disabled = false;
    });
  }

  /* boot */
  route();
})();
