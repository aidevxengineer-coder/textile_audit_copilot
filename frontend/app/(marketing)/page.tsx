import Image from "next/image";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Footer } from "@/components/layout/footer";
import { MarketingHeader } from "@/components/layout/marketing-header";
import { MarketingMotion } from "@/components/marketing/marketing-motion";
import { ProductGuide } from "@/components/marketing/product-guide";
import { getOptionalServerUser } from "@/lib/server-api";
import "./marketing.css";
import "./refinement.css";

const useCaseCards = [
  ["Made for teams", "One workspace for factories, consultants, and sourcing teams."],
  ["Review evidence", "Turn uploads into likely gaps, clauses, and next steps."],
  ["Keep it grounded", "Use project files and trusted knowledge with citations."],
  ["Share progress", "Create reports and keep every review traceable."],
];

const tools = [
  ["Add your evidence", "Upload photos, policies, records, and certificates in one project."],
  ["Ask in plain language", "Ask what needs attention and follow up on any finding."],
  ["See the supporting proof", "Open the source documents behind each recommendation."],
  ["Share a clear report", "Give factory and sourcing teams the same practical next steps."],
];

export default async function MarketingPage() {
  const user = await getOptionalServerUser();
  if (user) redirect("/chat");

  return (
    <div className="marketing-shell">
      <MarketingMotion />
      <MarketingHeader />
      <main>
        <section className="mkt-hero">
          <div className="hero-background-photo" aria-hidden="true">
            <Image alt="" fill priority sizes="100vw" src="/images/leather-audit-workshop.jpg" />
          </div>
          <div className="wrap hero-content">
            <span className="eyebrow">AuditReady AI · textile and leather compliance</span>
            <h1>Stop audit surprises<br /><em>before they cost you.</em></h1>
            <p className="sub">Buyer audits reveal costly gaps hidden across supplier photos, policies, and records. AuditReady AI turns that scattered evidence into a traceable, prioritized readiness plan before the audit begins.</p>
            <div className="hero-actions"><Link className="button hero-account-button" href="/login">Create account</Link></div>
          </div>
        </section>

        <section className="mkt-scope" id="product" data-reveal>
          <div className="wrap">
            <div className="mkt-story-ribbon">
              <div><Image alt="Textile weaving floor" fill sizes="(max-width:800px) 100vw, 30vw" src="/images/textile-weaving-floor.jpeg" /></div>
              <div><Image alt="Leather craft worker" fill sizes="(max-width:800px) 100vw, 36vw" src="/images/leather-artisan.jpeg" /></div>
              <div><Image alt="Leather workshop team" fill sizes="(max-width:800px) 100vw, 30vw" src="/images/leather-workshop-team.jpeg" /></div>
            </div>
            <div className="mkt-scope-head"><span className="eyebrow">What this app actually does</span><h2>One clear place to prepare, review, and act.</h2></div>
            <div className="mkt-scope-grid">
              {useCaseCards.map(([title, body], index) => <article className="mkt-scope-card" key={title}><span className="scope-pin" aria-hidden="true" /><span className="scope-number">0{index + 1}</span><p className="mkt-scope-kicker">{title}</p><p>{body}</p></article>)}
            </div>
          </div>
        </section>

        <section className="mkt-feature-story" id="review-evidence" data-reveal>
          <div className="wrap mkt-feature-story-inner">
          <div className="mkt-feature-row">
            <div className="mkt-feature-copy">
              <span className="eyebrow">One workspace for every review</span>
              <h2>Bring factory evidence into one clear review.</h2>
              <p>Upload a photo, policy, or record once. AuditReady brings the relevant evidence together, highlights likely gaps, and gives your team a clear next step.</p>
              <p>Instead of chasing files across chats and spreadsheets, everyone sees the same review. Each finding links to the evidence behind it.</p>
            </div>
            <div className="mkt-feature-art">
              <div className="mkt-art-photo"><Image alt="Factory compliance inspection" fill sizes="(max-width:900px) 100vw,50vw" src="/images/audit-inspection-team.jpeg" /></div>
              {[["Emergency exit needs clearing", "Major"], ["Overtime record needs checking", "Minor"], ["Fire extinguisher check is current", "Compliant"]].map(([label, status]) => <div className="mkt-art-panel" key={label}><strong>{label}</strong><span className={`tag ${status === "Major" ? "major" : ""}`}>{status}</span></div>)}
            </div>
          </div>

          <div className="mkt-feature-row reverse" id="how-it-works">
            <div className="mkt-feature-art mkt-trace-art">
              <div className="mkt-art-panel"><strong>Your evidence journey</strong><span className="tag">Live trace</span></div>
              <div className="mkt-pipeline">
                <span><small>01</small><b>Understand</b><em>Your question</em></span><i>→</i>
                <span><small>02</small><b>Find proof</b><em>Relevant files</em></span><i>→</i>
                <span><small>03</small><b>Check it</b><em>Against standards</em></span><i>→</i>
                <span><small>04</small><b>Guide you</b><em>Clear next step</em></span>
              </div>
              <p className="mkt-art-quote">Open any step to see the documents and checks behind the answer.</p>
            </div>
            <div className="mkt-feature-copy"><span className="eyebrow">Nothing hidden</span><h2>Know exactly why a finding was raised.</h2><p>Every answer shows how your question was understood, which evidence was used, and what was checked before a recommendation was made.</p></div>
          </div>
          </div>
        </section>

        <section className="mkt-tools" id="features" data-reveal>
          <div className="wrap">
            <div className="mkt-tools-head"><span className="eyebrow">Core features</span><h2>Tools that turn evidence into action.</h2><p>Every feature is built to make audit preparation clearer for factory and sourcing teams.</p></div>
            <div className="mkt-feature-grid">{tools.map(([title, body], index) => <article className="mkt-feature-tile" key={title}><span className="feature-number">0{index + 1}</span><div><h3>{title}</h3><p>{body}</p></div></article>)}</div>
          </div>
        </section>

        <section className="mkt-ask-section" id="ask-auditready" data-reveal><div className="wrap"><div className="mkt-ask-head"><span className="eyebrow">Ask AuditReady AI</span><h2>Questions about the product, answered in one place.</h2><p>Ask about accounts, security, evidence uploads, audit preparation, web search, and integrations.</p></div><ProductGuide /></div></section>

      </main>
      <Footer />
    </div>
  );
}
