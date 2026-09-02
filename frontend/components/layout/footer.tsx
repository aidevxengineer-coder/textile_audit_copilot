import Link from "next/link";

import { BrandMark } from "@/components/ui/brand-mark";

export function Footer() {
  return (
    <footer className="mkt-footer">
      <div className="wrap mkt-footer-grid">
        <div className="mkt-footer-brand"><div className="mkt-logo"><BrandMark small />AuditReady AI</div><p>Pre audit intelligence for Pakistani textile and leather exporters, factories, and sourcing teams.</p></div>
        <div><h4>Product</h4><a href="#product">Overview</a><a href="#review-evidence">Evidence review</a><a href="#how-it-works">How it works</a></div>
        <div><h4>Resources</h4><a href="#features">Features</a><a href="#ask-auditready">Ask AuditReady</a><Link href="/login">Security and account access</Link></div>
        <div><h4>Contact</h4><a href="mailto:team@auditready.local">team@auditready.local</a><span>Karachi · Lahore · Faisalabad · Sialkot</span><Link href="/login">Sign in or create an account</Link></div>
      </div>
    </footer>
  );
}
