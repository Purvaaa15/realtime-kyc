// src/pages/VerifyPage.tsx
// 4-Step Guided Real-Time KYC Wizard:
//   Step 1: Applicant Metadata & DPDP Biometric Consent
//   Step 2: Live Camera Stream + MediaPipe Landmark Mesh + Blink Liveness + Anti-Spoof Progress + Retry
//   Step 3: Multi-Document ID Drag-and-Drop / Rear Camera Capture + OCR Preview + Validation Pill
//   Step 4: Verdict Receipt + Fraud Risk Gauge + XAI Coach + Printable Certificate
import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  ShieldAlert,
  CheckCircle2,
  Camera,
  UploadCloud,
  ScanFace,
  Printer,
  RotateCcw,
  FileText,
  Sparkles,
  Search,
  RefreshCw,
} from "lucide-react";
import { apiRequest, getWebSocketUrl } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type {
  ExtractedIdFields,
  LandmarkPoint,
  LivenessStatus,
  MatchFaceResponse,
  ScanIdResponse,
  SpoofStatus,
  UserExplainResponse,
  WsFrameResponse,
} from "../types/kyc";

type WizardStep = "consent" | "liveness" | "upload" | "result";

const PURPOSES = [
  "Digital Banking Onboarding",
  "Fintech Wallet Activation",
  "Campus / Institutional Verification",
  "Telecom SIM KYC",
  "Vendor Compliance Onboarding",
];

export const VerifyPage: React.FC = () => {
  const { user, setActiveSessionId } = useAuth();

  const [step, setStep] = useState<WizardStep>("consent");
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [email, setEmail] = useState(user?.email || "");
  const [purpose, setPurpose] = useState(PURPOSES[0]);
  const [consentChecked, setConsentChecked] = useState(false);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [trackingCode, setTrackingCode] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [statusBanner, setStatusBanner] = useState<string>("Review biometric consent to begin.");
  const [busy, setBusy] = useState(false);

  // Live telemetry & stream status
  const [wsState, setWsState] = useState<"idle" | "connecting" | "connected" | "done" | "error">("idle");
  const [faceFound, setFaceFound] = useState(false);
  const [liveness, setLiveness] = useState<LivenessStatus>({
    liveness_passed: false,
    blink_count: 0,
    blinks_required: 2,
    message: "Align your face in the camera frame",
  });
  const [spoof, setSpoof] = useState<SpoofStatus | null>(null);

  // Document scan & drag-and-drop state
  const [scannedFields, setScannedFields] = useState<ExtractedIdFields | null>(null);
  const [selectedFilename, setSelectedFilename] = useState<string>("");
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [dragOver, setDragOver] = useState<boolean>(false);

  // Final result & AI explanation
  const [matchResult, setMatchResult] = useState<MatchFaceResponse | null>(null);
  const [aiExplain, setAiExplain] = useState<UserExplainResponse | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const intervalRef = useRef<number | null>(null);
  const livenessClearedRef = useRef<boolean>(false);

  useEffect(() => {
    if (user && !fullName) setFullName(user.full_name);
    if (user && !email) setEmail(user.email);
  }, [user]);

  const stopMediaAndSocket = () => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  };

  useEffect(() => {
    return () => {
      stopMediaAndSocket();
      setActiveSessionId(null);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, []);

  const drawLandmarks = (landmarks: LandmarkPoint[], imgWidth: number, imgHeight: number) => {
    const canvas = overlayRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!landmarks.length || !imgWidth || !imgHeight) return;

    const sx = canvas.width / imgWidth;
    const sy = canvas.height / imgHeight;
    ctx.fillStyle = "rgba(56, 189, 248, 0.85)";
    for (const pt of landmarks) {
      ctx.beginPath();
      ctx.arc(pt.x * sx, pt.y * sy, 1.4, 0, Math.PI * 2);
      ctx.fill();
    }
  };

  // Extracted helper so both initial launch and "Retry Camera" share the exact setup flow
  const attachCameraAndWebSocket = async (targetSessionId: string) => {
    stopMediaAndSocket();
    livenessClearedRef.current = false;
    setErrorMsg("");
    setWsState("connecting");
    setStatusBanner("Requesting camera permission...");

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" },
      audio: false,
    });
    streamRef.current = stream;

    // Wait briefly for video element mount after setStep("liveness")
    for (let i = 0; i < 20 && !videoRef.current; i++) {
      await new Promise((r) => setTimeout(r, 25));
    }
    const videoEl = videoRef.current;
    if (!videoEl) throw new Error("Camera preview element unavailable");

    videoEl.srcObject = stream;
    await new Promise<void>((resolve) => {
      videoEl.onloadedmetadata = () => {
        videoEl.play().catch(() => {});
        resolve();
      };
    });

    const vw = videoEl.videoWidth || 640;
    const vh = videoEl.videoHeight || 480;
    if (overlayRef.current) {
      overlayRef.current.width = vw;
      overlayRef.current.height = vh;
    }
    if (!captureCanvasRef.current) {
      captureCanvasRef.current = document.createElement("canvas");
    }
    captureCanvasRef.current.width = vw;
    captureCanvasRef.current.height = vh;

    const ws = new WebSocket(getWebSocketUrl(targetSessionId));
    wsRef.current = ws;

    ws.onopen = () => {
      setWsState("connected");
      setStatusBanner("Camera live — look forward and blink naturally twice.");
      intervalRef.current = window.setInterval(() => {
        if (
          !wsRef.current ||
          wsRef.current.readyState !== WebSocket.OPEN ||
          !videoRef.current ||
          !captureCanvasRef.current ||
          livenessClearedRef.current
        ) {
          return;
        }
        const ctx = captureCanvasRef.current.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(videoRef.current, 0, 0, captureCanvasRef.current.width, captureCanvasRef.current.height);
        const b64 = captureCanvasRef.current.toDataURL("image/jpeg", 0.85);
        wsRef.current.send(JSON.stringify({ type: "frame", data: b64 }));
      }, 500);
    };

    ws.onmessage = (event) => {
      const data: WsFrameResponse = JSON.parse(event.data);
      if (data.error) {
        setErrorMsg(data.error);
        return;
      }
      setFaceFound(Boolean(data.face_found));
      if (data.spoof) setSpoof(data.spoof);

      if (data.face_found) {
        drawLandmarks(data.landmarks || [], data.width || vw, data.height || vh);
        setLiveness(data.liveness);
        setStatusBanner(data.liveness.message);

        if (data.liveness.liveness_passed && !livenessClearedRef.current) {
          livenessClearedRef.current = true;
          setWsState("done");
          setStatusBanner("Liveness passed! Upload your ID document.");
          if (intervalRef.current !== null) {
            window.clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
          }
          const ctx = overlayRef.current?.getContext("2d");
          if (ctx && overlayRef.current) ctx.clearRect(0, 0, overlayRef.current.width, overlayRef.current.height);
          setStep("upload");
        }
      } else {
        const ctx = overlayRef.current?.getContext("2d");
        if (ctx && overlayRef.current) ctx.clearRect(0, 0, overlayRef.current.width, overlayRef.current.height);
        setStatusBanner("No face detected — center your face inside the frame.");
      }
    };

    ws.onerror = () => {
      setWsState("error");
      setErrorMsg("WebSocket stream interrupted. Ensure FastAPI is running and click Retry Camera.");
    };
  };

  const startLiveSession = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");

    if (!fullName.trim()) {
      setErrorMsg("Please enter your full name as printed on your ID document.");
      return;
    }
    if (!consentChecked) {
      setErrorMsg("Please read and accept the biometric consent disclosure to proceed.");
      return;
    }

    setBusy(true);
    try {
      const started = await apiRequest<{ session_id: string; tracking_code: string }>("/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          applicant_name: fullName.trim(),
          applicant_email: email.trim() || null,
          purpose,
          consent_given: true,
        }),
      });

      setSessionId(started.session_id);
      setTrackingCode(started.tracking_code);
      setActiveSessionId(started.session_id);
      setStep("liveness");

      await attachCameraAndWebSocket(started.session_id);
    } catch (err) {
      setWsState("error");
      setErrorMsg(
        `${(err as Error).message || "Could not start live verification."} Check camera permissions in Brave and click Retry Camera.`
      );
    } finally {
      setBusy(false);
    }
  };

  const retryCamera = async () => {
    if (!sessionId || busy) return;
    setBusy(true);
    try {
      await attachCameraAndWebSocket(sessionId);
    } catch (err) {
      setWsState("error");
      setErrorMsg((err as Error).message || "Camera access failed. Check browser permissions.");
    } finally {
      setBusy(false);
    }
  };

  const handleIdUpload = async (file: File) => {
    if (!sessionId) return;
    const ext = file.name.toLowerCase().split(".").pop() || "";
    if (!["jpg", "jpeg", "png", "pdf"].includes(ext)) {
      setErrorMsg("Unsupported file type — please upload a JPG, PNG, or PDF ID document.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setErrorMsg("File too large — maximum allowed size is 10 MB.");
      return;
    }

    setErrorMsg("");
    setBusy(true);
    setSelectedFilename(file.name);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    if (file.type.startsWith("image/")) {
      setPreviewUrl(URL.createObjectURL(file));
    } else {
      setPreviewUrl("");
    }
    setStatusBanner("Running OCR extraction and cryptographic validation...");

    try {
      const formData = new FormData();
      formData.append("frame", file, file.name);
      formData.append("session_id", sessionId);

      const res = await apiRequest<ScanIdResponse>("/scan-id", {
        method: "POST",
        body: formData,
      });

      if (!res.success || !res.fields) {
        setErrorMsg(res.error || "Could not extract clear text from the document. Try a sharper flat image.");
        setScannedFields(null);
      } else {
        setScannedFields(res.fields);
        setStatusBanner("Document scanned! Review extracted details and capture your selfie.");
      }
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleFaceMatch = async () => {
    if (!sessionId || !videoRef.current) return;
    setErrorMsg("");
    setBusy(true);
    setStatusBanner("Capturing live selfie & running Fraud Risk Engine...");

    try {
      if (!captureCanvasRef.current) {
        captureCanvasRef.current = document.createElement("canvas");
      }
      const canvas = captureCanvasRef.current;
      canvas.width = videoRef.current.videoWidth || 640;
      canvas.height = videoRef.current.videoHeight || 480;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Unable to capture selfie frame");
      ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);

      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.9));
      if (!blob) throw new Error("Selfie encoding failed");

      const formData = new FormData();
      formData.append("frame", blob, "selfie.jpg");
      formData.append("session_id", sessionId);

      const res = await apiRequest<MatchFaceResponse>("/match-face", {
        method: "POST",
        body: formData,
      });

      setMatchResult(res);
      stopMediaAndSocket();
      setStep("result");
      setStatusBanner(res.verdict.message);

      apiRequest<UserExplainResponse>(`/api/ai/session/${sessionId}/explain`)
        .then(setAiExplain)
        .catch(() => {});
    } catch (err) {
      setErrorMsg((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const resetWizard = () => {
    stopMediaAndSocket();
    setSessionId(null);
    setTrackingCode("");
    setActiveSessionId(null);
    setScannedFields(null);
    setMatchResult(null);
    setAiExplain(null);
    setSpoof(null);
    setFaceFound(false);
    setWsState("idle");
    setErrorMsg("");
    setConsentChecked(false);
    livenessClearedRef.current = false;
    setStep("consent");
    setStatusBanner("Review biometric consent to begin.");
  };

  const stepIndex = { consent: 0, liveness: 1, upload: 2, result: 3 }[step];
  const blinkReq = Math.max(1, liveness.blinks_required ?? 2);
  const blinkPct = liveness.liveness_passed
    ? 100
    : Math.min(100, Math.round(((liveness.blink_count ?? 0) / blinkReq) * 100));
  const spoofPct = spoof ? Math.max(0, Math.min(100, Math.round(spoof.spoof_score * 100))) : 0;

  return (
    <div className="page-container">
      <div className="no-print" style={{ marginBottom: 18, display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 style={{ fontFamily: "var(--font-head)", fontSize: 24, fontWeight: 800 }}>
            Guided Video KYC Verification
          </h1>
          <p style={{ fontSize: 13, color: "var(--text-muted)" }}>{statusBanner}</p>
        </div>
        {trackingCode && (
          <div className="badge badge-info mono">Tracking Code: {trackingCode}</div>
        )}
      </div>

      {/* Stepper */}
      <div className="wizard-stepper no-print">
        {[
          { key: "consent", label: "1. Biometric Consent" },
          { key: "liveness", label: "2. Live Blink & Spoof" },
          { key: "upload", label: "3. ID OCR & Validation" },
          { key: "result", label: "4. Verdict & Certificate" },
        ].map((s, idx) => (
          <div
            key={s.key}
            className={`wizard-step ${idx < stepIndex ? "done" : idx === stepIndex ? "active" : ""}`}
          >
            <CheckCircle2 size={16} style={{ flexShrink: 0 }} />
            <span>{s.label}</span>
          </div>
        ))}
      </div>

      {errorMsg && (
        <div className="alert alert-error no-print" style={{ marginBottom: 16 }}>
          <ShieldAlert size={18} style={{ flexShrink: 0 }} />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* STEP 1: CONSENT */}
      {step === "consent" && (
        <form className="card page-narrow" style={{ margin: "0 auto" }} onSubmit={startLiveSession}>
          <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
            Applicant Details &amp; Biometric Processing Consent
          </h2>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 18 }}>
            Your explicit consent is logged permanently before activating the webcam or storing encrypted evidence.
          </p>

          <div className="grid-2">
            <div className="field-group">
              <label className="field-label" htmlFor="kycFullName">Full Name (as on ID)</label>
              <input
                id="kycFullName"
                className="field-input"
                placeholder="e.g. Aarav Sharma"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>

            <div className="field-group">
              <label className="field-label" htmlFor="kycEmail">Email (for status &amp; erasure rights)</label>
              <input
                id="kycEmail"
                type="email"
                className="field-input"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          <div className="field-group">
            <label className="field-label" htmlFor="kycPurpose">Verification Purpose</label>
            <select
              id="kycPurpose"
              className="field-select"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            >
              {PURPOSES.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>

          <div className="card-subtle" style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>
              DPDP Privacy &amp; Security Disclosure (v1.0-DPDP)
            </div>
            <ul style={{ fontSize: 12, color: "var(--text-muted)", paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
              <li>Live video frames are analyzed in memory for facial landmarks, blinks, and spoofing cues.</li>
              <li>Your uploaded ID card and final selfie are encrypted at rest inside the Fernet Vault (AES-128-CBC + HMAC-SHA256).</li>
              <li>Every reviewer inspection is recorded in the audit trail; retention defaults to 30 days and you may erase your biometrics anytime on Track Status.</li>
            </ul>
            <label style={{ display: "flex", alignItems: "flex-start", gap: 10, marginTop: 12, fontSize: 13, cursor: "pointer" }}>
              <input
                type="checkbox"
                checked={consentChecked}
                onChange={(e) => setConsentChecked(e.target.checked)}
                style={{ width: 16, height: 16, marginTop: 2, flexShrink: 0 }}
              />
              <span>I consent to live camera capture, OCR extraction, and encrypted biometric verification.</span>
            </label>
          </div>

          <button type="submit" className="btn btn-primary" disabled={busy}>
            <Camera size={16} />
            {busy ? "Starting Session..." : "Give Consent & Open Camera"}
          </button>
        </form>
      )}

      {/* STEP 2 & 3: STUDIO (KEEP VIDEO MOUNTED ACROSS LIVENESS -> UPLOAD) */}
      {(step === "liveness" || step === "upload") && (
        <div className="verify-studio">
          {/* Left column: camera feed OR ID upload dropzone */}
          <div className="card">
            <div style={{ display: step === "liveness" ? "block" : "none" }}>
              <div className="camera-frame">
                <video ref={videoRef} autoPlay playsInline muted />
                <canvas ref={overlayRef} />
                <div className="live-tag">
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: "#fff" }} />
                  {wsState === "connected" ? "LIVE STREAM" : wsState === "error" ? "PAUSED" : "CONNECTING"}
                </div>
              </div>
              <p style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>
                Look straight toward the webcam in even front lighting. Avoid heavy window backlighting or sunglasses.
              </p>
            </div>

            {step === "upload" && (
              <div>
                <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 6 }}>
                  Upload Identity Document (Step 3)
                </h2>
                <p style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 14 }}>
                  Drag and drop or select a sharp flat photo / PDF of your Aadhaar, PAN, Driving Licence, Passport, Voter ID, or Institutional ID.
                </p>

                <label
                  className={`upload-dropzone ${dragOver ? "drag-over" : ""}`}
                  style={{ display: "block" }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragOver(true);
                  }}
                  onDragLeave={() => setDragOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragOver(false);
                    const f = e.dataTransfer.files?.[0];
                    if (f) handleIdUpload(f);
                  }}
                >
                  <UploadCloud size={30} color="#38bdf8" style={{ margin: "0 auto 8px" }} />
                  <div style={{ fontWeight: 600, fontSize: 14 }}>
                    {selectedFilename
                      ? `Selected: ${selectedFilename} (drop or click to replace)`
                      : "Drag & drop ID here, or click to browse"}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 4 }}>
                    JPG, PNG, or PDF · Max 10 MB
                  </div>
                  <input
                    type="file"
                    accept=".jpg,.jpeg,.png,.pdf"
                    style={{ display: "none" }}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) handleIdUpload(f);
                    }}
                  />
                </label>

                <div style={{ display: "flex", justifyContent: "center", marginTop: 10 }}>
                  <label className="btn btn-secondary btn-sm" style={{ cursor: "pointer" }}>
                    <Camera size={14} /> Snap ID with Device Camera
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) handleIdUpload(f);
                      }}
                    />
                  </label>
                </div>

                {previewUrl && (
                  <div style={{ marginTop: 14, textAlign: "center" }}>
                    <img
                      src={previewUrl}
                      alt="Uploaded ID preview"
                      style={{ maxHeight: 200, maxWidth: "100%", borderRadius: 10, border: "1px solid var(--border)" }}
                    />
                  </div>
                )}

                {scannedFields && (
                  <div className="card-subtle" style={{ marginTop: 16 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
                      <span style={{ fontWeight: 700, fontSize: 14, display: "inline-flex", alignItems: "center", gap: 6 }}>
                        <FileText size={16} color="#38bdf8" /> Extracted Document Fields
                      </span>
                      {scannedFields.id_valid === true ? (
                        <span className="badge badge-pass">Validation Passed</span>
                      ) : scannedFields.id_valid === false ? (
                        <span className="badge badge-fail">Validation Failed</span>
                      ) : (
                        <span className="badge badge-info">Parsed</span>
                      )}
                    </div>

                    <div className="grid-2" style={{ fontSize: 13 }}>
                      <div><span style={{ color: "var(--text-dim)" }}>Type:</span> {scannedFields.id_type || "—"}</div>
                      <div><span style={{ color: "var(--text-dim)" }}>ID Number:</span> <span className="mono">{scannedFields.id_number || "—"}</span></div>
                      <div><span style={{ color: "var(--text-dim)" }}>Name:</span> {scannedFields.name || "—"}</div>
                      <div><span style={{ color: "var(--text-dim)" }}>DOB:</span> {scannedFields.dob || "—"}</div>
                    </div>
                    {scannedFields.validation_note && (
                      <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
                        Note: {scannedFields.validation_note}
                      </div>
                    )}

                    <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <button type="button" className="btn btn-emerald" disabled={busy} onClick={handleFaceMatch}>
                        <ScanFace size={16} />
                        {busy ? "Matching Face..." : "Look at Camera & Match Face"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right column: live biometric telemetry */}
          <div className="card telemetry-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 700, fontSize: 14 }}>Biometric Telemetry</span>
              <span className={`badge ${wsState === "error" ? "badge-fail" : "badge-info"}`}>
                {wsState === "connected"
                  ? "WS Live"
                  : wsState === "done"
                  ? "Liveness Done"
                  : wsState === "error"
                  ? "Stream Error"
                  : "Connecting"}
              </span>
            </div>

            <div className="telemetry-row">
              <span>Consent Recorded</span>
              <span className="badge badge-pass">Verified</span>
            </div>

            <div className="telemetry-row">
              <span>Face Landmark Mesh</span>
              <span className={`badge ${faceFound ? "badge-pass" : "badge-muted"}`}>
                {faceFound ? "468 pts Locked" : "Searching..."}
              </span>
            </div>

            <div className="telemetry-block">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span>Blink Liveness</span>
                <span className={`badge ${liveness.liveness_passed ? "badge-pass" : "badge-review"}`}>
                  {liveness.liveness_passed
                    ? "Confirmed"
                    : `${liveness.blink_count ?? 0}/${blinkReq} Blinks`}
                </span>
              </div>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: `${blinkPct}%` }} />
              </div>
            </div>

            <div className="telemetry-block">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span>Anti-Spoof Stability</span>
                <span className={`badge ${spoof ? (spoof.is_live ? "badge-pass" : "badge-fail") : "badge-muted"}`}>
                  {spoof ? (spoof.is_live ? `Live (${spoof.spoof_score})` : `Warning (${spoof.spoof_score})`) : "Sampling..."}
                </span>
              </div>
              <div className="progress-track">
                <div
                  className={`progress-fill ${spoof && !spoof.is_live ? "warn" : ""}`}
                  style={{ width: `${spoofPct}%` }}
                />
              </div>
            </div>

            <div className="telemetry-row">
              <span>ID OCR Scan</span>
              <span className={`badge ${scannedFields ? "badge-pass" : "badge-muted"}`}>
                {scannedFields ? (scannedFields.id_type || "Scanned") : "Pending"}
              </span>
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
              {step === "liveness" && (wsState === "error" || wsState === "idle") && (
                <button type="button" className="btn btn-primary btn-sm" style={{ flex: 1 }} disabled={busy} onClick={retryCamera}>
                  <RefreshCw size={13} /> Retry Camera
                </button>
              )}
              <button type="button" className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={resetWizard}>
                <RotateCcw size={13} /> Cancel &amp; Restart
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STEP 4: VERDICT RECEIPT & PRINTABLE CERTIFICATE */}
      {step === "result" && matchResult && (
        <div className="card page-narrow" style={{ margin: "0 auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 12, borderBottom: "1px solid var(--border)", paddingBottom: 16, marginBottom: 18 }}>
            <div>
              <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-dim)" }}>
                PehchaanAI Verification Certificate
              </div>
              <h2 style={{ fontFamily: "var(--font-head)", fontSize: 22, fontWeight: 800, marginTop: 4 }}>
                {matchResult.verdict.message}
              </h2>
              <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
                Applicant: <strong>{fullName}</strong> · Purpose: {purpose}
              </div>
            </div>

            <div style={{ textAlign: "right" }}>
              <span
                className={`badge ${
                  matchResult.verdict.verdict === "PASS"
                    ? "badge-pass"
                    : matchResult.verdict.verdict === "REVIEW"
                    ? "badge-review"
                    : "badge-fail"
                }`}
                style={{ fontSize: 14, padding: "6px 14px" }}
              >
                {matchResult.verdict.verdict}
              </span>
              <div className="mono" style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 6 }}>
                Ref: {trackingCode}
              </div>
            </div>
          </div>

          {/* Metrics Row */}
          <div className="grid-3" style={{ marginBottom: 18 }}>
            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Face Match Confidence</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: "var(--brand)" }}>
                {matchResult.match.confidence !== null ? `${matchResult.match.confidence.toFixed(1)}%` : "—"}
              </div>
            </div>

            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Unified Fraud Risk</div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {matchResult.fraud.fraud_score.toFixed(1)}/100{" "}
                <span className="badge badge-muted">{matchResult.fraud.risk_level}</span>
              </div>
            </div>

            <div className="card-subtle">
              <div style={{ fontSize: 11, color: "var(--text-dim)" }}>Document Scanned</div>
              <div style={{ fontSize: 16, fontWeight: 700, marginTop: 4 }}>
                {scannedFields?.id_type || "ID Card"}
              </div>
            </div>
          </div>

          {/* AI Coach Explanation */}
          {aiExplain && (
            <div className="alert alert-info" style={{ flexDirection: "column", gap: 6, marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, width: "100%", flexWrap: "wrap" }}>
                <Sparkles size={15} /> {aiExplain.headline}
                <span className="badge badge-muted" style={{ marginLeft: "auto" }}>{aiExplain.provider}</span>
              </div>
              <p>{aiExplain.summary}</p>
              {aiExplain.next_steps.length > 0 && (
                <ul style={{ paddingLeft: 18, marginTop: 4 }}>
                  {aiExplain.next_steps.map((ns, i) => (
                    <li key={i}>{ns}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Explainable Verdict Reasons */}
          <div className="card-subtle" style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>Explainable Audit Signals</div>
            <ul style={{ paddingLeft: 18, fontSize: 13, color: "var(--text-muted)", display: "flex", flexDirection: "column", gap: 4 }}>
              {(matchResult.verdict.verdict_reasons || []).map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>

          <div className="no-print" style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button type="button" className="btn btn-primary" onClick={() => window.print()}>
              <Printer size={15} /> Print / Save Certificate
            </button>
            <Link to={`/status?ref=${encodeURIComponent(trackingCode)}`} className="btn btn-secondary">
              <Search size={15} /> View Status &amp; Privacy Erasure
            </Link>
            <button type="button" className="btn btn-secondary" onClick={resetWizard}>
              <RotateCcw size={15} /> New Verification
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
