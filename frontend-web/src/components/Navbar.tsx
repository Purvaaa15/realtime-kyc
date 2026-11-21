// src/components/Navbar.tsx
// Top sticky navigation bar with responsive mobile hamburger menu toggle.
import React, { useEffect, useState } from "react";
import { NavLink, Link, useLocation } from "react-router-dom";
import {
  ShieldCheck,
  Video,
  Search,
  Bot,
  LayoutDashboard,
  UserCircle,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "../context/AuthContext";

export const Navbar: React.FC = () => {
  const { user, health, isReviewer, logout, refreshHealth } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  // Close mobile drawer automatically whenever the user navigates
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <Link to="/" className="brand-link">
          <div className="brand-logo">
            <ShieldCheck size={20} />
          </div>
          <div>
            <span className="brand-title">PehchaanAI</span>
            <span className="brand-sub">Real-Time KYC &amp; Fraud Intelligence</span>
          </div>
        </Link>

        {/* Mobile hamburger toggle — shown only below 860px via CSS */}
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={menuOpen}
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMenuOpen((prev) => !prev)}
        >
          {menuOpen ? <X size={18} /> : <Menu size={18} />}
        </button>

        <div className={`nav-collapse ${menuOpen ? "open" : ""}`}>
          <nav className="nav-links" aria-label="Primary">
            <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              Overview
            </NavLink>
            <NavLink to="/verify" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Video size={14} /> Start KYC
            </NavLink>
            <NavLink to="/status" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Search size={14} /> Track Status
            </NavLink>
            <NavLink to="/assistant" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Bot size={14} /> AI Assistant
            </NavLink>
            <NavLink to="/dashboard" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <LayoutDashboard size={14} /> Reviewer Portal
            </NavLink>
          </nav>

          <div className="nav-right">
            <span
              className="health-pill"
              onClick={() => refreshHealth?.()}
              style={{ cursor: "pointer" }}
              title={
                health
                  ? `API v${health.version} | Redis: ${health.redis ? "OK" : "Down"} | PostgreSQL: ${health.database === false ? "Down" : "OK"} | Tesseract OCR: ${health.tesseract === false ? "Missing" : "OK"} | AI: ${health.ai_mode || "local-grounded"} (Click to recheck)`
                  : "Checking backend services..."
              }
            >
              <span
                className={
                  health && health.redis && health.database !== false && health.tesseract !== false
                    ? "dot-ok"
                    : "dot-warn"
                }
              />
              {!health
                ? "Checking..."
                : !health.redis
                  ? "API Live (No Redis)"
                  : health.database === false
                    ? "DB Offline"
                    : health.tesseract === false
                      ? "Tesseract Missing"
                      : "All Systems Live"}
            </span>

            {user ? (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <NavLink to="/account" className="btn btn-secondary btn-sm">
                  <UserCircle size={14} /> {user.full_name.split(" ")[0]}
                </NavLink>
                <button type="button" className="btn btn-secondary btn-sm" onClick={logout} title="Sign Out">
                  <LogOut size={14} />
                </button>
              </div>
            ) : (
              <NavLink to={isReviewer ? "/dashboard" : "/login"} className="btn btn-primary btn-sm">
                Sign In
              </NavLink>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
