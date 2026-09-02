import Image from "next/image";
import Link from "next/link";

import { LoginForm } from "@/components/auth/login-form";
import { BrandMark } from "@/components/ui/brand-mark";

export default function LoginPage() {
  return (
    <main className="access-page">
      <section className="access-frame" aria-labelledby="access-title">
        <div className="access-visual">
          <Image
            alt="Leather workshop team preparing evidence"
            fill
            priority
            sizes="100vw"
            src="/images/leather-audit-workshop.jpg"
          />
        </div>
        <div className="access-layout">
          <div className="access-panel">
            <div className="access-brand">
              <BrandMark small />
              <div>
                <strong>AuditReady AI</strong>
                <span>Compliance workspace</span>
              </div>
            </div>
            <div className="access-heading">
              <p className="eyebrow">Secure workspace</p>
              <h1 id="access-title">Welcome back</h1>
              <p>Use your existing account or create a protected workspace.</p>
            </div>
            <LoginForm />
            <Link aria-label="Back to the AuditReady AI overview" className="access-back" href="/">
              &larr; Back to overview
            </Link>
          </div>
        </div>
      </section>
    </main>
  );
}
