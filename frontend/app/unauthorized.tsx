import Link from "next/link";

export default function Unauthorized() {
  return (
    <div className="centered-shell">
      <div className="auth-card">
        <h2>Please sign in to continue.</h2>
        <p>Your session is missing or has expired.</p>
        <Link className="button button-primary" href="/login">
          Go to login
        </Link>
      </div>
    </div>
  );
}
