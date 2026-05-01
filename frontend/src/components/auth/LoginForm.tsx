import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { GoogleSignInButton, OrWithEmailDivider } from "./GoogleSignInButton";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function LoginForm() {
  const { signIn, error, clearError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? "/dashboard";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [forgotMessage, setForgotMessage] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    clearError();
    setLocalError(null);

    if (!EMAIL_RE.test(email)) {
      setLocalError("That doesn't look like a valid email address.");
      return;
    }
    if (!password) {
      setLocalError("Please enter your password.");
      return;
    }

    setBusy(true);
    try {
      await signIn(email, password);
      navigate(redirectTo, { replace: true });
    } catch {
      // friendly mapping handled in AuthContext
    } finally {
      setBusy(false);
    }
  }

  const shownError = localError ?? error ?? null;

  return (
    <div className="w-full max-w-[360px]">
      <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
        Welcome back
      </div>
      <h2 className="mt-2 text-[24px] font-medium tracking-[-0.01em] text-primary">
        Sign in
      </h2>
      <p className="mt-2 text-[13px] text-secondary">
        No account?{" "}
        <Link to="/signup" className="text-iris hover:text-iris-deep">
          Create one
        </Link>
      </p>

      <div className="mt-7">
        <GoogleSignInButton />
        <OrWithEmailDivider />
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="email"
            className="mb-2 block text-[11px] uppercase tracking-[0.08em] text-tertiary"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
            className="w-full rounded-md border-[0.5px] border-border-subtle bg-card px-3.5 py-2.5 text-[13px] text-primary placeholder:text-muted focus:border-iris focus:outline-none"
          />
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <label
              htmlFor="password"
              className="text-[11px] uppercase tracking-[0.08em] text-tertiary"
            >
              Password
            </label>
            <button
              type="button"
              onClick={() =>
                setForgotMessage("Password reset is coming soon.")
              }
              className="text-[11px] text-iris hover:text-iris-deep"
            >
              Forgot password?
            </button>
          </div>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full rounded-md border-[0.5px] border-border-subtle bg-card px-3.5 py-2.5 text-[13px] text-primary placeholder:text-muted focus:border-iris focus:outline-none"
          />
        </div>

        {forgotMessage && (
          <div className="rounded-md border-[0.5px] border-iris/40 bg-iris/10 px-3 py-2 text-[12px] text-iris">
            {forgotMessage}
          </div>
        )}

        {shownError && (
          <div className="rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-3 py-2 text-[12px] text-critical">
            {shownError}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-iris px-4 py-3 text-[13px] font-medium text-page transition-colors hover:bg-iris-deep disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
