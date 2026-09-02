import Link from "next/link";

export default function Forbidden() {
  return (
    <div className="centered-shell">
      <div className="auth-card">
        <h2>Admin access required.</h2>
        <p>This screen is reserved for knowledge-base and audit-log administration.</p>
        <Link className="button button-primary" href="/chat">
          Back to workspace
        </Link>
      </div>
    </div>
  );
}
