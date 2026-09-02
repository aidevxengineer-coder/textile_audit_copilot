import Image from "next/image";

import { MfaFlow } from "@/components/auth/mfa-flow";
import { BrandMark } from "@/components/ui/brand-mark";

export default function MfaPage() {
  return (
    <main className="access-page">
      <section className="access-frame access-frame-mfa">
        <div className="access-visual">
          <Image alt="Leather workshop team preparing evidence" fill priority sizes="100vw" src="/images/leather-audit-workshop.jpg" />
          <div className="access-visual-copy"><p>Secure access for every review.</p><span>Role-aware protection and traceable evidence</span></div>
        </div>
        <div className="access-panel access-panel-mfa">
          <div className="access-brand"><BrandMark small /><div><strong>AuditReady AI</strong><span>Secure verification</span></div></div>
          <MfaFlow />
        </div>
      </section>
    </main>
  );
}
