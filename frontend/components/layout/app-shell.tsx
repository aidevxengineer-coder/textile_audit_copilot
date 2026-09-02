"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { BrandMark } from "@/components/ui/brand-mark";
import { Icon } from "@/components/ui/icon";
import { logoutUser } from "@/lib/browser-api";
import type { User } from "@/lib/types";

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const workspaceView = searchParams.get("view") || "projects";
  const pageName = pathname.startsWith("/admin")
    ? "Administration"
    : pathname.startsWith("/report")
      ? "Report"
      : workspaceView === "evidence"
        ? "Evidence"
        : workspaceView === "review"
          ? "Review"
          : "Projects";

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logoutUser();
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <div className={`workspace-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      {mobileOpen ? (
        <button aria-label="Close navigation" className="nav-backdrop" onClick={() => setMobileOpen(false)} type="button" />
      ) : null}
      <aside className={`workspace-rail ${mobileOpen ? "mobile-open" : ""}`}>
        <div className="brand-block">
          <BrandMark small />
          <div className="sidebar-label">
            <strong>AuditReady AI</strong>
            <span>Compliance workspace</span>
          </div>
          <button aria-label="Close navigation" className="icon-button rail-mobile-close" onClick={() => setMobileOpen(false)} type="button">
            <Icon name="close" />
          </button>
        </div>

        <p className="nav-section-label sidebar-label">Workspace</p>
        <nav className="workspace-nav">
          <Link
            aria-label="Projects"
            className={pathname.startsWith("/chat") && workspaceView === "projects" ? "active" : ""}
            href="/chat?view=projects"
            onClick={() => setMobileOpen(false)}
          >
            <Icon name="folder" /><span className="sidebar-label">Projects</span>
          </Link>
          <Link
            aria-label="Evidence"
            className={pathname.startsWith("/chat") && workspaceView === "evidence" ? "active" : ""}
            href="/chat?view=evidence"
            onClick={() => setMobileOpen(false)}
          >
            <Icon name="document" /><span className="sidebar-label">Evidence</span>
          </Link>
          <Link
            aria-label="Review"
            className={pathname.startsWith("/chat") && workspaceView === "review" ? "active" : ""}
            href="/chat?view=review"
            onClick={() => setMobileOpen(false)}
          >
            <Icon name="chat" /><span className="sidebar-label">Review</span>
          </Link>
          {user.role === "admin" ? (
            <Link aria-label="Administration" className={pathname.startsWith("/admin") ? "active" : ""} href="/admin" onClick={() => setMobileOpen(false)}>
              <Icon name="admin" /><span className="sidebar-label">Administration</span>
            </Link>
          ) : null}
        </nav>

        <div className="rail-security sidebar-label">
          <Icon name="shield" />
          <div><strong>Protected workspace</strong><span>Encrypted files and secure sessions</span></div>
        </div>
        <div className="workspace-note account-panel">
          <Icon className="account-user-icon" name="user" />
          <div className="sidebar-label user-copy">
            <strong>{user.full_name}</strong>
            <span>{user.email}</span>
            <small>{user.role === "admin" ? "Administrator" : "Factory user"}</small>
          </div>
          <button aria-label="Sign out" className="account-signout" disabled={signingOut} onClick={() => void handleSignOut()} type="button">
            <span className="sidebar-label">Sign out</span><Icon name="logout" />
          </button>
        </div>
      </aside>

      <div className="workspace-content">
        <header className="workspace-topbar">
          <div className="topbar-left">
            <button aria-label="Open navigation" className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} type="button"><Icon name="menu" /></button>
            <button aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="icon-button desktop-collapse" onClick={() => setCollapsed((value) => !value)} type="button"><Icon name="menu" /></button>
            <div className="history-navigation" aria-label="Page history navigation">
              <button aria-label="Go back" className="icon-button" onClick={() => router.back()} title="Back" type="button"><Icon name="arrowBack" /></button>
              <button aria-label="Go forward" className="icon-button" onClick={() => router.forward()} title="Forward" type="button"><Icon name="arrow" /></button>
            </div>
            <div className="breadcrumbs"><span>Workspace</span><Icon name="chevron" /><strong>{pageName}</strong></div>
          </div>
          <div className="topbar-actions"><span className="system-live"><i /> Secure workspace online</span></div>
        </header>
        <main className="workspace-main">{children}</main>
      </div>
    </div>
  );
}
