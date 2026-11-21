// dashboard.js
// Controls the agent dashboard: login, session list, filters, analytics, and detail modal.

const SERVER_URL = "http://localhost:8000";

// Stored in memory only (not localStorage) — cleared on page refresh
// for basic security since this is a demo/student project
let dashboardPassword = null;
let currentFilter = "ALL";


// ---------------------------------------------------------------
// ELEMENT REFERENCES
// ---------------------------------------------------------------
const loginScreen   = document.getElementById("loginScreen");
const dashboard     = document.getElementById("dashboard");
const passwordInput = document.getElementById("passwordInput");
const loginButton   = document.getElementById("loginButton");
const loginError    = document.getElementById("loginError");
const logoutButton  = document.getElementById("logoutButton");
const tableBody     = document.getElementById("sessionTableBody");
const emptyState    = document.getElementById("emptyState");
const modalOverlay  = document.getElementById("modalOverlay");
const modalBody     = document.getElementById("modalBody");
const closeModal    = document.getElementById("closeModal");
const refreshButton = document.getElementById("refreshButton");


// ---------------------------------------------------------------
// HELPER: getRiskLevel
// Maps a 0-100 fraud risk score to LOW / MEDIUM / HIGH.
// ---------------------------------------------------------------
function getRiskLevel(score) {
  if (score == null) return "LOW";
  if (score < 25) return "LOW";
  if (score < 55) return "MEDIUM";
  return "HIGH";
}


// ---------------------------------------------------------------
// FUNCTION: apiCall
// Wrapper for all authenticated dashboard API requests.
// Automatically attaches the password as a header.
// ---------------------------------------------------------------
async function apiCall(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-Dashboard-Auth": dashboardPassword,
    ...(options.headers || {}),
  };

  const response = await fetch(`${SERVER_URL}${path}`, { ...options, headers });

  if (response.status === 401) {
    // Session expired or wrong password — force back to login
    dashboardPassword = null;
    loginScreen.style.display = "flex";
    dashboard.style.display   = "none";
    throw new Error("Unauthorized");
  }

  return response.json();
}


// ---------------------------------------------------------------
// LOGIN
// ---------------------------------------------------------------
async function attemptLogin() {
  const password = passwordInput.value.trim();
  if (!password) return;

  loginError.textContent = "";

  try {
    const response = await fetch(`${SERVER_URL}/api/dashboard/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });

    const data = await response.json();

    if (data.success) {
      dashboardPassword = password;
      loginScreen.style.display = "none";
      dashboard.style.display   = "block";
      loadDashboard();
    } else {
      loginError.textContent = "Incorrect password";
    }
  } catch (error) {
    loginError.textContent = "Cannot reach server";
    console.error(error);
  }
}

loginButton.addEventListener("click", attemptLogin);
passwordInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") attemptLogin();
});

logoutButton.addEventListener("click", () => {
  dashboardPassword = null;
  loginScreen.style.display = "flex";
  dashboard.style.display   = "none";
  passwordInput.value = "";
});


// ---------------------------------------------------------------
// FUNCTION: loadDashboard
// Loads stats, analytics, and session list together.
// ---------------------------------------------------------------
async function loadDashboard() {
  await Promise.all([loadStats(), loadAnalytics(), loadSessions(), loadVaultStats()]);
  initReviewerSocket();
  requestNotificationPermission();
}

// ---------------------------------------------------------------
// FUNCTION: loadVaultStats
// Fetches encrypted evidence storage summary for the retention bar.
// ---------------------------------------------------------------
async function loadVaultStats() {
  const el = document.getElementById("vaultStatsText");
  const daysInput = document.getElementById("vaultRetentionDays");
  if (!el) return;

  const days = daysInput ? Math.max(0, parseInt(daysInput.value || "30", 10) || 0) : 30;
  try {
    const stats = await apiCall(`/api/dashboard/vault/stats?retention_days=${days}`);
    el.textContent = `${stats.total_files} encrypted blobs (${stats.id_files} ID, ${stats.selfie_files} selfie · ${stats.total_kb} KB) · ${stats.expired_count} expired (>${stats.retention_days}d)`;
  } catch (error) {
    el.textContent = "Vault stats unavailable";
    console.error("Vault stats error:", error);
  }
}

// Keep track of temporary decrypted image URLs so we can release memory
// as soon as the reviewer switches sessions or closes the detail modal.
let activeEvidenceUrls = [];

function revokeEvidenceUrls() {
  for (const url of activeEvidenceUrls) {
    URL.revokeObjectURL(url);
  }
  activeEvidenceUrls = [];
}

async function fetchEvidenceCard(sessionId, docKind, label, available) {
  const card = document.createElement("div");
  card.className = "vault-evidence-card";

  const title = document.createElement("div");
  title.className = "vault-card-label";
  title.textContent = label;
  card.appendChild(title);

  if (!available) {
    const missing = document.createElement("div");
    missing.className = "vault-missing";
    missing.textContent = "Not captured in this session";
    card.appendChild(missing);
    return card;
  }

  const resp = await fetch(`/api/dashboard/sessions/${encodeURIComponent(sessionId)}/evidence/${docKind}`, {
    headers: { "X-Dashboard-Auth": dashboardPassword },
  });

  if (!resp.ok) {
    const errDiv = document.createElement("div");
    errDiv.className = "vault-missing";
    errDiv.textContent = resp.status === 404 ? "Missing from vault" : `Error (${resp.status})`;
    card.appendChild(errDiv);
    return card;
  }

  const blob = await resp.blob();
  const objectUrl = URL.createObjectURL(blob);
  activeEvidenceUrls.push(objectUrl);

  const img = document.createElement("img");
  img.src = objectUrl;
  img.alt = label;
  card.appendChild(img);
  return card;
}


// ---------------------------------------------------------------
// FUNCTION: loadStats
// ---------------------------------------------------------------
async function loadStats() {
  try {
    const stats = await apiCall("/api/dashboard/stats");
    document.getElementById("statTotal").textContent    = stats.total;
    document.getElementById("statPassed").textContent   = stats.passed;
    document.getElementById("statFailed").textContent   = stats.failed;
    document.getElementById("statReview").textContent   = stats.review;
    document.getElementById("statPassRate").textContent = stats.pass_rate + "%";
  } catch (error) {
    console.error("Stats load error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: loadAnalytics
// Loads verdict proportions, operational metrics, and doc breakdown.
// ---------------------------------------------------------------
async function loadAnalytics() {
  try {
    const data = await apiCall("/api/dashboard/analytics");
    const total = data.total || 0;

    // Update verdict distribution bar
    const v = data.verdicts || {};
    const pct = (count) => total > 0 ? ((count / total) * 100).toFixed(1) + "%" : "0%";

    document.getElementById("barPass").style.width       = pct(v.PASS || 0);
    document.getElementById("barReview").style.width     = pct(v.REVIEW || 0);
    document.getElementById("barFail").style.width       = pct(v.FAIL || 0);
    document.getElementById("barIncomplete").style.width = pct(v.INCOMPLETE || 0);

    document.getElementById("verdictLegend").innerHTML = `
      <span>🟢 Pass: ${v.PASS || 0}</span>
      <span>🟡 Review: ${v.REVIEW || 0}</span>
      <span>🔴 Fail: ${v.FAIL || 0}</span>
      <span>⚪ Incomplete: ${v.INCOMPLETE || 0}</span>
    `;

    // Update operational metrics
    document.getElementById("metricAvgConf").textContent   = (data.avg_confidence || 0).toFixed(1) + "%";
    document.getElementById("metricAvgFraud").textContent  = (data.avg_fraud_score || 0).toFixed(1) + " / 100";
    document.getElementById("metricAvgDur").textContent    = (data.avg_duration_sec || 0).toFixed(1) + "s";
    document.getElementById("metricSpoofRate").textContent =
      `${data.spoof_rate || 0}% (${data.spoof_flagged || 0})`;

    // Update document breakdown pills
    const docs = data.id_types || {};
    const docEl = document.getElementById("docBreakdown");
    const entries = Object.entries(docs);
    docEl.innerHTML = entries.length
      ? entries.map(([type, count]) => `<span class="doc-pill">${type}: <strong>${count}</strong></span>`).join("")
      : "No documents yet";

  } catch (error) {
    console.error("Analytics load error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: loadSessions
// Fetches sessions for the current filter and renders the table.
// ---------------------------------------------------------------
async function loadSessions() {
  try {
    const data = await apiCall(`/api/dashboard/sessions?verdict=${currentFilter}`);
    renderSessionTable(data.sessions);
  } catch (error) {
    console.error("Sessions load error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: renderSessionTable
// Builds the table rows from session data.
// ---------------------------------------------------------------
function renderSessionTable(sessions) {
  tableBody.innerHTML = "";

  if (sessions.length === 0) {
    emptyState.style.display = "block";
    return;
  }
  emptyState.style.display = "none";

  sessions.forEach((session) => {
    const row = document.createElement("tr");
    row.addEventListener("click", () => openSessionDetail(session.id));

    const date = session.created_at
      ? new Date(session.created_at).toLocaleString()
      : "—";

    const confidence = session.match_confidence
      ? session.match_confidence.toFixed(1) + "%"
      : "—";

    const fraudScore = session.fraud_score != null ? Number(session.fraud_score) : 0.0;
    const riskLevel  = getRiskLevel(fraudScore);

    const idType = session.id_fields?.id_type || "—";

    row.innerHTML = `
      <td>${session.id.slice(0, 8)}…</td>
      <td>${date}</td>
      <td><span class="verdict-badge verdict-${session.verdict || 'INCOMPLETE'}">${session.verdict || 'INCOMPLETE'}</span></td>
      <td>${confidence}</td>
      <td><span class="risk-badge risk-${riskLevel}">${fraudScore.toFixed(1)} · ${riskLevel}</span></td>
      <td>${session.liveness_blinks ?? '—'}</td>
      <td>${idType}</td>
      <td><a class="view-link">View →</a></td>
    `;

    tableBody.appendChild(row);
  });
}


// ---------------------------------------------------------------
// FILTER BUTTONS
// ---------------------------------------------------------------
document.querySelectorAll(".filter-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    loadSessions();
  });
});

refreshButton.addEventListener("click", loadDashboard);


// ---------------------------------------------------------------
// FUNCTION: openSessionDetail
// Fetches full session detail + audit trail and shows the modal.
// ---------------------------------------------------------------
async function openSessionDetail(sessionId) {
  try {
    const data    = await apiCall(`/api/dashboard/sessions/${sessionId}`);
    const session = data.session;
    const trail   = data.audit_trail;
    const vault   = data.vault || { has_id: false, has_selfie: false };
    revokeEvidenceUrls();

    const idFields = session.id_fields || {};

    const spoofStatus = session.spoof_detected
      ? `❌ Flagged (score: ${session.spoof_score != null ? session.spoof_score.toFixed(3) : 'N/A'})`
      : `✓ Clear${session.spoof_score != null ? ` (score: ${session.spoof_score.toFixed(3)})` : ''}`;

    const fraudScore = session.fraud_score != null ? Number(session.fraud_score) : 0.0;
    const riskLevel  = getRiskLevel(fraudScore);
    const fraudEvent = trail.find(e => e.event_type === "fraud_risk_assessed");
    const breakdown  = fraudEvent?.details?.breakdown || null;
    const riskFactors = fraudEvent?.details?.risk_factors || [];

    modalBody.innerHTML = `
      <div class="detail-section">
        <h3>Verdict</h3>
        <div class="detail-row">
          <span class="label">Status</span>
          <span class="value"><span class="verdict-badge verdict-${session.verdict || 'INCOMPLETE'}">${session.verdict || 'INCOMPLETE'}</span></span>
        </div>
        <div class="detail-row">
          <span class="label">Message</span>
          <span class="value">${session.verdict_message || '—'}</span>
        </div>
        ${session.verdict_reasons && session.verdict_reasons.length ? `
        <div class="detail-row" style="align-items: flex-start;">
          <span class="label">Reasons</span>
          <span class="value">
            <ul style="margin: 0; padding-left: 18px; text-align: left;">
              ${session.verdict_reasons.map(r => `<li>${r}</li>`).join('')}
            </ul>
          </span>
        </div>` : ''}
      </div>

      <div class="detail-section">
        <h3>Fraud Risk Intelligence</h3>
        <div class="risk-gauge-box">
          <div class="risk-gauge-header">
            <span>Unified Fraud Risk Score</span>
            <strong>${fraudScore.toFixed(1)} / 100 &nbsp;<span class="risk-badge risk-${riskLevel}">${riskLevel}</span></strong>
          </div>
          <div class="risk-gauge-track">
            <div class="risk-gauge-fill fill-${riskLevel}" style="width: ${Math.min(100, Math.max(0, fraudScore))}%"></div>
          </div>
          ${breakdown ? `
            <div class="risk-breakdown-grid">
              <div>Face Risk: <strong>${breakdown.face_risk} / 30</strong></div>
              <div>Spoof &amp; Liveness: <strong>${breakdown.spoof_liveness_risk} / 35</strong></div>
              <div>Document Risk: <strong>${breakdown.document_risk} / 10</strong></div>
              <div>History &amp; IP: <strong>${breakdown.history_risk} / 25</strong></div>
            </div>
          ` : '<div style="font-size:12px;color:#777">Legacy session (pre-fraud engine)</div>'}
          ${riskFactors.length ? `
            <ul class="risk-factor-list">
              ${riskFactors.map(f => `<li>${f}</li>`).join('')}
            </ul>
          ` : ''}
        </div>
      </div>

      <div class="detail-section">
        <h3>Verification Steps</h3>
        <div class="detail-row"><span class="label">Face Detected</span><span class="value">${session.face_found ? '✓ Yes' : '✗ No'}</span></div>
        <div class="detail-row"><span class="label">Liveness Passed</span><span class="value">${session.liveness_passed ? '✓ Yes' : '✗ No'} (${session.liveness_blinks || 0} blinks)</span></div>
        <div class="detail-row"><span class="label">Anti-Spoof Check</span><span class="value">${spoofStatus}</span></div>
        <div class="detail-row"><span class="label">ID Scanned</span><span class="value">${session.id_scanned ? '✓ Yes' : '✗ No'}</span></div>
        <div class="detail-row"><span class="label">Face Matched</span><span class="value">${session.face_matched ? '✓ Yes' : '✗ No'} (${(session.match_confidence || 0).toFixed(1)}% confidence)</span></div>
      </div>

      <div class="detail-section">
        <h3>Extracted ID Fields</h3>
        <div class="detail-row"><span class="label">Name</span><span class="value">${idFields.name || '—'}</span></div>
        <div class="detail-row"><span class="label">ID Type</span><span class="value">${idFields.id_type || '—'}</span></div>
        <div class="detail-row"><span class="label">ID Number</span><span class="value">${idFields.id_number || '—'}</span></div>
        <div class="detail-row"><span class="label">ID Validation</span><span class="value">${idFields.id_valid === true ? '✓ Valid' : idFields.id_valid === false ? '❌ Invalid' : '—'}${idFields.validation_note ? ` (${idFields.validation_note})` : ''}</span></div>
        <div class="detail-row"><span class="label">DOB</span><span class="value">${idFields.dob || '—'}</span></div>
      </div>

      <div class="detail-section">
        <h3>Encrypted Evidence Vault</h3>
        <div class="vault-detail-status">
          <span>${vault.has_id || vault.has_selfie
            ? `Stored encrypted (${vault.has_id ? 'ID' : ''}${vault.has_id && vault.has_selfie ? ' + ' : ''}${vault.has_selfie ? 'Selfie' : ''}). Decryption is audit-logged.`
            : 'Not stored in encrypted vault (legacy or purged session).'}</span>
          ${vault.has_id || vault.has_selfie
            ? `<button class="vault-view-btn" data-vault-session="${session.id}" data-has-id="${vault.has_id ? '1' : '0'}" data-has-selfie="${vault.has_selfie ? '1' : '0'}" type="button">Decrypt &amp; View Evidence</button>`
            : ''}
        </div>
        <div id="vaultEvidenceContainer" class="vault-evidence-grid" style="display:none;"></div>
      </div>

      <div class="detail-section">
        <h3>Device Info</h3>
        <div class="detail-row"><span class="label">IP Address</span><span class="value">${session.ip_address || '—'}</span></div>
        <div class="detail-row"><span class="label">Created</span><span class="value">${session.created_at ? new Date(session.created_at).toLocaleString() : '—'}</span></div>
      </div>

      <div class="detail-section">
        <h3>Audit Trail</h3>
        ${trail.map(event => `
          <div class="timeline-item">
            <span class="timeline-time">${new Date(event.timestamp).toLocaleTimeString()}</span>
            <span class="timeline-event">${event.event_type}</span>
          </div>
        `).join('') || '<p style="color:#666;font-size:13px">No events recorded</p>'}
      </div>

      ${session.verdict === 'REVIEW' || session.review_action ? `
        <div class="detail-section">
          <h3>Agent Review</h3>
          ${session.review_action ? `
            <div class="detail-row">
              <span class="label">Action Taken</span>
              <span class="value">${session.review_action} by ${session.reviewed_by || 'Agent'}</span>
            </div>
            ${session.review_note ? `
            <div class="detail-row">
              <span class="label">Reviewer Note</span>
              <span class="value">${session.review_note}</span>
            </div>` : ''}
          ` : `
            <textarea id="reviewNoteInput" class="review-note-input" placeholder="Optional review note (e.g., 'Clear identity match upon visual inspection')"></textarea>
            <div class="review-actions">
              <button class="review-btn approve-btn" onclick="submitReview('${session.id}', 'approved')">Approve</button>
              <button class="review-btn escalate-btn" onclick="submitReview('${session.id}', 'escalated')">Escalate</button>
              <button class="review-btn reject-btn" onclick="submitReview('${session.id}', 'rejected')">Reject</button>
            </div>
          `}
        </div>
      ` : ''}
    `;

    modalOverlay.style.display = "flex";

  } catch (error) {
    console.error("Session detail error:", error);
  }
}


// ---------------------------------------------------------------
// FUNCTION: submitReview
// Called when an agent clicks Approve/Escalate/Reject on a REVIEW session.
// Exposed on window since it's called from inline onclick above.
// ---------------------------------------------------------------
window.submitReview = async function(sessionId, action) {
  const noteInput = document.getElementById("reviewNoteInput");
  const note = noteInput ? noteInput.value.trim() : "";

  try {
    await apiCall(`/api/dashboard/sessions/${sessionId}/review`, {
      method: "POST",
      body: JSON.stringify({ action, reviewer: "Agent", note }),
    });

    modalOverlay.style.display = "none";
    loadDashboard();  // refresh the list and analytics

  } catch (error) {
    console.error("Review submit error:", error);
  }
};


function closeSessionModal() {
  revokeEvidenceUrls();
  modalOverlay.style.display = "none";
}

closeModal.addEventListener("click", closeSessionModal);

modalOverlay.addEventListener("click", (e) => {
  if (e.target === modalOverlay) closeSessionModal();
});

// Event delegation for "Decrypt & View Evidence" inside the session detail modal
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-vault-session]");
  if (!btn) return;

  const sessionId = btn.dataset.vaultSession;
  const hasId     = btn.dataset.hasId === "1";
  const hasSelfie = btn.dataset.hasSelfie === "1";
  const container = document.getElementById("vaultEvidenceContainer");
  if (!container) return;

  btn.disabled = true;
  btn.textContent = "Decrypting...";
  revokeEvidenceUrls();
  container.innerHTML = "";
  container.style.display = "grid";

  try {
    const [idCard, selfieCard] = await Promise.all([
      fetchEvidenceCard(sessionId, "id", "ID Document", hasId),
      fetchEvidenceCard(sessionId, "selfie", "Live Selfie", hasSelfie),
    ]);
    container.appendChild(idCard);
    container.appendChild(selfieCard);
    btn.textContent = "Decrypted (Access Logged)";
  } catch (error) {
    console.error("Evidence decryption error:", error);
    btn.disabled = false;
    btn.textContent = "Decrypt & View Evidence";
  }
});

// Vault retention bar controls
const vaultRetentionInput = document.getElementById("vaultRetentionDays");
const purgeVaultBtn       = document.getElementById("purgeVaultBtn");

if (vaultRetentionInput) {
  vaultRetentionInput.addEventListener("change", loadVaultStats);
}

if (purgeVaultBtn) {
  purgeVaultBtn.addEventListener("click", async () => {
    const days = vaultRetentionInput
      ? Math.max(0, parseInt(vaultRetentionInput.value || "30", 10) || 0)
      : 30;

    if (!confirm(`Delete encrypted vault files older than ${days} day(s)? This cannot be undone.`)) {
      return;
    }

    purgeVaultBtn.disabled = true;
    purgeVaultBtn.textContent = "Purging...";
    try {
      const res = await apiCall("/api/dashboard/vault/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ retention_days: days }),
      });
      await loadVaultStats();
      alert(`Purged ${res.deleted_count} expired evidence blob(s) (>${res.retention_days}d).`);
    } catch (error) {
      alert("Vault purge failed: " + error.message);
    } finally {
      purgeVaultBtn.disabled = false;
      purgeVaultBtn.textContent = "Purge Expired";
    }
  });
}

// ===============================================================
// REAL-TIME REVIEWER NOTIFICATIONS ENGINE
// WebSockets + Web Audio API Chime + Native Desktop Notification
// ===============================================================

let reviewerWs = null;
let wsHeartbeatInterval = null;
let liveFallbackTimer = null;

// Request browser desktop notification permission
function requestNotificationPermission() {
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission().then((perm) => {
      console.log("[ReviewerNotification] Desktop permission:", perm);
    });
  }
}

// Synthesize alert chime using Web Audio API (zero external sound files needed)
function playNotificationChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    // First tone (587.33 Hz - D5)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now);
    gain1.gain.setValueAtTime(0.28, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.35);

    // Second cheerful chime tone (880.0 Hz - A5)
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880.0, now + 0.12);
    gain2.gain.setValueAtTime(0.32, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.6);
  } catch (e) {
    console.warn("[ReviewerNotification] Audio chime failed:", e);
  }
}

// Trigger native OS Desktop Notification
function triggerDesktopNotification(session) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;

  const name = session.applicant_name || "Applicant";
  const ref = session.tracking_code || (session.id ? session.id.slice(0, 8) : "Pending");
  const conf = session.match_confidence ? `${Number(session.match_confidence).toFixed(1)}%` : "N/A";
  const risk = session.fraud_score != null ? `${Number(session.fraud_score).toFixed(1)}/100` : "N/A";

  const notif = new Notification("⚠️ KYC Review Required — Action Needed", {
    body: `${name} (${ref})\nConfidence: ${conf} | Fraud Risk: ${risk}\nClick to inspect documents and approve/reject.`,
    icon: "/assets/favicon.ico",
    requireInteraction: true,
    tag: "kyc-review-" + (session.id || Date.now()),
  });

  notif.onclick = () => {
    window.focus();
    if (session.id) {
      openSessionDetail(session.id);
    }
    notif.close();
  };
}

// Show urgent in-app banner at top of dashboard
function showLiveAlertBanner(session) {
  const banner = document.getElementById("liveAlertBanner");
  const textEl = document.getElementById("liveAlertText");
  const reviewBtn = document.getElementById("liveAlertReviewBtn");
  const dismissBtn = document.getElementById("liveAlertDismissBtn");
  if (!banner || !textEl) return;

  const name = session.applicant_name || "Applicant";
  const ref = session.tracking_code || (session.id ? session.id.slice(0, 8) : "Pending");
  const conf = session.match_confidence ? `${Number(session.match_confidence).toFixed(1)}%` : "N/A";
  const risk = session.fraud_score != null ? `${Number(session.fraud_score).toFixed(1)}/100` : "N/A";

  textEl.innerHTML = `<strong>⚠️ Verification Flagged for Review:</strong> <strong>${name}</strong> (${ref}) requires compliance verification. Match: <strong>${conf}</strong> | Risk: <strong>${risk}</strong>`;
  banner.style.display = "flex";

  if (reviewBtn) {
    reviewBtn.onclick = () => {
      if (session.id) {
        openSessionDetail(session.id);
      }
      banner.style.display = "none";
    };
  }

  if (dismissBtn) {
    dismissBtn.onclick = () => {
      banner.style.display = "none";
    };
  }
}

// Connect WebSocket to /ws/reviewer
function initReviewerSocket() {
  if (reviewerWs && (reviewerWs.readyState === WebSocket.OPEN || reviewerWs.readyState === WebSocket.CONNECTING)) {
    return;
  }

  const badge = document.getElementById("liveStatusBadge");
  if (badge) {
    badge.className = "live-badge live-connecting";
    badge.textContent = "🟡 Connecting...";
  }

  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws/reviewer`;

  try {
    reviewerWs = new WebSocket(wsUrl);

    reviewerWs.onopen = () => {
      console.log("[ReviewerNotification] WebSocket connected to /ws/reviewer");
      if (badge) {
        badge.className = "live-badge live-online";
        badge.textContent = "🟢 Live Alerts Active";
      }

      // Heartbeat ping every 25 seconds
      if (wsHeartbeatInterval) clearInterval(wsHeartbeatInterval);
      wsHeartbeatInterval = setInterval(() => {
        if (reviewerWs && reviewerWs.readyState === WebSocket.OPEN) {
          reviewerWs.send("ping");
        }
      }, 25000);
    };

    reviewerWs.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "NEW_REVIEW_REQUIRED" && msg.session) {
          console.log("[ReviewerNotification] New review required:", msg.session);
          playNotificationChime();
          triggerDesktopNotification(msg.session);
          showLiveAlertBanner(msg.session);

          // Immediately update list & stats without full page reload
          loadSessions();
          loadStats();
          loadAnalytics();
        } else if (msg.type === "SESSION_REVIEWED" || msg.type === "SESSION_COMPLETED") {
          loadSessions();
          loadStats();
          loadAnalytics();
        }
      } catch (err) {
        // Pong or non-JSON message
      }
    };

    reviewerWs.onclose = () => {
      if (badge) {
        badge.className = "live-badge live-offline";
        badge.textContent = "⚪ Offline (Reconnecting)";
      }
      if (wsHeartbeatInterval) clearInterval(wsHeartbeatInterval);
      setTimeout(initReviewerSocket, 3500); // Reconnect
    };

    reviewerWs.onerror = () => {
      if (reviewerWs) reviewerWs.close();
    };
  } catch (e) {
    console.error("[ReviewerNotification] Failed to create WebSocket:", e);
    setTimeout(initReviewerSocket, 5000);
  }

  // Backup polling every 30s in case WebSockets are temporarily blocked
  if (!liveFallbackTimer) {
    liveFallbackTimer = setInterval(() => {
      const dashboardEl = document.getElementById("dashboard");
      if (dashboardEl && dashboardEl.style.display !== "none") {
        loadSessions();
        loadStats();
      }
    }, 30000);
  }
}

// Hook up "Test Alert" button so user can test sound & notification anytime
const testAlertBtn = document.getElementById("testAlertButton");
if (testAlertBtn) {
  testAlertBtn.addEventListener("click", () => {
    requestNotificationPermission();
    playNotificationChime();
    const dummySession = {
      id: "test-" + Date.now().toString(16),
      tracking_code: "KYC-TEST77",
      applicant_name: "Test Applicant (Friend/Family)",
      match_confidence: 52.4,
      fraud_score: 28.5,
    };
    triggerDesktopNotification(dummySession);
    showLiveAlertBanner(dummySession);
  });
}
