// src/App.tsx
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { Navbar } from "./components/Navbar";
import { AssistantDrawer } from "./components/AssistantDrawer";
import { LandingPage } from "./pages/LandingPage";
import { VerifyPage } from "./pages/VerifyPage";
import { StatusPage } from "./pages/StatusPage";
import { LoginPage, AccountPage } from "./pages/AuthPages";
import { AssistantPage } from "./pages/AssistantPage";
import { DashboardPage } from "./pages/DashboardPage";

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <BrowserRouter>
        <div className="app-shell">
          <Navbar />
          <main style={{ flex: 1 }}>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/verify" element={<VerifyPage />} />
              <Route path="/status" element={<StatusPage />} />
              <Route path="/login" element={<LoginPage initialMode="login" />} />
              <Route path="/register" element={<LoginPage initialMode="register" />} />
              <Route path="/account" element={<AccountPage />} />
              <Route path="/assistant" element={<AssistantPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/reviewer" element={<DashboardPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <footer className="footer">
            PehchaanAI · Real-Time Video KYC &amp; Fraud Intelligence · Dept. of Computer Engineering (Group BTech CS-A 47)
          </footer>
          <AssistantDrawer />
        </div>
      </BrowserRouter>
    </AuthProvider>
  );
};

export default App;
