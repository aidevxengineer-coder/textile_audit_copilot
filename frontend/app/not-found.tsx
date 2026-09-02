import Link from "next/link";

export default function NotFound() {
  return (
    <div className="centered-shell">
      <div className="auth-card">
        <h2>We could not find that route or report.</h2>
        <p>The page may have moved, or the session may not belong to your account.</p>
        <Link className="button button-primary" href="/chat">
          Return to chat
        </Link>
      </div>
    </div>
  );
}
