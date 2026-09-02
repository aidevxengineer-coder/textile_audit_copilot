"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <div className="centered-shell">
          <div className="auth-card">
            <h2>The application hit a fatal error.</h2>
            <p>{error.message}</p>
            <button className="button button-primary" onClick={() => reset()} type="button">
              Reload layout
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
