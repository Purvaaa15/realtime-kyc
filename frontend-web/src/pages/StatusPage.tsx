// src/pages/StatusPage.tsx
// Public Application Status Lookup & DPDP Right-to-Erasure controls
// with responsive receipt grid and a styled confirmation modal.
import React, { useEffect, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { Search, Trash2, Printer, ShieldAlert, CheckCircle2, Sparkles, X } from "lucide-react";
import { apiRequest } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { PublicReceipt, UserExplainResponse } from "../types/kyc";

export const StatusPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const { setActiveSessionId } = useAuth();

  const [refInput, setRefInput] = useState(searchParams.get("ref") || "");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [receipt, setReceipt] = useState<PublicReceipt | null>(null);
  const [explain, setExplain] = useState<UserExplainResponse | null>(null);

  const [eraseEmail, setEraseEmail] = useState("");
  const [eraseModalOpen, setEraseModalOpen] = useState(false);
  const [eraseBusy, setEraseBusy] = useState(false);
  const [eraseMsg, setEraseMsg] = useState("");

  const lookup = async (targetRef: string) => {
    const clean = targetRef.trim();
    if (!clean) return;
    setLoading(true);
    setErrorMsg("");
    setEraseMsg("");
    setExplain(null);

    try {
      const data = await apiRequest<{ found: boolean; receipt: PublicReceipt }>(
        `/api/status/${encodeURIComponent(clean)}`
      );
      setReceipt(data.receipt);
      setActiveSessionId(data.receipt.session_id);
      apiRequest<UserExplainResponse>(`/api/ai/session/${encodeURIComponent(data.receipt.session_id)}/explain`)
        .then(setExplain)
        .catch(() => {});
    } catch (err) {
      setReceipt(null);
      setErrorMsg((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const initialRef = searchParams.get("ref");
    if (initialRef) {
      setRefInput(initialRef);
      lookup(initialRef);
    }
    return () => setActiveSessionId(null);
  }, []);

  // Close DPDP confirmation modal on Escape and lock body scroll while open
  useEffect(() => {
    if (!eraseModalOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !eraseBusy) setEraseModalOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [eraseModalOpen, eraseBusy]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (refInput.trim()) {
      setSearchParams({ ref: refInput.trim() });
      lookup(refInput);
    }
  };

  const confirmAndErase = async () => {
    if (!receipt) return;
    setEraseBusy(true);
    setErrorMsg("");
    try {
      const res = await apiRequest<{ success: boolean; message: string; deleted_blobs: number }>(
        `/api/sessions/${encodeURIComponent(receipt.session_id)}/erase`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: eraseEmail.trim() }),
        }
      );
      setEraseModalOpen(false);
      setEraseMsg(`${res.message} (${res.deleted_blobs} vault blob(s) deleted).`);
      await lookup(receipt.session_id);
    } catch (err) {
      setEraseModalOpen(false);
      setErrorMsg((err as Error).message);
    } finally {
      setEraseBusy(false);
    }
  };

  return (
    <div className="page-container page-narrow">
      <div className="no-print" style={{ marginBottom: 18 }}>
        <h1 style={{ fontFamily: "var(--font-head)", fontSize: 24, fontWeight: 800 }}>
          Application Status &amp; Privacy Controls
        </h1>
        <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
          Look up any KYC verification by Tracking Code (e.g. <span className="mono">KYC-9772548D</span>) or full Session ID.
        </p>
      </div>

      <form className="card no-print" onSubmit={handleSearch} style={{ display: "flex", gap: 10, marginBottom: 18, flexWrap: "wrap" }}>
        <input
          className="field-input"
          style={{ flex: "1 1 220px" }}
          placeholder="Enter Tracking Code or Session UUID..."
          value={refInput}
          onChange={(e) => setRefInput(e.target.value)}
        />
        <button type="submit" className="btn btn-primary" disabled={loading}>
          <Search size={15} /> {loading ? "Looking up..." : "Track Application"}
        </button>
      </form>

      {errorMsg && (
        <div className="alert alert-error" style={{ marginBottom: 16 }}>
          <ShieldAlert size={17} style={{ flexShrink: 0 }} /> <span>{errorMsg}</span>
        </div>
      )}

      {eraseMsg && (
        <div className="alert alert-success" style={{ marginBottom: 16 }}>
          <CheckCircle2 size={17} style={{ flexShrink: 0 }} /> <span>{eraseMsg}</span>
        </div>
      )}

      {receipt && (
        <div className="card">
          <div className="print-only" style={{ borderBottom: "2px solid #0f172a", paddingBottom: 10, marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "#475569" }}>
              PehchaanAI · Real-Time Identity &amp; Fraud Intelligence
            </div>
            <div style={{ fontSize: 18, fontWeight: 800, marginTop: 2 }}>
              Official Video KYC Verification Certificate
            </div>
            <div style={{ fontSize: 11, color: "#475569", marginTop: 2 }}>
              Generated: {new Date().toLocaleString()} · Consent Version: v1.0-DPDP
            </div>
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, paddingBottom: 16, borderBottom: "1px solid var(--border)", marginBottom: 16 }}>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 12, color: "var(--text-dim)", wordBreak: "break-all" }}>
                {receipt.tracking_code} · {receipt.session_id}
              </div>
              <h2 style={{ fontFamily: "var(--font-head)", fontSize: 20, fontWeight: 800, marginTop: 4 }}>
                {receipt.verdict_message || "Verification Record"}
              </h2>
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 4 }}>
                Applicant: <strong>{receipt.applicant_name || "Anonymous Session"}</strong> · Purpose: {receipt.purpose || "Identity Verification"}
              </div>
            </div>

            <span
              className={`badge ${
                receipt.verdict === "PASS"
                  ? "badge-pass"
                  : receipt.verdict === "REVIEW"
                  ? "badge-review"
                  : receipt.verdict === "FAIL"
                  ? "badge-fail"
                  : "badge-muted"
              }`}
              style={{ fontSize: 13, padding: "5px 12px" }}
            >
              {receipt.verdict || "IN PROGRESS"}
            </span>
          </div>

          <div className="grid-4" style={{ marginBottom: 16 }}>
            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Match Confidence</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--brand)" }}>
                {receipt.match_confidence !== null && receipt.match_confidence !== undefined
                  ? `${receipt.match_confidence.toFixed(1)}%`
                  : "—"}
              </div>
            </div>
            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Fraud Risk</div>
              <div style={{ fontSize: 18, fontWeight: 700 }}>
                {receipt.fraud_score !== null && receipt.fraud_score !== undefined
                  ? `${receipt.fraud_score.toFixed(1)}/100`
                  : "—"}
              </div>
            </div>
            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Document</div>
              <div style={{ fontSize: 14, fontWeight: 600 }}>
                {receipt.id_type || "—"} {receipt.id_number_masked ? `(${receipt.id_number_masked})` : ""}
              </div>
            </div>
            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Vault &amp; Consent</div>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {receipt.erased_at
                  ? "PII Erased"
                  : `${receipt.consent_given ? "Consent ✓" : "Legacy"} · ${receipt.vault_present ? "Encrypted" : "No Blob"}`}
              </div>
            </div>
          </div>

          {receipt.review_action && (
            <div className="alert alert-info" style={{ marginBottom: 14 }}>
              <div>
                <strong>Reviewer Decision:</strong> {receipt.review_action.toUpperCase()} by {receipt.reviewed_by || "Reviewer"}
                {receipt.review_note && <div style={{ marginTop: 4 }}>Note: {receipt.review_note}</div>}
              </div>
            </div>
          )}

          {explain && (
            <div className="card-subtle" style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 700, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                <Sparkles size={15} color="#38bdf8" /> {explain.headline}
                <span className="badge badge-muted" style={{ marginLeft: "auto" }}>{explain.provider}</span>
              </div>
              <p style={{ fontSize: 13, color: "var(--text-muted)" }}>{explain.summary}</p>
            </div>
          )}

          {receipt.verdict_reasons.length > 0 && (
            <div className="card-subtle" style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Verification Audit Signals</div>
              <ul style={{ paddingLeft: 18, fontSize: 12, color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: 3 }}>
                {receipt.verdict_reasons.map((r, idx) => (
                  <li key={idx}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="no-print" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", flexWrap: "wrap", gap: 14, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => window.print()}>
                <Printer size={14} /> Print Receipt
              </button>
              <Link to="/verify" className="btn btn-primary btn-sm">
                Start New KYC
              </Link>
            </div>

            {!receipt.erased_at && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", width: "min(100%, 460px)", justifyContent: "flex-end" }}>
                <input
                  className="field-input erase-email-input"
                  placeholder="Confirm email (if used)"
                  value={eraseEmail}
                  onChange={(e) => setEraseEmail(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  disabled={eraseBusy}
                  onClick={() => setEraseModalOpen(true)}
                >
                  <Trash2 size={14} /> {eraseBusy ? "Erasing..." : "Erase My Biometric Data"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Custom DPDP Right-to-Erasure Confirmation Modal */}
      {eraseModalOpen && receipt && (
        <div
          className="modal-backdrop"
          onClick={() => {
            if (!eraseBusy) setEraseModalOpen(false);
          }}
        >
          <div className="modal-panel modal-panel-sm" role="dialog" aria-modal="true" aria-label="Confirm biometric data erasure" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, color: "#f87171", fontWeight: 800, fontSize: 16 }}>
                <ShieldAlert size={18} /> Confirm DPDP Biometric Erasure
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={eraseBusy}
                onClick={() => setEraseModalOpen(false)}
              >
                <X size={14} />
              </button>
            </div>

            <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 12 }}>
              This action permanently deletes encrypted ID and selfie blobs from the Evidence Vault for{" "}
              <strong className="mono">{receipt.tracking_code}</strong>, redacts applicant PII in PostgreSQL, and
              records an immutable <span className="mono">pii_erased</span> audit event.
            </p>
            <p style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 16 }}>
              This cannot be undone once confirmed.
            </p>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={eraseBusy}
                onClick={() => setEraseModalOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-danger btn-sm"
                disabled={eraseBusy}
                onClick={confirmAndErase}
              >
                <Trash2 size={14} /> {eraseBusy ? "Erasing Vault & PII..." : "Permanently Erase"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
