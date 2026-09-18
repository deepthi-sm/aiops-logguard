import { useState } from "react";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";
import { useTheme, type Theme } from "../hooks/useTheme";

/**
 * /settings — two-tab settings page (General / Data sources).
 *
 *   ┌────────────────────────────────────────────────────────────┐
 *   │  Preferences                                               │
 *   │  Settings                                                  │
 *   │  ───────────────────────────────────────────────────────   │
 *   │  [General]  [Data sources]                                 │
 *   │  ───────────────────────────────────────────────────────   │
 *   │  Theme:        ◉ Dark    ◯ Light                           │
 *   │  Default page: ◉ Dashboard ◯ Anomalies                     │
 *   │  …                                                         │
 *   └────────────────────────────────────────────────────────────┘
 *
 * Most fields are read-only for the demo — the team isn't persisting
 * settings yet. Theme is the one fully-wired control (delegates to
 * `useTheme`, which writes localStorage).
 *
 * The Alerting tab was removed: no PagerDuty / Slack / email
 * channels are wired in this build, so a dedicated configuration
 * tab was misleading. If outbound alerting lands later, restore the
 * tab and the AlertingTab + ChannelStatus components from git
 * history (commit prior to the audit's removal).
 */

type Tab = "general" | "data";

export function Settings() {
  const [tab, setTab] = useState<Tab>("general");

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Preferences</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Settings
        </h1>
      </header>

      {/* Tab strip */}
      <div className="mb-7 flex items-center gap-6 border-b-[0.5px] border-border-subtle">
        <TabButton active={tab === "general"} onClick={() => setTab("general")}>
          General
        </TabButton>
        <TabButton active={tab === "data"} onClick={() => setTab("data")}>
          Data sources
        </TabButton>
      </div>

      {tab === "general" && <GeneralTab />}
      {tab === "data" && <DataSourcesTab />}
    </div>
  );
}

// -- Tab button -----------------------------------------------------------

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "relative -mb-px border-b-[1.5px] px-1 pb-2.5 text-[12px] transition-colors",
        active
          ? "border-iris text-primary"
          : "border-transparent text-tertiary hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}

// -- General --------------------------------------------------------------

function GeneralTab() {
  const { theme, setTheme } = useTheme();
  const [defaultPage, setDefaultPage] = useState<"dashboard" | "anomalies">(
    "dashboard",
  );

  return (
    <div className="rounded-lg border-[0.5px] border-border-subtle bg-card">
      <SettingRow
        label="Theme"
        hint="Switches dark / light tokens on the <html> element. Persisted to localStorage."
      >
        <RadioGroup
          value={theme}
          onChange={(v) => setTheme(v as Theme)}
          options={[
            { value: "dark", label: "Dark" },
            { value: "light", label: "Light" },
          ]}
        />
      </SettingRow>
      <SettingRow
        label="Default landing page"
        hint="Where the app opens after sign-in."
      >
        <RadioGroup
          value={defaultPage}
          onChange={(v) => setDefaultPage(v as "dashboard" | "anomalies")}
          options={[
            { value: "dashboard", label: "Dashboard" },
            { value: "anomalies", label: "Anomalies" },
          ]}
        />
      </SettingRow>
      <SettingRow label="Time zone" hint="Display only; storage stays UTC.">
        <span className="font-mono text-[12px] text-secondary">
          {Intl.DateTimeFormat().resolvedOptions().timeZone}
        </span>
      </SettingRow>
      <SettingRow label="Live refresh" hint="Polling interval for the feed.">
        <span className="font-mono text-[12px] text-secondary">5s</span>
      </SettingRow>
    </div>
  );
}

// -- Data sources --------------------------------------------------------

function DataSourcesTab() {
  return (
    <div className="rounded-lg border-[0.5px] border-border-subtle bg-card">
      <SettingRow label="Postgres" hint="Anomaly + feedback persistence.">
        <span className="font-mono text-[12px] text-secondary">
          postgres:5432 / db: logguard
        </span>
      </SettingRow>
      <SettingRow label="Redis" hint="Ingest stream + pubsub.">
        <span className="font-mono text-[12px] text-secondary">redis:6379</span>
      </SettingRow>
      <SettingRow label="Ollama" hint="Local LLaMA 3 8B for RAG.">
        <span className="font-mono text-[12px] text-secondary">
          ollama:11434 · llama3:8b
        </span>
      </SettingRow>
      <SettingRow label="FAISS index" hint="Vector store of past incidents.">
        <span className="font-mono text-[12px] text-secondary">
          artifacts/faiss.index · 20 vectors
        </span>
      </SettingRow>
      <SettingRow label="Drain3 state" hint="Persisted log-template parser.">
        <span className="font-mono text-[12px] text-secondary">
          artifacts/drain3_state.bin
        </span>
      </SettingRow>
    </div>
  );
}

// -- Building blocks ----------------------------------------------------

function SettingRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-6 border-b-[0.5px] border-border-subtle px-5 py-4 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-primary">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-tertiary">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function RadioGroup<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div className="flex items-center gap-1 rounded-md border-[0.5px] border-border-subtle bg-page p-0.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded-[5px] px-3 py-1 text-[11px] transition-colors",
            value === opt.value
              ? "bg-card text-primary shadow-[0_0_0_0.5px_var(--border-subtle)]"
              : "text-tertiary hover:text-primary",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
