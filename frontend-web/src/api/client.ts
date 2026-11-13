// src/api/client.ts
// Typed HTTP & WebSocket helper functions communicating with FastAPI.

const TOKEN_KEY = "pehchaan_auth_token";
const PASSCODE_KEY = "pehchaan_reviewer_passcode";

export function getAuthToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setAuthToken(token: string) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getReviewerPasscode(): string {
  return sessionStorage.getItem(PASSCODE_KEY) || "";
}

export function setReviewerPasscode(passcode: string) {
  if (passcode) sessionStorage.setItem(PASSCODE_KEY, passcode);
  else sessionStorage.removeItem(PASSCODE_KEY);
}

export function buildAuthHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extra };
  const token = getAuthToken();
  const passcode = getReviewerPasscode();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (passcode) headers["X-Dashboard-Auth"] = passcode;
  return headers;
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const existing = (options.headers as Record<string, string>) || {};
  const headers = buildAuthHeaders(existing);

  const response = await fetch(path, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const errBody = await response.json();
      message = errBody.error || errBody.detail || message;
    } catch {
      // keep HTTP fallback
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function getWebSocketUrl(sessionId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/${encodeURIComponent(sessionId)}`;
}
