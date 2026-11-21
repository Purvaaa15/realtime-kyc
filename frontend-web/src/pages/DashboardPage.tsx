// src/pages/DashboardPage.tsx
// Compliance Reviewer Operations Portal: KPIs, Analytics, Encrypted Vault,
// Searchable Session Queue with Live Auto-Refresh, AI Triage Brief,
// Encrypted Evidence Viewer, Approve/Escalate/Reject actions, and CSV/JSON Exports.
import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  Download,
  RefreshCw,
  Trash2,
  Eye,
  Sparkles,
  X,
  Lock,
  Radio,
  Printer,
  Bell,
} from "lucide-react";
import { apiRequest, buildAuthHeaders } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type {
  AuditEventItem,
  DashboardAnalytics,
  DashboardStats,
  ReviewerAiSummary,
  SessionRecord,
  UserProfile,
  VaultStats,
} from "../types/kyc";

function playNotificationChime() {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now); // D5
    gain1.gain.setValueAtTime(0.28, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.35);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880.0, now + 0.12); // A5
    gain2.gain.setValueAtTime(0.32, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.65);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.65);
  } catch (e) {
    console.warn("Chime error:", e);
  }
}

function triggerDesktopNotification(title: string, body: string, onClick?: () => void) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const notif = new Notification(title, {
      body,
      icon: "/assets/favicon.ico",
      requireInteraction: true,
    });
    if (onClick) {
      notif.onclick = () => {
        window.focus();
        onClick();
        notif.close();
      };
    }
  } catch (e) {
    console.warn("Desktop notification error:", e);
  }
}

export const DashboardPage: React.FC = () => {
  const { isReviewer, user, loginWithToken, unlockWithPasscode } = useAuth();

  // Login state when not yet authenticated as reviewer
  const [passcode, setPasscode] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);

  // Dashboard operational data
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [analytics, setAnalytics] = useState<DashboardAnalytics | null>(null);
  const [vaultStats, setVaultStats] = useState<VaultStats | null>(null);
  const [retentionDays, setRetentionDays] = useState<number>(30);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [verdictFilter, setVerdictFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [loadingData, setLoadingData] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [bannerMsg, setBannerMsg] = useState<string>("");
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [urgentAlert, setUrgentAlert] = useState<{
    id: string;
    name: string;
    ref: string;
    conf?: number;
    risk?: number;
  } | null>(null);

  // Vault purge confirmation modal state
  const [purgeModalOpen, setPurgeModalOpen] = useState<boolean>(false);
  const [purgeBusy, setPurgeBusy] = useState<boolean>(false);

  // Detail modal state
  const [detailSession, setDetailSession] = useState<SessionRecord | null>(null);
  const [detailTrail, setDetailTrail] = useState<AuditEventItem[]>([]);
  const [detailVault, setDetailVault] = useState<{ has_id: boolean; has_selfie: boolean }>({
    has_id: false,
    has_selfie: false,
  });
  const [aiBrief, setAiBrief] = useState<ReviewerAiSummary | null>(null);
  const [idImgUrl, setIdImgUrl] = useState<string | null>(null);
  const [selfieImgUrl, setSelfieImgUrl] = useState<string | null>(null);
  const [evidenceLoaded, setEvidenceLoaded] = useState<boolean>(false);
  const [maskAadhaar, setMaskAadhaar] = useState<boolean>(true);
  const [aadhaarRedacted, setAadhaarRedacted] = useState<boolean | null>(null);
  const [decrypting, setDecrypting] = useState<boolean>(false);
  const [reviewNote, setReviewNote] = useState<string>("");
  const [reviewBusy, setReviewBusy] = useState<boolean>(false);

  const revokeImages = () => {
    if (idImgUrl) URL.revokeObjectURL(idImgUrl);
    if (selfieImgUrl) URL.revokeObjectURL(selfieImgUrl);
    setIdImgUrl(null);
    setSelfieImgUrl(null);
  };

  useEffect(() => {
    return () => revokeImages();
  }, []);

  const loadAll = async (filter = verdictFilter, days = retentionDays, silent = false) => {
    if (!isReviewer) return;
    if (!silent) setLoadingData(true);
    try {
      const [s, a, sessRes, v] = await Promise.all([
        apiRequest<DashboardStats>("/api/dashboard/stats"),
        apiRequest<DashboardAnalytics>("/api/dashboard/analytics"),
        apiRequest<{ sessions: SessionRecord[] }>(`/api/dashboard/sessions?verdict=${encodeURIComponent(filter)}`),
        apiRequest<VaultStats>(`/api/dashboard/vault/stats?retention_days=${days}`),
      ]);
      setStats(s);
      setAnalytics(a);
      setSessions(sessRes.sessions);
      setVaultStats(v);
    } catch (err) {
      setBannerMsg(`Failed to load dashboard data: ${(err as Error).message}`);
    } finally {
      if (!silent) setLoadingData(false);
    }
  };

  useEffect(() => {
    if (isReviewer) loadAll(verdictFilter, retentionDays);
  }, [isReviewer, verdictFilter]);

  // Optional 10-second live polling for multi-device / live KYC demos
  useEffect(() => {
    if (!isReviewer || !autoRefresh) return;
    const id = window.setInterval(() => {
      loadAll(verdictFilter, retentionDays, true);
    }, 10000);
    return () => window.clearInterval(id);
  }, [isReviewer, autoRefresh, verdictFilter, retentionDays]);

  // Real-Time Reviewer Push Notifications (/ws/reviewer)
  useEffect(() => {
    if (!isReviewer) return;

    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }

    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/ws/reviewer`;
    let ws: WebSocket | null = null;
    let timer: number | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => {
          setWsConnected(true);
        };
        ws.onmessage = (event) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "NEW_REVIEW_REQUIRED" && msg.session) {
              playNotificationChime();
              const s = msg.session;
              const name = s.applicant_name || "Applicant";
              const ref = s.tracking_code || (s.id ? s.id.slice(0, 8) : "Pending");
              const conf = s.match_confidence ? `${Number(s.match_confidence).toFixed(1)}%` : "N/A";
              const risk = s.fraud_score != null ? `${Number(s.fraud_score).toFixed(1)}/100` : "N/A";

              setUrgentAlert({
                id: s.id,
                name,
                ref,
                conf: s.match_confidence,
                risk: s.fraud_score,
              });

              triggerDesktopNotification(
                `⚠️ KYC Review Required: ${name}`,
                `Tracking: ${ref} | Match: ${conf} | Risk: ${risk}\nClick to inspect documents and approve/reject.`,
                () => {
                  if (s.id) openDetailModal(s.id);
                }
              );

              loadAll(verdictFilter, retentionDays, true);
            } else if (msg.type === "SESSION_COMPLETED") {
              const name = msg.applicant_name || "Applicant";
              const v = msg.verdict || "COMPLETED";
              setBannerMsg(`✨ New Verification Recorded: ${name} — Result: ${v}`);
              loadAll(verdictFilter, retentionDays, true);
            } else if (msg.type === "SESSION_REVIEWED") {
              loadAll(verdictFilter, retentionDays, true);
            }
          } catch {
            // Heartbeat
          }
        };
        ws.onclose = () => {
          setWsConnected(false);
          timer = window.setTimeout(connect, 3500);
        };
        ws.onerror = () => {
          if (ws) ws.close();
        };
      } catch (e) {
        console.warn("WebSocket connect error:", e);
      }
    };

    connect();

    return () => {
      if (timer) window.clearTimeout(timer);
      if (ws) ws.close();
    };
  }, [isReviewer, verdictFilter, retentionDays]);

  const handleTestAlert = () => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    playNotificationChime();
    setUrgentAlert({
      id: "test-" + Date.now().toString(16),
      name: "Test Applicant (Friend/Family)",
      ref: "KYC-TEST77",
      conf: 52.4,
      risk: 28.5,
    });
    triggerDesktopNotification(
      "⚠️ KYC Review Required: Test Applicant",
      "Tracking: KYC-TEST77 | Match: 52.4% | Risk: 28.5/100\nClick to inspect documents and approve/reject."
    );
  };

  const closeDetailModal = () => {
    revokeImages();
    setDetailSession(null);
    setAiBrief(null);
  };

  // Close open modals with Escape and lock background page scroll while modal is open
  useEffect(() => {
    if (!detailSession && !purgeModalOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (purgeModalOpen && !purgeBusy) {
        setPurgeModalOpen(false);
      } else if (detailSession) {
        closeDetailModal();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [detailSession, purgeModalOpen, purgeBusy]);

  const handleReviewerLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    setLoginBusy(true);
    try {
      if (email.trim()) {
        const res = await apiRequest<{ success: boolean; token?: string; user?: UserProfile }>("/api/dashboard/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim(), password }),
        });
        if (res.token && res.user) loginWithToken(res.token, res.user);
      } else {
        await apiRequest<{ success: boolean }>("/api/dashboard/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ password: passcode }),
        });
        unlockWithPasscode(passcode);
      }
    } catch (err) {
      setLoginError((err as Error).message);
    } finally {
      setLoginBusy(false);
    }
  };

  const confirmPurgeVault = async () => {
    setPurgeBusy(true);
    try {
      const res = await apiRequest<{ deleted_count: number; retention_days: number; stats: VaultStats }>(
        "/api/dashboard/vault/purge",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ retention_days: retentionDays }),
        }
      );
      setVaultStats(res.stats);
      setPurgeModalOpen(false);
      setBannerMsg(`Purged ${res.deleted_count} expired evidence blob(s) (>${res.retention_days}d).`);
    } catch (err) {
      setPurgeModalOpen(false);
      setBannerMsg(`Vault purge failed: ${(err as Error).message}`);
    } finally {
      setPurgeBusy(false);
    }
  };

  const handleExport = async (fmt: "csv" | "json") => {
    try {
      const resp = await fetch(
        `/api/dashboard/compliance/export?format=${fmt}&verdict=${encodeURIComponent(verdictFilter)}`,
        { headers: buildAuthHeaders() }
      );
      if (!resp.ok) throw new Error(`Export failed (${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `pehchaanai_compliance_report.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setBannerMsg((err as Error).message);
    }
  };

  const openDetailModal = async (sessionId: string) => {
    revokeImages();
    setEvidenceLoaded(false);
    setMaskAadhaar(true);
    setAadhaarRedacted(null);
    setAiBrief(null);
    setReviewNote("");

    try {
      const detail = await apiRequest<{
        session: SessionRecord;
        audit_trail: AuditEventItem[];
        vault: { has_id: boolean; has_selfie: boolean };
      }>(`/api/dashboard/sessions/${encodeURIComponent(sessionId)}`);
      setDetailSession(detail.session);
      setDetailTrail(detail.audit_trail);
      setDetailVault(detail.vault);

      apiRequest<ReviewerAiSummary>(`/api/dashboard/sessions/${encodeURIComponent(sessionId)}/ai-summary`)
        .then(setAiBrief)
        .catch(() => {});
    } catch (err) {
      setBannerMsg((err as Error).message);
    }
  };

  const decryptEvidence = async (useMask = maskAadhaar) => {
    if (!detailSession) return;
    setDecrypting(true);
    revokeImages();
    try {
      let idWasRedacted: boolean | null = null;
      const fetchOne = async (kind: "id" | "selfie", avail: boolean) => {
        if (!avail) return null;
        const resp = await fetch(
          `/api/dashboard/sessions/${encodeURIComponent(detailSession.id)}/evidence/${kind}?masked=${useMask ? "true" : "false"}`,
          { headers: buildAuthHeaders() }
        );
        if (!resp.ok) return null;
        if (kind === "id") {
          idWasRedacted = resp.headers.get("X-Aadhaar-Redacted") === "true";
        }
        return URL.createObjectURL(await resp.blob());
      };

      const [idUrl, selfieUrl] = await Promise.all([
        fetchOne("id", detailVault.has_id),
        fetchOne("selfie", detailVault.has_selfie),
      ]);
      setIdImgUrl(idUrl);
      setSelfieImgUrl(selfieUrl);
      setAadhaarRedacted(idWasRedacted);
      setEvidenceLoaded(true);

      // Refresh audit trail so 'evidence_accessed' shows immediately
      const refreshed = await apiRequest<{ audit_trail: AuditEventItem[] }>(
        `/api/dashboard/sessions/${encodeURIComponent(detailSession.id)}`
      );
      setDetailTrail(refreshed.audit_trail);
    } finally {
      setDecrypting(false);
    }
  };

  const submitReview = async (action: "approved" | "escalated" | "rejected") => {
    if (!detailSession) return;
    setReviewBusy(true);
    try {
      await apiRequest(`/api/dashboard/sessions/${encodeURIComponent(detailSession.id)}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          reviewer: user?.full_name || "Compliance Reviewer",
          note: reviewNote.trim(),
        }),
      });
      closeDetailModal();
      setBannerMsg(`Session ${detailSession.tracking_code} marked ${action.toUpperCase()}.`);
      await loadAll(verdictFilter, retentionDays);
    } catch (err) {
      setBannerMsg((err as Error).message);
    } finally {
      setReviewBusy(false);
    }
  };

  if (!isReviewer) {
    return (
      <div className="page-container" style={{ maxWidth: 460 }}>
        <form className="card" onSubmit={handleReviewerLogin}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <ShieldCheck size={22} color="#38bdf8" />
            <h1 style={{ fontFamily: "var(--font-head)", fontSize: 20, fontWeight: 800 }}>
              Compliance Reviewer Portal
            </h1>
          </div>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
            Protected operations console. Enter the dashboard passcode or sign in with your reviewer account (<span className="mono">reviewer@pehchaanai.local</span>).
          </p>

          {loginError && <div className="alert alert-error" style={{ marginBottom: 14 }}>{loginError}</div>}

          <div className="field-group">
            <label className="field-label">Reviewer Passcode</label>
            <input
              type="password"
              className="field-input"
              placeholder="Enter passcode (e.g. admin123)"
              value={passcode}
              onChange={(e) => setPasscode(e.target.value)}
            />
          </div>

          <div style={{ textAlign: "center", fontSize: 11, color: "var(--text-dim)", margin: "10px 0" }}>
            — OR REVIEWER ACCOUNT —
          </div>

          <div className="field-group">
            <label className="field-label">Email</label>
            <input type="email" className="field-input" placeholder="reviewer@pehchaanai.local" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="field-group">
            <label className="field-label">Password</label>
            <input type="password" className="field-input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>

          <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={loginBusy}>
            {loginBusy ? "Verifying..." : "Unlock Reviewer Portal"}
          </button>
        </form>
      </div>
    );
  }

  const filteredSessions = sessions.filter((s) => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return true;
    return (
      s.id.toLowerCase().includes(q) ||
      (s.tracking_code || "").toLowerCase().includes(q) ||
      (s.applicant_name || "").toLowerCase().includes(q) ||
      ((s.id_fields?.id_type || "").toLowerCase().includes(q))
    );
  });

  const totalVerdicts = analytics
    ? Math.max(1, analytics.verdicts.PASS + analytics.verdicts.REVIEW + analytics.verdicts.FAIL + analytics.verdicts.INCOMPLETE)
    : 1;

  const filterCounts: Record<string, number | undefined> = {
    ALL: stats?.total,
    PASS: analytics?.verdicts.PASS,
    REVIEW: analytics?.verdicts.REVIEW,
    FAIL: analytics?.verdicts.FAIL,
    INCOMPLETE: analytics?.verdicts.INCOMPLETE,
  };

  const fraudEvent = detailTrail.find((e) => e.event_type === "fraud_risk_assessed");
  const breakdown = (fraudEvent?.details?.breakdown || {}) as Record<string, number>;

  return (
    <div className="page-container">
      <div className={detailSession ? "no-print" : ""}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 18 }}>
        <div>
          <h1 style={{ fontFamily: "var(--font-head)", fontSize: 24, fontWeight: 800 }}>
            Compliance &amp; Fraud Operations Portal
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Real-time analytics, AI case triage, Encrypted Evidence Vault inspection, and audit exports.
          </p>
        </div>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {wsConnected ? (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, padding: "5px 10px", background: "rgba(16, 185, 129, 0.15)", color: "#10b981", borderRadius: 6, border: "1px solid rgba(16, 185, 129, 0.3)", fontWeight: 500 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#10b981", boxShadow: "0 0 6px #10b981" }}></span>
              Live Alerts Connected
            </span>
          ) : (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, padding: "5px 10px", background: "rgba(245, 158, 11, 0.15)", color: "#f59e0b", borderRadius: 6, border: "1px solid rgba(245, 158, 11, 0.3)", fontWeight: 500 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#f59e0b" }}></span>
              Connecting Alerts...
            </span>
          )}

          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleTestAlert}
            title="Play sound chime and test browser desktop notification"
          >
            <Bell size={14} /> Test Alert
          </button>

          <button
            type="button"
            className={`btn btn-sm ${autoRefresh ? "btn-emerald" : "btn-secondary"}`}
            onClick={() => setAutoRefresh((v) => !v)}
            title="Poll dashboard every 10 seconds"
          >
            <Radio size={14} /> {autoRefresh ? "Live Auto (10s)" : "Auto-Refresh"}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleExport("csv")}>
            <Download size={14} /> Export CSV
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => handleExport("json")}>
            <Download size={14} /> Export JSON
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={() => loadAll(verdictFilter, retentionDays)}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      {urgentAlert && (
        <div
          style={{
            marginBottom: 16,
            padding: "14px 18px",
            background: "linear-gradient(90deg, rgba(239, 68, 68, 0.18), rgba(245, 158, 11, 0.12))",
            border: "1px solid rgba(239, 68, 68, 0.4)",
            borderRadius: 8,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 12,
            boxShadow: "0 4px 16px rgba(239, 68, 68, 0.12)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 36, height: 36, borderRadius: "50%", background: "rgba(239, 68, 68, 0.25)", display: "flex", alignItems: "center", justifyContent: "center", color: "#ef4444" }}>
              <Bell size={20} />
            </div>
            <div>
              <div style={{ fontWeight: 700, color: "#fca5a5", fontSize: 15 }}>
                ⚠️ Action Required: KYC Verification Flagged for Review!
              </div>
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 2 }}>
                Applicant: <strong style={{ color: "var(--text-main)" }}>{urgentAlert.name}</strong> ({urgentAlert.ref})
                {urgentAlert.conf != null && <span> · Match Conf: <strong>{Number(urgentAlert.conf).toFixed(1)}%</strong></span>}
                {urgentAlert.risk != null && <span> · Fraud Score: <strong>{Number(urgentAlert.risk).toFixed(1)}/100</strong></span>}
              </div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {urgentAlert.id && !urgentAlert.id.startsWith("test-") && (
              <button
                type="button"
                className="btn btn-emerald btn-sm"
                onClick={() => {
                  openDetailModal(urgentAlert.id);
                  setUrgentAlert(null);
                }}
              >
                Inspect & Review
              </button>
            )}
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setUrgentAlert(null)}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}

      {bannerMsg && (
        <div className="alert alert-info" style={{ marginBottom: 14, justifyContent: "space-between", alignItems: "center", flexWrap: "wrap" }}>
          <span>{bannerMsg}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setBannerMsg("")}>Dismiss</button>
        </div>
      )}

      {/* KPIs */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-val">{stats?.total ?? "—"}</div>
          <div className="kpi-lbl">Total Sessions</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-val" style={{ color: "var(--emerald)" }}>{stats?.passed ?? "—"}</div>
          <div className="kpi-lbl">Passed</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-val" style={{ color: "var(--amber)" }}>{stats?.review ?? "—"}</div>
          <div className="kpi-lbl">Needs Review</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-val" style={{ color: "var(--rose)" }}>{stats?.failed ?? "—"}</div>
          <div className="kpi-lbl">Failed</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-val" style={{ color: "var(--brand)" }}>{stats ? `${stats.pass_rate}%` : "—"}</div>
          <div className="kpi-lbl">Pass Rate</div>
        </div>
      </div>

      {/* Analytics Row */}
      {analytics && (
        <div className="analytics-grid">
          <div className="card">
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase" }}>
              Verdict Distribution
            </div>
            <div className="dist-bar">
              <div style={{ width: `${(analytics.verdicts.PASS / totalVerdicts) * 100}%`, background: "var(--emerald)" }} />
              <div style={{ width: `${(analytics.verdicts.REVIEW / totalVerdicts) * 100}%`, background: "var(--amber)" }} />
              <div style={{ width: `${(analytics.verdicts.FAIL / totalVerdicts) * 100}%`, background: "var(--rose)" }} />
              <div style={{ width: `${(analytics.verdicts.INCOMPLETE / totalVerdicts) * 100}%`, background: "#475569" }} />
            </div>
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
              Pass {analytics.verdicts.PASS} · Review {analytics.verdicts.REVIEW} · Fail {analytics.verdicts.FAIL} · Incomplete {analytics.verdicts.INCOMPLETE}
            </div>
          </div>

          <div className="card">
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8 }}>
              Operational Metrics
            </div>
            <div className="grid-2" style={{ gap: 6, fontSize: 13 }}>
              <div>Avg Match Conf: <strong>{analytics.avg_confidence}%</strong></div>
              <div>Avg Fraud Score: <strong>{analytics.avg_fraud_score}</strong></div>
              <div>Avg Duration: <strong>{analytics.avg_duration_sec}s</strong></div>
              <div>Spoof Flagged: <strong>{analytics.spoof_flagged} ({analytics.spoof_rate}%)</strong></div>
            </div>
          </div>

          <div className="card">
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8 }}>
              Document Breakdown
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {Object.entries(analytics.id_types).map(([doc, count]) => (
                <span className="badge badge-muted" key={doc}>{doc}: {count}</span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Vault Retention Bar */}
      <div className="card" style={{ marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="badge badge-pass"><Lock size={12} /> Encrypted Vault (AES-128 Fernet)</span>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {vaultStats
              ? `${vaultStats.total_files} blobs (${vaultStats.id_files} ID, ${vaultStats.selfie_files} selfie · ${vaultStats.total_kb} KB) · ${vaultStats.expired_count} expired (>${vaultStats.retention_days}d)`
              : "Loading vault telemetry..."}
          </span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <label style={{ fontSize: 12, color: "var(--text-muted)" }} htmlFor="retDaysInput">Retention (d):</label>
          <input
            id="retDaysInput"
            type="number"
            min={0}
            className="field-input"
            style={{ width: 72, padding: "6px 8px", fontSize: 12 }}
            value={retentionDays}
            onChange={(e) => {
              const d = Math.max(0, parseInt(e.target.value || "30", 10) || 0);
              setRetentionDays(d);
              apiRequest<VaultStats>(`/api/dashboard/vault/stats?retention_days=${d}`)
                .then(setVaultStats)
                .catch(() => {});
            }}
          />
          <button type="button" className="btn btn-danger btn-sm" onClick={() => setPurgeModalOpen(true)}>
            <Trash2 size={13} /> Purge Expired
          </button>
        </div>
      </div>

      {/* Filters & Search */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {["ALL", "PASS", "REVIEW", "FAIL", "INCOMPLETE"].map((f) => (
            <button
              key={f}
              type="button"
              className={`btn btn-sm ${verdictFilter === f ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setVerdictFilter(f)}
            >
              {f}{filterCounts[f] !== undefined ? ` (${filterCounts[f]})` : ""}
            </button>
          ))}
        </div>

        <input
          className="field-input search-input"
          placeholder="Search tracking code, applicant, ID type..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Sessions Table */}
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Ref / Session</th>
              <th>Applicant</th>
              <th>Date</th>
              <th>Verdict</th>
              <th>Confidence</th>
              <th>Fraud Risk</th>
              <th>ID Type</th>
              <th>Review</th>
            </tr>
          </thead>
          <tbody>
            {loadingData && sessions.length === 0 ? (
              Array.from({ length: 4 }).map((_, i) => (
                <tr key={i}>
                  <td colSpan={8}>
                    <div className="skeleton-line" style={{ width: `${92 - i * 6}%` }} />
                  </td>
                </tr>
              ))
            ) : filteredSessions.length === 0 ? (
              <tr><td colSpan={8} style={{ textAlign: "center", color: "var(--text-dim)" }}>No matching sessions found.</td></tr>
            ) : (
              filteredSessions.map((s) => (
                <tr key={s.id} onClick={() => openDetailModal(s.id)}>
                  <td className="mono">{s.tracking_code || s.id.slice(0, 8)}</td>
                  <td>{s.applicant_name || <span style={{ color: "var(--text-dim)" }}>Anonymous</span>}</td>
                  <td>{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</td>
                  <td>
                    <span className={`badge ${s.verdict === "PASS" ? "badge-pass" : s.verdict === "REVIEW" ? "badge-review" : s.verdict === "FAIL" ? "badge-fail" : "badge-muted"}`}>
                      {s.verdict || "INCOMPLETE"}
                    </span>
                  </td>
                  <td>{s.match_confidence ? `${s.match_confidence.toFixed(1)}%` : "—"}</td>
                  <td>
                    <span className={`badge ${s.fraud_score >= 55 ? "badge-fail" : s.fraud_score >= 25 ? "badge-review" : "badge-pass"}`}>
                      {(s.fraud_score || 0).toFixed(1)}
                    </span>
                  </td>
                  <td>{s.id_fields?.id_type || "—"}</td>
                  <td>{s.review_action ? <span className="badge badge-info">{s.review_action}</span> : "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Vault Purge Confirmation Modal */}
      {purgeModalOpen && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (!purgeBusy) setPurgeModalOpen(false);
          }}
        >
          <div className="modal-panel modal-panel-sm" role="dialog" aria-modal="true" aria-label="Confirm vault purge" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div style={{ fontWeight: 800, fontSize: 16, color: "#f87171" }}>
                Purge Expired Evidence Blobs
              </div>
              <button type="button" className="btn btn-secondary btn-sm" disabled={purgeBusy} onClick={() => setPurgeModalOpen(false)}>
                <X size={14} />
              </button>
            </div>
            <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 16 }}>
              Delete encrypted <span className="mono">.enc</span> ID and selfie files older than{" "}
              <strong>{retentionDays} day(s)</strong> from the Fernet Vault? Currently{" "}
              <strong>{vaultStats?.expired_count ?? 0}</strong> file(s) qualify. This cannot be undone.
            </p>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-secondary btn-sm" disabled={purgeBusy} onClick={() => setPurgeModalOpen(false)}>
                Cancel
              </button>
              <button type="button" className="btn btn-danger btn-sm" disabled={purgeBusy} onClick={confirmPurgeVault}>
                <Trash2 size={14} /> {purgeBusy ? "Purging..." : "Confirm Purge"}
              </button>
            </div>
          </div>
        </div>
      )}
      </div>

      {/* Reviewer Session Detail Modal */}
      {detailSession && (
        <div className="modal-backdrop" onClick={closeDetailModal}>
          <div className="modal-panel" role="dialog" aria-modal="true" aria-label="Case Review Workstation" onClick={(e) => e.stopPropagation()}>
            <div className="print-only" style={{ borderBottom: "2px solid #0f172a", paddingBottom: 8, marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", color: "#475569" }}>
                PehchaanAI · Compliance Reviewer Case Dossier
              </div>
              <div style={{ fontSize: 11, color: "#475569" }}>
                Exported: {new Date().toLocaleString()} · Consent Version: v1.0-DPDP
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, gap: 10 }}>
              <div style={{ minWidth: 0 }}>
                <div className="mono" style={{ fontSize: 12, color: "var(--text-dim)", wordBreak: "break-all" }}>
                  {detailSession.tracking_code} · {detailSession.id}
                </div>
                <h2 style={{ fontFamily: "var(--font-head)", fontSize: 20, fontWeight: 800 }}>
                  Case Review Workstation
                </h2>
              </div>
              <div className="no-print" style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.print()} title="Print or save PDF dossier">
                  <Printer size={14} /> Print Dossier
                </button>
                <button type="button" className="btn btn-secondary btn-sm" aria-label="Close modal" onClick={closeDetailModal}>
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* AI Reviewer Triage Brief */}
            {aiBrief && (
              <div className="alert alert-info" style={{ flexDirection: "column", gap: 6, marginBottom: 14 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, width: "100%", flexWrap: "wrap" }}>
                  <Sparkles size={15} /> AI Reviewer Triage Brief
                  <span className="badge badge-muted" style={{ marginLeft: "auto" }}>{aiBrief.provider}</span>
                </div>
                <div>{aiBrief.executive_summary}</div>
                <div style={{ fontSize: 12 }}>
                  Recommended: <strong>{aiBrief.recommended_action.toUpperCase()}</strong> — {aiBrief.recommended_reason}
                </div>
              </div>
            )}

            {/* Key Metrics */}
            <div className="grid-3" style={{ marginBottom: 14 }}>
              <div className="card-subtle">
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Verdict</div>
                <div style={{ fontWeight: 700 }}>{detailSession.verdict || "INCOMPLETE"}</div>
              </div>
              <div className="card-subtle">
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Confidence / Distance</div>
                <div style={{ fontWeight: 700 }}>
                  {detailSession.match_confidence?.toFixed(1)}% ({detailSession.match_distance?.toFixed(4)})
                </div>
              </div>
              <div className="card-subtle">
                <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Unified Fraud Score</div>
                <div style={{ fontWeight: 700 }}>{(detailSession.fraud_score || 0).toFixed(1)}/100</div>
              </div>
            </div>

            {Object.keys(breakdown).length > 0 && (
              <div className="card-subtle" style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Fraud Risk Breakdown</div>
                <div className="grid-4" style={{ gap: 8, fontSize: 12 }}>
                  <div>Face: {breakdown.face_risk ?? 0}/30</div>
                  <div>Spoof/Live: {breakdown.spoof_liveness_risk ?? 0}/35</div>
                  <div>Document: {breakdown.document_risk ?? 0}/10</div>
                  <div>History: {breakdown.history_risk ?? 0}/25</div>
                </div>
              </div>
            )}

            {/* Applicant & Document Details */}
            <div className="card-subtle" style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Applicant, Consent &amp; Document Info</div>
              <div className="grid-2" style={{ gap: 6, fontSize: 12 }}>
                <div>Applicant: {detailSession.applicant_name || "Anonymous"}</div>
                <div>Purpose: {detailSession.purpose || "—"}</div>
                <div>Consent: {detailSession.consent_given ? "Recorded ✓" : "Legacy / Not Set"}</div>
                <div>Anti-Spoof: {detailSession.spoof_detected ? "Flagged ⚠" : `Clean (${detailSession.spoof_score ?? "—"})`}</div>
                <div>ID Type: {detailSession.id_fields?.id_type || "—"}</div>
                <div>ID Number: <span className="mono">{detailSession.id_fields?.id_number || "—"}</span></div>
                <div>OCR Name: {detailSession.id_fields?.name || "—"}</div>
                <div>ID Valid: {detailSession.id_fields?.id_valid === true ? "Valid ✓" : detailSession.id_fields?.id_valid === false ? "Invalid ✕" : "—"}</div>
              </div>
            </div>

            {/* Encrypted Evidence Vault Viewer */}
            <div className="card-subtle" style={{ marginBottom: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    Encrypted Evidence Vault
                    {evidenceLoaded && aadhaarRedacted && (
                      <span className="badge badge-pass">UIDAI 8-Digit Masked</span>
                    )}
                    {evidenceLoaded && (detailSession.id_fields?.id_type || "").toLowerCase() === "aadhaar" && !maskAadhaar && (
                      <span className="badge badge-review">Unmasked View Logged</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-dim)" }}>
                    {detailVault.has_id || detailVault.has_selfie
                      ? `Encrypted blobs available (${detailVault.has_id ? "ID" : ""}${detailVault.has_id && detailVault.has_selfie ? " + " : ""}${detailVault.has_selfie ? "Selfie" : ""}). Viewing logs an audit event.`
                      : "No encrypted vault blobs (legacy plaintext, purged, or erased session)."}
                  </div>
                </div>
                {(detailVault.has_id || detailVault.has_selfie) && (
                  <div className="no-print" style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    {(detailSession.id_fields?.id_type || "").toLowerCase() === "aadhaar" && (
                      <label style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={maskAadhaar}
                          onChange={(e) => {
                            const nextMask = e.target.checked;
                            setMaskAadhaar(nextMask);
                            if (evidenceLoaded) {
                              decryptEvidence(nextMask);
                            }
                          }}
                        />
                        Mask first 8 Aadhaar digits
                      </label>
                    )}
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={decrypting || evidenceLoaded}
                      onClick={() => decryptEvidence(maskAadhaar)}
                    >
                      <Eye size={14} /> {decrypting ? "Decrypting..." : evidenceLoaded ? "Decrypted (Logged)" : "Decrypt & View"}
                    </button>
                  </div>
                )}
              </div>

              {evidenceLoaded && (
                <div className="grid-2" style={{ marginTop: 12 }}>
                  <div className="card" style={{ padding: 10, textAlign: "center" }}>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>ID DOCUMENT</div>
                    {idImgUrl ? <img src={idImgUrl} alt="Decrypted ID" style={{ maxWidth: "100%", maxHeight: 200, borderRadius: 8 }} /> : "Not stored"}
                  </div>
                  <div className="card" style={{ padding: 10, textAlign: "center" }}>
                    <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>LIVE SELFIE</div>
                    {selfieImgUrl ? <img src={selfieImgUrl} alt="Decrypted Selfie" style={{ maxWidth: "100%", maxHeight: 200, borderRadius: 8 }} /> : "Not stored"}
                  </div>
                </div>
              )}
            </div>

            {/* Audit Trail */}
            <div className="card-subtle" style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 8 }}>Audit Trail ({detailTrail.length} events)</div>
              <div style={{ maxHeight: 150, overflowY: "auto", display: "flex", flexDirection: "column", gap: 4 }}>
                {detailTrail.map((ev) => (
                  <div key={ev.id} style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12, borderBottom: "1px solid var(--border)", paddingBottom: 4 }}>
                    <span className="mono">{ev.event_type} <span style={{ color: "var(--text-dim)" }}>({ev.actor})</span></span>
                    <span style={{ color: "var(--text-dim)", flexShrink: 0 }}>{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : ""}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Human Review Action */}
            <div className="card-subtle">
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>Compliance Decision</div>
              {detailSession.review_action && (
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 8 }}>
                  Previous decision: <strong>{detailSession.review_action}</strong> by {detailSession.reviewed_by || "Agent"}
                  {detailSession.review_note ? ` — "${detailSession.review_note}"` : ""}
                </div>
              )}
              <textarea
                className="field-textarea no-print"
                placeholder="Optional compliance review note..."
                value={reviewNote}
                onChange={(e) => setReviewNote(e.target.value)}
              />
              <div className="no-print" style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                <button type="button" className="btn btn-emerald" style={{ flex: "1 1 110px" }} disabled={reviewBusy} onClick={() => submitReview("approved")}>
                  Approve
                </button>
                <button type="button" className="btn btn-secondary" style={{ flex: "1 1 110px" }} disabled={reviewBusy} onClick={() => submitReview("escalated")}>
                  Escalate
                </button>
                <button type="button" className="btn btn-danger" style={{ flex: "1 1 110px" }} disabled={reviewBusy} onClick={() => submitReview("rejected")}>
                  Reject
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
