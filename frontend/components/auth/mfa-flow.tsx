"use client";

import { Suspense, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useRouter, useSearchParams } from "next/navigation";

import {
  beginMfaEnrollment,
  confirmMfaEnrollment,
  getMfaChallengeToken,
  verifyMfaLogin,
} from "@/lib/browser-api";

function MfaFlowInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const mode = searchParams.get("mode") === "challenge" ? "challenge" : "enroll";
  const destination = searchParams.get("next") === "/admin" ? "/admin" : "/chat";
  const [secret, setSecret] = useState("");
  const [uri, setUri] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (mode === "enroll") {
      void beginMfaEnrollment()
        .then((result) => {
          setSecret(result.secret);
          setUri(result.provisioning_uri);
        })
        .catch((fetchError) => {
          setError(fetchError instanceof Error ? fetchError.message : "Unable to start MFA enrollment.");
        });
    }
  }, [mode]);

  async function handleCode(formData: FormData) {
    setBusy(true);
    setError(null);
    try {
      const code = String(formData.get("code") || "");
      if (mode === "challenge") {
        if (!getMfaChallengeToken()) {
          throw new Error("MFA challenge expired. Please sign in again.");
        }
        await verifyMfaLogin(code);
      } else {
        await confirmMfaEnrollment(code);
      }
      router.push(destination);
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Unable to verify code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-card auth-wide mfa-card-compact">
      <div className="access-heading"><p className="eyebrow">Two-step verification</p><h1>{mode === "challenge" ? "Enter your code" : "Set up authenticator"}</h1><p>{mode === "challenge" ? "Use the six-digit code from your authenticator app." : "Scan once, then enter the generated six-digit code."}</p></div>
      {mode === "enroll" ? (
        <div className="mfa-grid">
          <div className="qr-card">{uri ? <QRCodeSVG value={uri} size={180} bgColor="transparent" fgColor="#FFFFFF" /> : <div className="qr-skeleton" />}</div>
          <div className="mfa-copy">
            <p>Scan with Google Authenticator, 1Password, Microsoft Authenticator, or Authy.</p>
            <details className="manual-secret"><summary>Can’t scan the QR code?</summary><code>{secret || "Loading secret..."}</code></details>
          </div>
        </div>
      ) : null}
      <form
        action={(formData) => {
          void handleCode(formData);
        }}
        className="auth-form"
      >
        <label>
          Verification code
          <input autoComplete="one-time-code" className="input" name="code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} placeholder="123456" required />
        </label>
        {error ? <p className="form-error">{error}</p> : null}
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? "Verifying..." : mode === "challenge" ? "Verify and Enter" : "Finish Enrollment"}
        </button>
      </form>
    </div>
  );
}

export function MfaFlow() {
  return (
    <Suspense fallback={<div className="auth-card">Loading MFA flow...</div>}>
      <MfaFlowInner />
    </Suspense>
  );
}
