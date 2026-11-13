// src/types/kyc.ts
// TypeScript interfaces matching the FastAPI backend responses verbatim.

export type UserRole = "applicant" | "reviewer" | "admin";

export interface UserProfile {
  id: string;
  full_name: string;
  email: string;
  phone?: string | null;
  role: UserRole;
  created_at?: string | null;
}

export interface HealthStatus {
  status: string;
  version: string;
  redis: boolean;
  database?: boolean;
  tesseract?: boolean;
  frontend?: string;
  ai_mode?: string;
}

export interface LandmarkPoint {
  x: number;
  y: number;
}

export interface LivenessStatus {
  liveness_passed: boolean;
  blink_count?: number;
  blinks_required?: number;
  message: string;
}

export interface SpoofStatus {
  is_live: boolean;
  spoof_score: number;
  texture_score?: number;
  frequency_score?: number;
  sharpness_score?: number;
  bezel_score?: number;
  message?: string;
}

export interface WsFrameResponse {
  face_found: boolean;
  landmarks: LandmarkPoint[];
  width?: number;
  height?: number;
  liveness: LivenessStatus;
  spoof?: SpoofStatus;
  error?: string;
}

export interface ExtractedIdFields {
  id_type?: string | null;
  name?: string | null;
  dob?: string | null;
  id_number?: string | null;
  id_valid?: boolean | null;
  validation_note?: string | null;
  redacted?: boolean;
}

export interface ScanIdResponse {
  success: boolean;
  error?: string;
  fields?: ExtractedIdFields;
}

export interface FraudBreakdown {
  face_risk: number;
  spoof_liveness_risk: number;
  document_risk: number;
  history_risk: number;
}

export interface FraudResult {
  fraud_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
  breakdown: FraudBreakdown;
  risk_factors: string[];
}

export interface VerdictResult {
  verdict: "PASS" | "REVIEW" | "FAIL" | "INCOMPLETE";
  message: string;
  color: string;
  checks: Record<string, boolean>;
  passed_count: number;
  total_checks: number;
  match_confidence: number;
  fraud_score: number;
  risk_level: string;
  id_fields: ExtractedIdFields;
  verdict_reasons: string[];
}

export interface MatchFaceResponse {
  match: {
    matched: boolean;
    distance: number | null;
    confidence: number | null;
    message: string;
  };
  fraud: FraudResult;
  verdict: VerdictResult;
}

export interface SessionRecord {
  id: string;
  tracking_code: string;
  user_id?: string | null;
  applicant_name?: string | null;
  applicant_email?: string | null;
  purpose?: string | null;
  consent_given: boolean;
  consent_at?: string | null;
  erased_at?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  verdict: string | null;
  verdict_message?: string | null;
  face_found: boolean;
  liveness_passed: boolean;
  id_scanned: boolean;
  face_matched: boolean;
  match_confidence: number;
  match_distance: number;
  fraud_score: number;
  liveness_blinks: number;
  spoof_detected: boolean;
  spoof_score?: number | null;
  id_fields?: ExtractedIdFields | null;
  verdict_reasons?: string[] | null;
  ip_address?: string | null;
  user_agent?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
  review_action?: string | null;
  reviewed_at?: string | null;
}

export interface PublicReceipt {
  session_id: string;
  tracking_code: string;
  applicant_name?: string | null;
  purpose?: string | null;
  consent_given: boolean;
  consent_at?: string | null;
  erased_at?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  verdict?: string | null;
  verdict_message?: string | null;
  verdict_reasons: string[];
  match_confidence?: number | null;
  fraud_score?: number | null;
  liveness_passed: boolean;
  liveness_blinks: number;
  spoof_detected: boolean;
  id_type?: string | null;
  id_number_masked?: string | null;
  id_valid?: boolean | null;
  validation_note?: string | null;
  reviewed_by?: string | null;
  review_action?: string | null;
  review_note?: string | null;
  reviewed_at?: string | null;
  vault_present: boolean;
}

export interface AuditEventItem {
  id: number;
  session_id: string;
  timestamp: string | null;
  event_type: string;
  details?: Record<string, unknown> | null;
  actor: string;
}

export interface DashboardStats {
  total: number;
  passed: number;
  failed: number;
  review: number;
  pass_rate: number;
}

export interface DashboardAnalytics {
  total: number;
  verdicts: { PASS: number; REVIEW: number; FAIL: number; INCOMPLETE: number };
  avg_confidence: number;
  avg_fraud_score: number;
  high_risk_count: number;
  avg_duration_sec: number;
  spoof_flagged: number;
  spoof_rate: number;
  id_types: Record<string, number>;
}

export interface VaultStats {
  total_files: number;
  id_files: number;
  selfie_files: number;
  total_bytes: number;
  total_kb: number;
  expired_count: number;
  retention_days: number;
}

export interface UserExplainResponse {
  headline: string;
  summary: string;
  next_steps: string[];
  reasons: string[];
  provider: string;
}

export interface ReviewerAiSummary {
  executive_summary: string;
  risk_highlights: string[];
  recommended_action: "approve" | "escalate" | "reject";
  recommended_reason: string;
  reasons: string[];
  audit_count: number;
  provider: string;
}

export interface AiChatResponse {
  answer: string;
  provider: string;
  citations: string[];
  retrieved_chunks: number;
}
