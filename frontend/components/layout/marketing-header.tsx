import Link from "next/link";

import { BrandMark } from "@/components/ui/brand-mark";

export function MarketingHeader() {
  return (
    <header className="mkt-nav">
      <div className="mkt-nav-inner">
        <Link href="/" className="mkt-logo">
          <BrandMark small />
          <span>AuditReady <b>AI</b></span>
        </Link>
        <nav className="mkt-nav-links">
          <a href="#product">Product</a>
          <a href="#how-it-works">How it works</a>
          <a href="#features">Features</a>
          <a href="#ask-auditready">Help</a>
        </nav>
        <div className="mkt-nav-right">
          <Link href="/login" className="mkt-login-link">
            Sign in
          </Link>
          <Link href="/login" className="button button-ghost mkt-create-link">
            Create account
          </Link>
        </div>
      </div>
    </header>
  );
}
