// src/pages/LandingPage.tsx
import React from "react";
import { Link } from "react-router-dom";
import {
  ShieldCheck,
  ScanFace,
  FileCheck2,
  Lock,
  Bot,
  BarChart3,
  ArrowRight,
  Search,
  Sparkles,
  CheckCircle2,
} from "lucide-react";

const PIPELINE_STEPS = [
  {
    num: "01",
    title: "Biometric Consent & Session Init",
    desc: "Explicit DPDP camera/biometric consent recorded in PostgreSQL with purpose & Redis TTL.",
  },
  {
    num: "02",
    title: "Real-Time FaceMesh & Blink Liveness",
    desc: "WebSocket 468-point facial landmark streaming + Eye Aspect Ratio (EAR) blink detection.",
  },
  {
    num: "03",
    title: "Multi-Layer Anti-Spoofing Defense",
    desc: "Laplacian sharpness, FFT frequency spectrum, color saturation, and bezel edge checks.",
  },
  {
    num: "04",
    title: "Multi-ID OCR & Checksum Validation",
    desc: "Tesseract + PyMuPDF PDF extraction with 12-digit Aadhaar Verhoeff & PAN validation.",
  },
  {
    num: "05",
    title: "Face Match, Fraud Engine & Vault",
    desc: "128-d cross-domain match, 0–100 Unified Fraud Score, XAI verdict, and AES-128 Fernet vault.",
  },
];

const FEATURES = [
  {
    icon: ScanFace,
    title: "In-Session Real-Time Liveness",
    desc: "Verifies physical presence during the live stream via WebSockets rather than delaying review hours later.",
  },
  {
    icon: FileCheck2,
    title: "Indian Multi-Document Intelligence",
    desc: "Supports Aadhaar, PAN, Driving Licence, Passport, Voter ID, Institutional ID, and PDFs with quality gates.",
  },
  {
    icon: BarChart3,
    title: "Unified Fraud Risk Engine (0–100)",
    desc: "Combines face match confidence, spoof margin, document integrity, and DB history/velocity signals.",
  },
  {
    icon: Lock,
    title: "Encrypted Vault & DPDP Controls",
    desc: "ID & selfie photos are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) with retention purging and erasure.",
  },
  {
    icon: Bot,
    title: "Explainable & Hybrid Agentic AI",
    desc: "Plain-English verdict reasons for users, AI triage briefs for reviewers, and a grounded RAG support chatbot.",
  },
  {
    icon: ShieldCheck,
    title: "Role-Based Compliance Operations",
    desc: "Dedicated Reviewer Portal with analytics, audit-logged decryption, Approve/Escalate/Reject, and CSV/JSON exports.",
  },
];

const SUPPORTED_DOCS = [
  "Aadhaar Card (Verhoeff Checksum)",
  "PAN Card (Format + Entity Validation)",
  "Driving Licence",
  "Indian Passport",
  "Voter ID (EPIC)",
  "Institutional ID",
  "PDF & Photo Uploads",
];

export const LandingPage: React.FC = () => {
  return (
    <div className="page-container">
      {/* Hero Section */}
      <section className="hero-grid">
        <div>
          <div className="hero-eyebrow">
            <Sparkles size={13} /> Real-Time Identity &amp; Fraud Intelligence · SDG 9
          </div>
          <h1 className="hero-title">
            Verify Identities Live — Not Hours After Onboarding
          </h1>
          <p className="hero-subtitle">
            <strong>PehchaanAI</strong> combines live webcam liveness, heuristic anti-spoofing,
            cryptographic Indian ID validation, cross-domain face matching, and a unified fraud risk
            engine into a single transparent decision pipeline with full auditability.
          </p>

          <div className="hero-actions">
            <Link to="/verify" className="btn btn-primary">
              Start Live KYC Verification <ArrowRight size={16} />
            </Link>
            <Link to="/status" className="btn btn-secondary">
              <Search size={15} /> Track Application
            </Link>
            <Link to="/dashboard" className="btn btn-secondary">
              Reviewer Portal
            </Link>
          </div>

          <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: "var(--text-dim)" }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <CheckCircle2 size={14} color="#22c55e" /> AES-128 Fernet Vault
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <CheckCircle2 size={14} color="#22c55e" /> Immutable Audit Trail
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <CheckCircle2 size={14} color="#22c55e" /> Explicit Consent &amp; Erasure
            </span>
          </div>
        </div>

        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
            <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--font-head)" }}>
              5-Stage Real-Time AI Pipeline
            </span>
            <span className="badge badge-info">FastAPI + React</span>
          </div>
          <div className="pipeline-list">
            {PIPELINE_STEPS.map((s) => (
              <div className="pipeline-row" key={s.num}>
                <div className="pipeline-step-num">{s.num}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{s.title}</div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{s.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Capabilities Grid */}
      <section style={{ marginTop: 18 }}>
        <div style={{ marginBottom: 14 }}>
          <h2 style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 700 }}>
            Full-Stack RegTech Platform Capabilities
          </h2>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
            Built for transparent verification, human-in-the-loop compliance reviews, and privacy at rest.
          </p>
        </div>

        <div className="features-grid">
          {FEATURES.map((f) => {
            const Icon = f.icon;
            return (
              <div className="card" key={f.title}>
                <div className="feature-icon">
                  <Icon size={20} />
                </div>
                <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 6 }}>{f.title}</h3>
                <p style={{ fontSize: 13, color: "var(--text-muted)" }}>{f.desc}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Supported IDs & Academic Honesty Notice */}
      <section className="card" style={{ marginTop: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 10 }}>
          Supported Identity Documents &amp; Format Checks
        </h3>
        <div className="docs-strip">
          {SUPPORTED_DOCS.map((doc) => (
            <span className="badge badge-muted" key={doc}>
              {doc}
            </span>
          ))}
        </div>
        <p style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 14 }}>
          Academic Prototype Notice: Anti-spoofing and face matching use calibrated heuristic computer-vision
          thresholds evaluated on sample genuine pairs rather than a commercial deepfake neural network or
          large-scale impostor benchmark. Borderline cases automatically route to the Compliance Reviewer Portal.
        </p>
      </section>
    </div>
  );
};
