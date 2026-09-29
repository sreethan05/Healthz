(function () {
  "use strict";

  var app = document.getElementById("app");

  /* ---------- session (frontend demo only — no real security) ---------- */

  function getRole() { return sessionStorage.getItem("cliniva_role"); }
  function getPatientId() { return sessionStorage.getItem("cliniva_patient_id"); }

  function loginAs(role) {
    sessionStorage.setItem("cliniva_role", role);
    if (role === "patient") sessionStorage.setItem("cliniva_patient_id", "P-1024");
    location.hash = role === "doctor" ? "#/doctor" : "#/patient?id=P-1024";
  }

  function logout() {
    sessionStorage.removeItem("cliniva_role");
    sessionStorage.removeItem("cliniva_patient_id");
    location.hash = "#/login";
  }

  /* ---------- router ---------- */

  function parseRoute() {
    var raw = location.hash.replace(/^#/, "") || "/login";
    var parts = raw.split("?");
    var path = parts[0];
    var query = {};
    if (parts[1]) {
      parts[1].split("&").forEach(function (kv) {
        var p = kv.split("=");
        query[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || "");
      });
    }
    return { path: path, query: query };
  }

  var docState = null; // consult state survives re-render while on screen

  function stopStream() {
    if (docState && docState.stream) {
      docState.stream.stop();
      docState.stream = null;
      if (docState.phase === "streaming" || docState.phase === "paused") {
        docState.phase = "draft"; // consult is interrupted -> show draft
      }
    }
  }

  function navigate() {
    stopStream();
    var r = parseRoute();
    if (r.path === "/login") { renderLogin(); return; }
    if (r.path === "/doctor") {
      if (getRole() !== "doctor") { renderDenied("Only a doctor can open the consult console."); return; }
      renderDoctor();
      return;
    }
    if (r.path === "/patient") {
      if (getRole() !== "patient") { renderDenied("Only the patient can open this page."); return; }
      var id = r.query.id || "";
      if (id !== getPatientId()) { renderDenied("This patient ID does not match your session."); return; }
      renderPatient(id);
      return;
    }
    var m = r.path.match(/^\/rx\/([A-Za-z0-9-]+)$/);
    if (m) { renderPharmacy(m[1]); return; }
    renderDenied("Page not found.");
  }

  window.addEventListener("hashchange", navigate);

  /* ---------- shared bits ---------- */

  function topBar(name, role, extraId) {
    var extra = extraId
      ? '<span class="topbar-id">Patient ' + extraId + "</span>"
      : "";
    return (
      '<header class="topbar">' +
      '<div class="topbar-left"><strong>' + name + "</strong>" + extra + "</div>" +
      '<div class="topbar-right">' +
      '<span class="badge badge-' + role + '">' + (role === "doctor" ? "Doctor" : "Patient") + "</span>" +
      '<button class="btn btn-ghost" id="logout-btn">Logout</button>' +
      "</div></header>"
    );
  }

  function wireLogout() {
    var b = document.getElementById("logout-btn");
    if (b) b.addEventListener("click", logout);
  }

  /* Real scannable QR (qrcode-generator, MIT — see cliniva/qr.js).
   * When served over http(s) the code encodes the full verify URL so a phone
   * camera opens the pharmacy screen; from file:// it falls back to the short
   * code text. Whole tile stays a link. */
  function qrContent(value) {
    var base = location.href.split("#")[0];
    return /^https?:/i.test(base) ? base + value : value;
  }

  function qrTile(value, sizeClass) {
    var cls = "qr " + (sizeClass || "");
    if (typeof qrcode === "function") {
      return (
        '<a class="' + cls + '" href="' + value + '" aria-label="Open pharmacy verify link">' +
        '<canvas data-qr="' + qrContent(value) + '"></canvas></a>'
      );
    }
    /* fallback: deterministic pseudo-QR (only if the lib failed to load) */
    var seed = 0;
    for (var i = 0; i < value.length; i++) seed = (seed * 31 + value.charCodeAt(i)) >>> 0;
    function rnd() { seed = (1103515245 * seed + 12345) >>> 0; return (seed >>> 16) / 65536; }
    var cells = "";
    for (var y = 0; y < 21; y++) {
      for (var x = 0; x < 21; x++) {
        var finder =
          (x < 7 && y < 7) || (x >= 14 && y < 7) || (x < 7 && y >= 14);
        var on;
        if (finder) {
          var fx = x % 14, fy = y % 14;
          var ring = Math.max(Math.abs(fx - 3), Math.abs(fy - 3));
          on = ring !== 2;
        } else {
          on = rnd() > 0.5;
        }
        if (on) cells += '<i style="grid-column:' + (x + 1) + ";grid-row:" + (y + 1) + '"></i>';
      }
    }
    return (
      '<a class="' + cls + '" href="' + value + '" aria-label="Open pharmacy verify link">' +
      '<span class="qr-grid">' + cells + "</span></a>"
    );
  }

  /* draw every pending QR canvas on the page */
  function paintQrTiles() {
    if (typeof qrcode !== "function") return;
    var tiles = document.querySelectorAll("canvas[data-qr]");
    for (var i = 0; i < tiles.length; i++) {
      var c = tiles[i];
      if (c.getAttribute("data-painted")) continue;
      try {
        var qr = qrcode(0, "M");
        qr.addData(c.getAttribute("data-qr"));
        qr.make();
        var n = qr.getModuleCount();
        var quiet = 4, scale = 8, W = (n + quiet * 2) * scale;
        c.width = W;
        c.height = W;
        var ctx = c.getContext("2d");
        if (!ctx) continue; /* canvas unsupported (e.g. test env) */
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, W, W);
        ctx.fillStyle = "#26211b";
        for (var r = 0; r < n; r++) {
          for (var col = 0; col < n; col++) {
            if (qr.isDark(r, col)) {
              ctx.fillRect((col + quiet) * scale, (r + quiet) * scale, scale, scale);
            }
          }
        }
        c.setAttribute("data-painted", "1");
      } catch (e) {
        /* leave tile empty; the link itself still works */
      }
    }
  }

  function chip(text, tone) {
    return '<span class="chip chip-' + tone + '">' + text + "</span>";
  }

  /* ---------- toast ---------- */

  var toastTimer = null;

  function toast(msg) {
    var el = document.getElementById("toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 2200);
  }

  /* ---------- transcript typing indicator ---------- */

  function addTyping() {
    removeTyping();
    var t = document.getElementById("transcript");
    if (t) {
      t.insertAdjacentHTML("beforeend",
        '<div class="bbl bbl-dr bbl-typing" aria-hidden="true"><span class="dots"><i></i><i></i><i></i></span></div>');
    }
  }

  function removeTyping() {
    var el = document.querySelector("#transcript .bbl-typing");
    if (el) el.remove();
  }

  /* ---------- login ---------- */

  function renderLogin() {
    app.innerHTML =
      '<main class="center-wrap">' +
      '<div class="card login-card">' +
      '<h1 class="brand">Cliniva</h1>' +
      '<p class="muted">Consult-to-prescription demo — mocked data only.</p>' +
      '<button class="btn btn-primary btn-block" id="login-doctor">Log in as Doctor</button>' +
      '<button class="btn btn-secondary btn-block" id="login-patient">Log in as Patient</button>' +
      "</div></main>";
    document.getElementById("login-doctor").addEventListener("click", function () { loginAs("doctor"); });
    document.getElementById("login-patient").addEventListener("click", function () { loginAs("patient"); });
  }

  /* ---------- access denied ---------- */

  function renderDenied(reason) {
    app.innerHTML =
      '<main class="center-wrap">' +
      '<div class="card denied-card">' +
      '<h1>Access denied</h1>' +
      '<p class="muted">' + reason + "</p>" +
      '<button class="btn btn-primary" id="back-login">Back to login</button>' +
      "</div></main>";
    document.getElementById("back-login").addEventListener("click", function () { location.hash = "#/login"; });
  }

  /* ---------- doctor console ---------- */

  function resetDocState() {
    docState = {
      phase: "pre-start", // pre-start | streaming | paused | draft | signed
      pendingDrug: "Amoxicillin",
      started: false,
      shown: [], // transcript lines shown so far (objects {speaker,text,flagged})
      stream: null
    };
  }

  function renderDoctor() {
    if (!docState) resetDocState();
    var p = getMockPatient("P-1024");
    var s = docState;

    var patientCard =
      '<aside class="card patient-card">' +
      '<div class="patient-head"><h2>' + p.name + '</h2><span class="muted">' + p.age + " yrs</span></div>" +
      '<div class="allergy-row">' + chip("⚠ Penicillin allergy", "danger") + "</div>" +
      "<details><summary>Patient details</summary>" +
      '<div class="memory-label">From Hindsight memory — mock only</div>' +
      "<h3>Past visit</h3>" +
      '<ul class="plain-list">' +
      p.pastVisits.map(function (v) { return "<li>" + v.reason + " · " + v.date + "</li>"; }).join("") +
      "</ul></details>" +
      "</aside>";

    var transcriptHtml = s.shown.length
      ? s.shown.map(function (l) { return bubble(l); }).join("")
      : '<p class="muted transcript-empty">Transcript will appear here.</p>';

    var right =
      '<section class="console-col">' +
      '<div class="safety-strip" id="safety-strip">' + safetyStripHtml() + "</div>" +
      '<div class="card transcript-card" id="transcript-card">' +
      '<div class="transcript" id="transcript">' + transcriptHtml + "</div>" +
      '<div class="console-actions">' +
      '<button class="btn btn-primary" id="start-btn"' + (s.started ? " disabled" : "") + ">Start Consult</button>" +
      '<button class="btn btn-secondary" id="end-btn"' + (s.started && s.phase !== "draft" ? "" : " disabled") + ">End Consult</button>" +
      "</div></div>" +
      '<div id="after-consult"></div>' +
      "</section>";

    app.innerHTML = topBar("Dr. Mehta", "doctor", "P-1024") +
      '<main class="doctor-grid">' + patientCard + right + "</main>";
    wireLogout();

    document.getElementById("start-btn").addEventListener("click", startConsult);
    document.getElementById("end-btn").addEventListener("click", endConsult);

    if (s.phase === "draft" || s.phase === "signed") {
      document.getElementById("transcript-card").style.display = "none";
      renderDraft();
    }
    if (s.phase === "signed") { renderSignedPanel(s.signed); }
    paintQrTiles();
  }

  function bubble(l) {
    return (
      '<div class="bbl bbl-' + l.speaker.toLowerCase() + (l.flagged ? " bbl-flagged" : "") + '">' +
      "<strong>" + (l.speaker === "Dr" ? "Dr. Mehta" : "Ravi") + ":</strong> " + l.text + "</div>"
    );
  }

  function safetyStripHtml() {
    var s = docState;
    if (s.phase === "pre-start") return '<span class="muted">Scanned just now — waiting for consult to start.</span>';
    if (s.phase === "draft" || s.phase === "signed") {
      return s.pendingDrug === "Amoxicillin"
        ? chip("⚠ Safety check flagged", "danger")
        : chip("Safety check passed", "ok");
    }
    return s.pendingDrug === "Amoxicillin" && s.started
      ? chip("Scanned just now · monitoring", "ok")
      : chip("Scanned just now · monitoring", "ok");
  }

  function refreshSafetyStrip() {
    var el = document.getElementById("safety-strip");
    if (el) el.innerHTML = safetyStripHtml();
  }

  function startConsult() {
    var s = docState;
    s.started = true;
    s.phase = "streaming";
    document.getElementById("start-btn").disabled = true;
    document.getElementById("end-btn").disabled = false;
    if (!s.shown.length) document.getElementById("transcript").innerHTML = "";
    refreshSafetyStrip();
    addTyping();

    s.stream = streamMockTranscript(
      function (idx, line) {
        removeTyping();
        var shownLine = { speaker: line.speaker, text: line.text, flagged: false };
        var safety = checkMockSafety(line);
        if (safety.status === "critical") {
          shownLine.flagged = true;
          s.shown.push(shownLine);
          appendBubble(shownLine);
          haltForPopup(line, safety, s.shown.length - 1);
        } else {
          s.shown.push(shownLine);
          appendBubble(shownLine);
          if (idx < MOCK_TRANSCRIPT.length - 1) addTyping();
        }
      },
      function () {
        removeTyping();
        /* stream complete — nothing to do; doctor ends consult */
      }
    );
  }

  function appendBubble(l) {
    var t = document.getElementById("transcript");
    var empty = t.querySelector(".transcript-empty");
    if (empty) empty.remove();
    t.insertAdjacentHTML("beforeend", bubble(l));
    t.parentElement.scrollTop = t.parentElement.scrollHeight;
  }

  function haltForPopup(line, safety, flaggedIdx) {
    var s = docState;
    removeTyping();
    if (s.stream) { s.stream.stop(); s.stream = null; }
    s.phase = "paused";
    document.getElementById("transcript").querySelectorAll(".bbl")[flaggedIdx].classList.add("bbl-flagged");
    refreshSafetyStrip();
    openSafetyModal(safety);
  }

  function openSafetyModal(safety) {
    var s = docState;
    var overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML =
      '<div class="modal critical" role="alertdialog" aria-modal="true" aria-label="' + safety.title + '">' +
      '<h2>' + safety.title + "</h2>" +
      '<p class="modal-reason">' + safety.reason + "</p>" +
      '<div class="modal-actions">' +
      '<button class="btn btn-primary" id="change-rx">Change prescription</button>' +
      '<button class="btn btn-ghost" id="resume-consult">Resume consult</button>' +
      "</div></div>";
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }

    overlay.querySelector("#change-rx").addEventListener("click", function () {
      s.pendingDrug = "Azithromycin";
      // swap the flagged line and any other mention in transcript + draft
      s.shown.forEach(function (l) {
        if (l.flagged) l.text = l.text.replace(/Amoxicillin/g, "Azithromycin");
      });
      var nodes = document.getElementById("transcript").querySelectorAll(".bbl-flagged");
      nodes.forEach(function (n) {
        n.innerHTML = n.innerHTML.replace(/Amoxicillin/g, "Azithromycin");
      });
      close();
      resumeStream();
    });

    overlay.querySelector("#resume-consult").addEventListener("click", function () {
      close();
      resumeStream();
    });
  }

  function resumeStream() {
    var s = docState;
    if (s.phase !== "paused") return;
    s.phase = "streaming";
    refreshSafetyStrip();
    // continue from where the popup halted, skipping already-shown lines
    var i = s.shown.length;
    (function tick() {
      if (i >= MOCK_TRANSCRIPT.length || s.phase !== "streaming") return;
      removeTyping();
      var line = MOCK_TRANSCRIPT[i];
      var shownLine = { speaker: line.speaker, text: line.text, flagged: false };
      if (line.drug) shownLine.text = line.text.replace(/Amoxicillin/g, s.pendingDrug);
      s.shown.push(shownLine);
      appendBubble(shownLine);
      i++;
      if (i < MOCK_TRANSCRIPT.length) addTyping();
      setTimeout(tick, 1300);
    })();
  }

  function endConsult() {
    var s = docState;
    removeTyping();
    if (s.stream) { s.stream.stop(); s.stream = null; }
    s.phase = "draft";
    document.getElementById("end-btn").disabled = true;
    var tc = document.getElementById("transcript-card");
    tc.style.display = "none";
    renderDraft();
    refreshSafetyStrip();
  }

  function renderDraft() {
    var s = docState;
    var draft = buildMockDraftRx(s.pendingDrug === "Amoxicillin" ? "Amoxicillin" : s.pendingDrug);
    var host = document.getElementById("after-consult");
    host.innerHTML =
      '<div class="card draft-card">' +
      "<h2>Draft prescription</h2>" +
      '<div class="draft-grid">' +
      '<label>Drug<input id="draft-drug" value="' + draft.drug + '"></label>' +
      '<label>Dosage<input id="draft-dosage" value="' + draft.dosage + '"></label>' +
      '<label>Duration<input id="draft-duration" value="' + draft.duration + '"></label>' +
      "</div>" +
      '<div id="draft-chip">' + draftChip(draft.drug) + "</div>" +
      '<div class="sign-panel">' +
      "<h3>Sign prescription</h3>" +
      '<p class="muted">Enter patient ID to confirm identity.</p>' +
      '<div class="sign-row">' +
      '<input id="sign-id" placeholder="Patient ID (e.g. P-1024)" autocomplete="off">' +
      '<button class="btn btn-primary" id="sign-btn">Sign</button>' +
      "</div>" +
      '<div id="sign-feedback"></div>' +
      "</div></div>";

    function draftChip(drug) {
      return drug === "Amoxicillin"
        ? chip("⚠ Safety check flagged", "danger")
        : chip("Safety check passed", "ok");
    }
    function recheck() {
      document.getElementById("draft-chip").innerHTML = draftChip(document.getElementById("draft-drug").value.trim());
    }
    ["draft-drug", "draft-dosage", "draft-duration"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", recheck);
    });

    document.getElementById("sign-btn").addEventListener("click", function () {
      var entered = document.getElementById("sign-id").value.trim();
      var fb = document.getElementById("sign-feedback");
      var result = signMockRx(entered);
      if (!result.ok) {
        fb.innerHTML = '<p class="error-text">' + result.error + "</p>";
        return;
      }
      docState.phase = "signed";
      docState.signed = result;
      renderSignedPanel(result);
      refreshSafetyStrip();
    });
  }

  function renderSignedPanel(result) {
    var host = document.getElementById("after-consult");
    var draftChip = document.querySelector(".draft-card .sign-panel");
    if (draftChip) draftChip.style.display = "none";
    var panel =
      '<div class="card signed-card">' +
      '<div class="success-head">' + chip("Signed", "ok") + "<h2>Prescription signed</h2></div>" +
      '<p class="rx-line"><strong>Rx ID:</strong> ' + result.rxId + "</p>" +
      '<div class="qr-row">' + qrTile(result.qr, "qr-sm") +
      '<p class="muted">Scan or open the verify link<br><code>' + result.qr + "</code></p></div>" +
      '<p class="muted">Follow-ups created: ' + result.followUps + " cards on the patient home.</p>" +
      "</div>";
    if (draftChip) draftChip.insertAdjacentHTML("afterend", panel);
    else host.insertAdjacentHTML("beforeend", panel);
    paintQrTiles();
  }

  /* ---------- patient screen ---------- */

  function renderPatient(id) {
    var p = getMockPatient(id);
    var visit = getMockVisitSummary();
    var rx = getMockRx();
    var followUps = getMockFollowUps();

    var fuHtml = followUps.length
      ? followUps.map(function (f, i) {
          return (
            '<div class="card followup-card" style="--d:' + (80 + i * 80) + 'ms">' +
            '<span class="fu-icon">' + f.icon + "</span>" +
            '<div class="fu-body"><strong>' + f.title + "</strong><span class=\"muted\">" + f.due + "</span></div>" +
            '<label class="toggle"><input type="checkbox" data-fu="' + i + '" data-title="' + f.title + '"><span></span>Remind me</label>' +
            "</div>"
          );
        }).join("")
      : '<div class="card empty-card"><p class="muted">No visits yet.</p></div>';

    app.innerHTML = topBar(p.name, "patient") +
      '<main class="page-wrap">' +
      '<div class="card visit-card"><h2>Visit summary</h2>' +
      "<p><strong>" + visit.doctor + "</strong> · " + visit.date + "</p>" +
      '<p class="muted">' + visit.reason + "</p></div>" +
      '<div class="card rx-card"><h2>Current e-Rx</h2>' +
      "<p><strong>" + rx.drug + "</strong> — " + rx.dosage + " · " + rx.duration + "</p>" +
      '<p class="muted">Expires ' + rx.expiry + " · " + rx.rxId + " · " + chip("Allergy check passed", "ok") + "</p>" +
      '<div class="qr-center">' + qrTile(rx.qr, "qr-lg") +
      '<p class="muted"><code>' + rx.qr + "</code></p></div></div>" +
      '<div class="section-title"><h2>Follow-ups</h2></div>' + fuHtml +
      '<div class="card past-card"><h2>Past visits</h2>' +
      "<ul class=\"plain-list\"><li>Seasonal cough and cold · 14 Aug 2026</li><li>Annual check-up · 02 Feb 2026</li></ul>" +
      "</div></main>";
    wireLogout();

    // reminder toggles are local state only; give feedback via toast
    document.querySelectorAll('.toggle input[type="checkbox"]').forEach(function (c) {
      c.addEventListener("change", function () {
        var title = this.getAttribute("data-title") || "follow-up";
        toast(this.checked ? "Reminder set — " + title : "Reminder off — " + title);
      });
    });
    paintQrTiles();
  }

  /* ---------- pharmacy verifier ---------- */

  function renderPharmacy(id) {
    var status = verifyMockRx(id);
    var rx = getMockRx();

    var banner =
      '<div class="rx-banner rx-' + status.toLowerCase() + '">' +
      (status === "VALID" ? "✔ VALID" : status === "DISPENSED" ? "● DISPENSED" : "✖ INVALID") +
      "</div>";

    var body = "";
    if (status === "VALID") {
      body =
        '<div class="card rx-detail">' +
        "<h2>Prescription</h2>" +
        "<p><strong>" + rx.drug + "</strong> — " + rx.dosage + " · " + rx.duration + "</p>" +
        '<p class="muted">' + rx.doctor + " · " + rx.date + " · expires " + rx.expiry + "</p>" +
        '<p>' + chip("Allergy check passed", "ok") + "</p>" +
        '<button class="btn btn-primary btn-block" id="dispense-btn">Mark as Dispensed</button>' +
        "</div>";
    } else if (status === "DISPENSED") {
      body = '<div class="card rx-detail"><p class="muted">This prescription has already been dispensed.</p></div>';
    } else {
      body = '<div class="card rx-detail"><p class="muted">Unknown prescription ID. No patient data is shown for unknown IDs.</p></div>';
    }

    app.innerHTML = '<main class="page-wrap narrow">' + banner + body + "</main>";

    if (status === "VALID") {
      document.getElementById("dispense-btn").addEventListener("click", function () {
        dispenseMockRx(id);
        toast("Prescription marked as dispensed");
        renderPharmacy(id); // re-render to DISPENSED
      });
    }
  }

  navigate();
})();
