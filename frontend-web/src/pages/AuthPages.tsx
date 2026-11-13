// src/pages/AuthPages.tsx
// Full-stack Authentication (Applicant Register/Login + Reviewer Portal Login)
// and Applicant Account History Portal with responsive controls and loading skeletons.
import React, { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { LogIn, UserPlus, ShieldCheck, ExternalLink } from "lucide-react";
import { apiRequest } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { SessionRecord, UserProfile } from "../types/kyc";

export const LoginPage: React.FC<{ initialMode?: "login" | "register" }> = ({ initialMode = "login" }) => {
  const navigate = useNavigate();
  const { loginWithToken, unlockWithPasscode } = useAuth();

  const [tab, setTab] = useState<"login" | "register" | "reviewer">(initialMode);
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [passcode, setPasscode] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const submitApplicantLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");
    setBusy(true);
    try {
      const res = await apiRequest<{ token: string; user: UserProfile }>("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      loginWithToken(res.token, res.user);
      navigate(res.user.role === "reviewer" || res.user.role === "admin" ? "/dashboard" : "/account");
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");
    setBusy(true);
    try {
      const res = await apiRequest<{ token: string; user: UserProfile }>("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ full_name: fullName, email, phone, password }),
      });
      loginWithToken(res.token, res.user);
      navigate("/verify");
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submitReviewerLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");
    setBusy(true);
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
      navigate("/dashboard");
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page-container" style={{ maxWidth: 500 }}>
      <div className="card">
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 18, background: "var(--bg)", padding: 4, borderRadius: 10 }}>
          <button
            type="button"
            className={`btn btn-sm ${tab === "login" ? "btn-primary" : "btn-secondary"}`}
            style={{ flex: "1 1 90px" }}
            onClick={() => { setTab("login"); setErrorMsg(""); }}
          >
            <LogIn size={14} /> Sign In
          </button>
          <button
            type="button"
            className={`btn btn-sm ${tab === "register" ? "btn-primary" : "btn-secondary"}`}
            style={{ flex: "1 1 90px" }}
            onClick={() => { setTab("register"); setErrorMsg(""); }}
          >
            <UserPlus size={14} /> Register
          </button>
          <button
            type="button"
            className={`btn btn-sm ${tab === "reviewer" ? "btn-primary" : "btn-secondary"}`}
            style={{ flex: "1 1 90px" }}
            onClick={() => { setTab("reviewer"); setErrorMsg(""); }}
          >
            <ShieldCheck size={14} /> Reviewer
          </button>
        </div>

        {errorMsg && <div className="alert alert-error" style={{ marginBottom: 14 }}>{errorMsg}</div>}

        {tab === "login" && (
          <form onSubmit={submitApplicantLogin}>
            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Sign In to Your Account</h2>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
              View your previous KYC applications, download certificates, or manage consent.
            </p>
            <div className="field-group">
              <label className="field-label">Email</label>
              <input className="field-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="field-group">
              <label className="field-label">Password</label>
              <input className="field-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? "Signing In..." : "Sign In"}
            </button>
          </form>
        )}

        {tab === "register" && (
          <form onSubmit={submitRegister}>
            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Create Applicant Account</h2>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
              Links your KYC verifications to a personal PostgreSQL profile.
            </p>
            <div className="field-group">
              <label className="field-label">Full Name</label>
              <input className="field-input" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
            </div>
            <div className="field-group">
              <label className="field-label">Email</label>
              <input className="field-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="field-group">
              <label className="field-label">Phone (Optional)</label>
              <input className="field-input" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </div>
            <div className="field-group">
              <label className="field-label">Password (min 6 chars)</label>
              <input className="field-input" type="password" minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? "Creating Account..." : "Create Account & Start KYC"}
            </button>
          </form>
        )}

        {tab === "reviewer" && (
          <form onSubmit={submitReviewerLogin}>
            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Compliance Reviewer Sign In</h2>
            <p style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 14 }}>
              Enter your reviewer passcode OR sign in with the seeded reviewer email (<span className="mono">reviewer@pehchaanai.local</span>).
            </p>
            <div className="field-group">
              <label className="field-label">Dashboard Passcode (Quick Access)</label>
              <input
                className="field-input"
                type="password"
                placeholder="e.g. admin123 (from .env)"
                value={passcode}
                onChange={(e) => setPasscode(e.target.value)}
              />
            </div>
            <div style={{ textAlign: "center", fontSize: 11, color: "var(--text-dim)", margin: "10px 0" }}>
              — OR SIGN IN WITH REVIEWER EMAIL —
            </div>
            <div className="field-group">
              <label className="field-label">Reviewer Email</label>
              <input className="field-input" type="email" placeholder="reviewer@pehchaanai.local" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field-group">
              <label className="field-label">Reviewer Password</label>
              <input className="field-input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <button type="submit" className="btn btn-primary" style={{ width: "100%" }} disabled={busy}>
              {busy ? "Unlocking..." : "Open Reviewer Portal"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export const AccountPage: React.FC = () => {
  const { user, loadingUser } = useAuth();
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    apiRequest<{ sessions: SessionRecord[] }>("/api/auth/sessions")
      .then((d) => setSessions(d.sessions))
      .catch(() => setSessions([]))
      .finally(() => setLoading(false));
  }, [user]);

  if (loadingUser) return <div className="page-container">Loading account...</div>;
  if (!user) {
    return (
      <div className="page-container page-narrow">
        <div className="card" style={{ textAlign: "center" }}>
          <h2 style={{ fontSize: 20, marginBottom: 8 }}>Sign In Required</h2>
          <p style={{ color: "var(--text-muted)", marginBottom: 16 }}>
            Please sign in or register an applicant account to view your verification history.
          </p>
          <Link to="/login" className="btn btn-primary">Go to Sign In</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <div className="card" style={{ marginBottom: 18, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <span className="badge badge-info" style={{ marginBottom: 6 }}>{user.role.toUpperCase()}</span>
          <h1 style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 800 }}>{user.full_name}</h1>
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>{user.email}{user.phone ? ` · ${user.phone}` : ""}</div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Link to="/verify" className="btn btn-primary">Start New KYC</Link>
          {(user.role === "reviewer" || user.role === "admin") && (
            <Link to="/dashboard" className="btn btn-secondary">Reviewer Portal</Link>
          )}
        </div>
      </div>

      <div className="card">
        <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 12 }}>My KYC Verification History</h2>
        {loading ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="skeleton-line" style={{ width: "100%" }} />
            <div className="skeleton-line" style={{ width: "88%" }} />
            <div className="skeleton-line" style={{ width: "74%" }} />
          </div>
        ) : sessions.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
            No completed KYC sessions linked to this account yet.
          </p>
        ) : (
          <div className="data-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tracking Code</th>
                  <th>Date</th>
                  <th>Purpose</th>
                  <th>Verdict</th>
                  <th>Confidence</th>
                  <th>Fraud Risk</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td className="mono">{s.tracking_code}</td>
                    <td>{s.created_at ? new Date(s.created_at).toLocaleString() : "—"}</td>
                    <td>{s.purpose || "Identity Verification"}</td>
                    <td>
                      <span className={`badge ${s.verdict === "PASS" ? "badge-pass" : s.verdict === "REVIEW" ? "badge-review" : "badge-fail"}`}>
                        {s.verdict || "INCOMPLETE"}
                      </span>
                    </td>
                    <td>{s.match_confidence ? `${s.match_confidence.toFixed(1)}%` : "—"}</td>
                    <td>{s.fraud_score !== null && s.fraud_score !== undefined ? s.fraud_score.toFixed(1) : "—"}</td>
                    <td>
                      <Link to={`/status?ref=${encodeURIComponent(s.tracking_code)}`} className="btn btn-secondary btn-sm">
                        Receipt <ExternalLink size={12} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
