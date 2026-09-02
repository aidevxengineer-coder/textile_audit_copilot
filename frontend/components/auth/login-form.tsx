"use client";

import { useRouter } from "next/navigation";
import { startTransition, useState } from "react";

import { loginUser, registerUser } from "@/lib/browser-api";
import { Icon } from "@/components/ui/icon";

export function LoginForm() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  function selectMode(nextMode: "login" | "register") {
    setMode(nextMode);
    setError(null);
    setShowPassword(false);
  }

  async function handleSubmit(formData: FormData) {
    setBusy(true);
    setError(null);
    try {
      const payload = {
        email: String(formData.get("email") || ""),
        password: String(formData.get("password") || ""),
      };

      if (mode === "register") {
        await registerUser({
          ...payload,
          full_name: String(formData.get("full_name") || ""),
        });
      }

      const result = await loginUser(payload);
      const destination = result.user.role === "admin" ? "/admin" : "/chat";
      startTransition(() => {
        if (result.mfa_required) {
          router.push(`/mfa?mode=challenge&next=${encodeURIComponent(destination)}`);
          return;
        }
        if (result.mfa_enrollment_required) {
          router.push(`/mfa?mode=enroll&next=${encodeURIComponent(destination)}`);
          return;
        }
        router.push(destination);
      });
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`auth-card auth-card-${mode}`} data-mode={mode}>
      <div aria-label="Choose an account action" className="auth-tabs" role="tablist">
        <button
          aria-selected={mode === "login"}
          className={mode === "login" ? "active" : ""}
          role="tab"
          type="button"
          onClick={() => selectMode("login")}
        >
          Sign In
        </button>
        <button
          aria-selected={mode === "register"}
          className={mode === "register" ? "active" : ""}
          role="tab"
          type="button"
          onClick={() => selectMode("register")}
        >
          Create Account
        </button>
      </div>
      <div className="auth-mode-copy">
        <strong>{mode === "login" ? "Sign in to your account" : "Create your private workspace"}</strong>
        <span>{mode === "login" ? "Administrators sign in here too. MFA starts automatically when required." : "New accounts are created as factory-user workspaces with private projects and reviews."}</span>
      </div>
      <form
        action={(formData) => {
          void handleSubmit(formData);
        }}
        className="auth-form"
      >
        {mode === "register" ? (
          <label>
            Full name
            <input className="input" name="full_name" placeholder="Ayesha Khan" required />
          </label>
        ) : null}
        <label>
          Work email
          <input autoCapitalize="none" autoComplete="email" className="input" name="email" type="email" placeholder="compliance@factory.pk" required />
        </label>
        <label>
          Password
          <span className="password-field"><input className="input" name="password" type={showPassword ? "text" : "password"} placeholder={mode === "login" ? "Your password" : "Minimum 12 characters"} minLength={mode === "login" ? 8 : 12} autoComplete={mode === "login" ? "current-password" : "new-password"} required /><button aria-label={showPassword ? "Hide password" : "Show password"} className="password-toggle" onClick={() => setShowPassword((value) => !value)} type="button"><Icon name={showPassword ? "eyeOff" : "eye"} /></button></span>
        </label>
        {error ? <p aria-live="polite" className="form-error" role="alert">{error}</p> : null}
        <button className="button button-primary" disabled={busy} type="submit">
          {busy ? (mode === "login" ? "Signing in…" : "Creating account…") : mode === "login" ? "Sign in securely" : "Create account"}
        </button>
      </form>
      <p className="form-footnote access-privacy">Protected by secure session cookies and role-based access.</p>
      <p className="auth-account-switch">
        {mode === "login" ? "New to AuditReady AI?" : "Already have an account?"}{" "}
        <button onClick={() => selectMode(mode === "login" ? "register" : "login")} type="button">
          {mode === "login" ? "Create an account" : "Sign in instead"}
        </button>
      </p>
    </div>
  );
}
