// src/context/AuthContext.tsx
import React, { createContext, useContext, useEffect, useState } from "react";
import { apiRequest, getAuthToken, getReviewerPasscode, setAuthToken, setReviewerPasscode } from "../api/client";
import type { HealthStatus, UserProfile } from "../types/kyc";

interface AuthContextValue {
  user: UserProfile | null;
  reviewerPasscodeSet: boolean;
  isReviewer: boolean;
  loadingUser: boolean;
  health: HealthStatus | null;
  activeSessionId: string | null;
  setActiveSessionId: (sid: string | null) => void;
  loginWithToken: (token: string, user: UserProfile) => void;
  unlockWithPasscode: (passcode: string) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [reviewerPasscodeSet, setPasscodeState] = useState<boolean>(() => Boolean(getReviewerPasscode()));
  const [loadingUser, setLoadingUser] = useState<boolean>(true);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const refreshUser = async () => {
    const token = getAuthToken();
    if (!token) {
      setUser(null);
      setLoadingUser(false);
      return;
    }
    try {
      const data = await apiRequest<{ user: UserProfile }>("/api/auth/me");
      setUser(data.user);
    } catch {
      setAuthToken("");
      setUser(null);
    } finally {
      setLoadingUser(false);
    }
  };

  useEffect(() => {
    refreshUser();
    apiRequest<HealthStatus>("/health").then(setHealth).catch(() => setHealth(null));
  }, []);

  const loginWithToken = (token: string, nextUser: UserProfile) => {
    setAuthToken(token);
    setUser(nextUser);
  };

  const unlockWithPasscode = (passcode: string) => {
    setReviewerPasscode(passcode);
    setPasscodeState(Boolean(passcode));
  };

  const logout = () => {
    setAuthToken("");
    setReviewerPasscode("");
    setPasscodeState(false);
    setUser(null);
  };

  const isReviewer = Boolean(
    reviewerPasscodeSet || (user && (user.role === "reviewer" || user.role === "admin"))
  );

  return (
    <AuthContext.Provider
      value={{
        user,
        reviewerPasscodeSet,
        isReviewer,
        loadingUser,
        health,
        activeSessionId,
        setActiveSessionId,
        loginWithToken,
        unlockWithPasscode,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
