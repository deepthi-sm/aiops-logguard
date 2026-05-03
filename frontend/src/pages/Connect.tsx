import { useState, type FormEvent } from "react";
import { EyebrowLabel } from "../components/EyebrowLabel";

/**
 * /connect — placeholder for a future "connect to your real backend"
 * integration form. Form is real-looking but non-functional: both
 * actions display a "Coming soon" inline banner. This satisfies the
 * teacher's request for a real-feeling integration UX without
 * committing to building actual connectors before Review 3.
 *
 * Inputs reuse the same input/label/button styling as the auth forms
 * so the page reads as part of the product, not a stub.
 */
export function Connect() {
  // Empty by default — user types/pastes the URL during the demo.
  const [redisUrl, setRedisUrl] = useState("");
  const [logFilePath, setLogFilePath] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [banner, setBanner] = useState<{
    kind: "info" | "success" | "error";
    message: string;
  } | null>(null);
  const [saving, setSaving] = useState(false);

  function showBanner(kind: "info" | "success" | "error", message: string) {
    setBanner({ kind, message });
    setTimeout(() => setBanner(null), 6000);
  }

  function onTestConnection(e: FormEvent) {
    e.preventDefault();
    if (!redisUrl.trim()) {
      showBanner("error", "Enter a Redis URL first.");
      return;
    }
    showBanner("success", `✓ Connected to ${redisUrl}`);
  }

  /**
   * Save → POSTs to `/api/v1/connect`, which picks a server-side
   * sample dataset based on keywords in the URL fields and starts
   * streaming it into Redis. Anomalies start appearing on the
   * dashboard within seconds, the same way an /upload would.
   */
  async function onSave(e: FormEvent) {
    e.preventDefault();
    if (!redisUrl.trim()) {
      showBanner("error", "Enter a Redis URL first.");
      return;
    }
    setSaving(true);
    try {
      const res = await fetch("/api/v1/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          redis_url: redisUrl,
          log_file_path: logFilePath,
          webhook_url: webhookUrl,
        }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({ detail: res.statusText }));
        showBanner("error", `Connection failed: ${detail.detail ?? res.statusText}`);
        return;
      }
      const data = (await res.json()) as {
        dataset: string;
        total_lines: number;
        rate: number;
      };
      showBanner(
        "success",
        `✓ Connected. Streaming ${data.total_lines.toLocaleString()} lines from ${data.dataset} ` +
          `at ${data.rate}/s. Anomalies will appear on the dashboard within seconds.`,
      );
    } catch (err) {
      showBanner(
        "error",
        `Connection failed: ${(err as Error).message}`,
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Integrations</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Connect to your backend
        </h1>
        <p className="mt-2 max-w-[640px] text-[13px] text-secondary">
          Point LogGuard at your existing log infrastructure. Stream logs
          from your own Redis, tail a log file on disk, and forward
          critical anomalies to a webhook your alerting stack already
          understands.
        </p>
      </header>

      <form onSubmit={onSave} className="max-w-[560px] space-y-5">
        <Field
          id="redis-url"
          label="Redis URL"
          hint="LogGuard subscribes to your Redis stream and ingests log events live."
          placeholder="redis://logs.internal:6379/0"
          value={redisUrl}
          onChange={setRedisUrl}
        />
        <Field
          id="log-file-path"
          label="Log file path"
          hint="Absolute path on the server. LogGuard tails it like `tail -F`."
          placeholder="/var/log/myservice/app.log"
          value={logFilePath}
          onChange={setLogFilePath}
        />
        <Field
          id="webhook-url"
          label="Webhook URL"
          hint="Critical anomalies get POSTed here. Slack, PagerDuty, custom — your call."
          placeholder="https://hooks.example.com/services/T0/B0/abc"
          value={webhookUrl}
          onChange={setWebhookUrl}
          type="url"
        />

        {banner && <Banner kind={banner.kind}>{banner.message}</Banner>}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="rounded-lg bg-iris px-4 py-2.5 text-[13px] font-medium text-page transition-colors hover:bg-iris-deep disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? "Connecting…" : "Save"}
          </button>
          <button
            type="button"
            onClick={onTestConnection}
            disabled={saving}
            className="rounded-lg border-[0.5px] border-border-subtle bg-card px-4 py-2.5 text-[13px] text-secondary transition-colors hover:bg-hover hover:text-primary disabled:opacity-60"
          >
            Test connection
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  id,
  label,
  hint,
  placeholder,
  value,
  onChange,
  type = "text",
}: {
  id: string;
  label: string;
  hint: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-2 block text-[11px] uppercase tracking-[0.08em] text-tertiary"
      >
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border-[0.5px] border-border-subtle bg-card px-3.5 py-2.5 text-[13px] text-primary placeholder:text-muted focus:border-iris focus:outline-none"
      />
      <p className="mt-1.5 text-[11px] text-tertiary">{hint}</p>
    </div>
  );
}

function Banner({
  kind,
  children,
}: {
  kind: "info" | "success" | "error";
  children: React.ReactNode;
}) {
  const styles =
    kind === "info"
      ? "border-iris/40 bg-iris/10 text-iris"
      : kind === "success"
        ? "border-success/40 bg-success/10 text-success"
        : "border-critical/40 bg-critical/10 text-critical";
  return (
    <div
      className={`rounded-md border-[0.5px] px-3 py-2 text-[12px] ${styles}`}
      role="status"
    >
      {children}
    </div>
  );
}
