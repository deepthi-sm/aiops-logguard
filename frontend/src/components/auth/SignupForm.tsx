import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { GoogleSignInButton, OrWithEmailDivider } from "./GoogleSignInButton";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function SignupForm() {
  const { signUp, error, clearError } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  function validate(): string | null {
    if (!name.trim()) return "Please enter your name.";
    if (!EMAIL_RE.test(email)) return "That doesn't look like a valid email address.";
    if (password.length < 8) return "Password must be at least 8 characters.";
    return null;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    clearError();
    setLocalError(null);
    const v = validate();
    if (v) {
      setLocalError(v);
      return;
    }
    setBusy(true);
    try {
      await signUp(email, password, name.trim());
      navigate("/dashboard", { replace: true });
    } catch {
      // mapped to friendly message in AuthContext; rendered below
    } finally {
      setBusy(false);
    }
  }

  const shownError = localError ?? error ?? null;

  return (
    <div className="w-full max-w-[360px]">
      <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
        Get started
      </div>
      <h2 className="mt-2 text-[24px] font-medium tracking-[-0.01em] text-primary">
        Create your account
      </h2>
      <p className="mt-2 text-[13px] text-secondary">
        Already have one?{" "}
        <Link to="/login" className="text-iris hover:text-iris-deep">
          Sign in
        </Link>
      </p>

      <div className="mt-7">
        <GoogleSignInButton />
        <OrWithEmailDivider />
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label="Full name"
          htmlFor="name"
          value={name}
          onChange={setName}
          placeholder="Deepthi"
          autoComplete="name"
        />
        <Field
          label="Email"
          htmlFor="email"
          value={email}
          onChange={setEmail}
          placeholder="you@company.com"
          type="email"
          autoComplete="email"
        />
        <div>
          <Field
            label="Password"
            htmlFor="password"
            value={password}
            onChange={setPassword}
            placeholder="••••••••"
            type="password"
            autoComplete="new-password"
          />
          <div className="mt-1.5 text-[11px] text-tertiary">
            Minimum 8 characters
          </div>
        </div>

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
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p className="mt-5 text-center text-[11px] text-tertiary">
        By creating an account, you agree to the{" "}
        <a href="#" className="text-iris hover:text-iris-deep">
          terms of service
        </a>{" "}
        and{" "}
        <a href="#" className="text-iris hover:text-iris-deep">
          privacy policy
        </a>
        .
      </p>
    </div>
  );
}

// -- input helper ---------------------------------------------------------

function Field({
  label,
  htmlFor,
  value,
  onChange,
  placeholder,
  type = "text",
  autoComplete,
}: {
  label: string;
  htmlFor: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  type?: string;
  autoComplete?: string;
}) {
  return (
    <div>
      <label
        htmlFor={htmlFor}
        className="mb-2 block text-[11px] uppercase tracking-[0.08em] text-tertiary"
      >
        {label}
      </label>
      <input
        id={htmlFor}
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border-[0.5px] border-border-subtle bg-card px-3.5 py-2.5 text-[13px] text-primary placeholder:text-muted focus:border-iris focus:outline-none"
      />
    </div>
  );
}
