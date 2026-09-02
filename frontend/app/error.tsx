"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="centered-shell">
      <div className="auth-card">
        <h2>Something went wrong inside the workspace.</h2>
        <p>{error.message}</p>
        <button className="button button-primary" onClick={() => reset()} type="button">
          Try again
        </button>
      </div>
    </div>
  );
}
