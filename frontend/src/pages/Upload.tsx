import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, UPLOAD_MAX_BYTES } from "../api/client";
import { useUpload, useUploadStatus } from "../api/queries";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";

// localStorage key for the in-progress upload's job id. Survives full
// route navigation (sidebar clicks → URL changes → /upload?job=... is
// lost). When the Upload page mounts without a `?job=` query param, we
// check this key and rehydrate from it — so the user can leave the
// upload running, browse around, come back, and still see the
// progress card.
const ACTIVE_JOB_KEY = "logguard_active_upload";

/**
 * /upload — push a user-supplied .log/.txt file into the live ingestion
 * pipeline.
 *
 *   1. Pick a file (`.log` or `.txt`, <= 50 MB)
 *   2. Click Upload
 *   3. Backend returns a job_id; we poll `/upload/{id}/status` every 2s
 *   4. When the job hits `completed`, redirect to `/anomalies?origin=user-upload`
 *      so the user sees the anomalies derived from their file
 *
 * The hidden `?rate=N` URL param (default 50, max 1000) accelerates
 * ingestion for demos. e.g. `/upload?rate=500` tells the backend to
 * push 500 lines/sec instead of the default 50.
 */
export function Upload() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  // Hidden demo-friendly rate override from the URL. Capped at 1000 to
  // match the backend; falls back to undefined (server uses its own
  // default of 50).
  const rateOverride = useMemo(() => {
    const raw = searchParams.get("rate");
    if (!raw) return undefined;
    const n = Number.parseInt(raw, 10);
    if (Number.isNaN(n) || n < 1 || n > 1000) return undefined;
    return n;
  }, [searchParams]);

  // jobId is persisted in BOTH the URL (?job=<id>) and localStorage so
  // that the upload progress card survives every kind of navigation:
  //
  //   - URL only:  refreshing the page or sharing the URL works
  //   - localStorage only: clicking a sidebar link (which replaces the
  //     URL entirely) and then coming back to /upload still finds the
  //     in-progress job
  //
  // On mount, if URL has no ?job= but localStorage does, we hydrate
  // back into the URL so polling resumes immediately.
  const urlJob = searchParams.get("job");
  const jobId = urlJob;

  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useUpload();
  const status = useUploadStatus(jobId);

  function setJobId(id: string | null) {
    const next = new URLSearchParams(searchParams);
    if (id) {
      next.set("job", id);
      try { localStorage.setItem(ACTIVE_JOB_KEY, id); } catch { /* storage disabled */ }
    } else {
      next.delete("job");
      try { localStorage.removeItem(ACTIVE_JOB_KEY); } catch { /* noop */ }
    }
    setSearchParams(next, { replace: true });
  }

  // Rehydrate from localStorage on mount when URL has no ?job=. We use
  // a layout-effect-style sync inside useEffect with empty deps so this
  // fires exactly once per mount.
  useEffect(() => {
    if (urlJob) return;
    let stored: string | null = null;
    try { stored = localStorage.getItem(ACTIVE_JOB_KEY); } catch { /* noop */ }
    if (stored) {
      const next = new URLSearchParams(searchParams);
      next.set("job", stored);
      setSearchParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Track whether the user has actively watched this upload (i.e. seen
  // a non-terminal status during the current mount). Distinguishes
  // "active watch about to finish" → redirect, from "returned to a job
  // that finished while we were elsewhere" → silently clear, render the
  // file picker. Without this distinction we'd flash a stale 100% bar
  // and re-trigger the auto-redirect every time the user revisits.
  const sawRunningRef = useRef(false);

  useEffect(() => {
    const s = status.data?.status;
    if (!s) return;

    if (s === "queued" || s === "running") {
      sawRunningRef.current = true;
      return;
    }

    // Terminal — clear localStorage so this job can't resurrect later.
    try { localStorage.removeItem(ACTIVE_JOB_KEY); } catch { /* noop */ }

    if (sawRunningRef.current && s === "completed") {
      // Active watcher: 1.2s "Done!" beat, then redirect.
      const t = setTimeout(() => {
        navigate("/anomalies?origin=user-upload");
      }, 1200);
      return () => clearTimeout(t);
    }

    // Came back to a job that's already terminal. Drop ?job= from the
    // URL so the page renders the picker instead of a stale progress
    // card. Don't redirect — the user navigated here deliberately.
    setJobId(null);
  }, [status.data?.status, navigate]);

  function onFileChange(e: ChangeEvent<HTMLInputElement>) {
    setValidationError(null);
    const f = e.target.files?.[0] ?? null;
    if (!f) {
      setFile(null);
      return;
    }
    const lower = f.name.toLowerCase();
    if (!lower.endsWith(".log") && !lower.endsWith(".txt")) {
      setValidationError("Only .log and .txt files are accepted.");
      setFile(null);
      return;
    }
    if (f.size > UPLOAD_MAX_BYTES) {
      setValidationError(
        `File is too large (${(f.size / (1024 * 1024)).toFixed(1)} MB). ` +
          `Maximum is ${UPLOAD_MAX_BYTES / (1024 * 1024)} MB per upload.`,
      );
      setFile(null);
      return;
    }
    setFile(f);
  }

  function onUpload() {
    if (!file) return;
    upload.mutate(
      { file, rate: rateOverride },
      {
        onSuccess: (resp) => {
          setJobId(resp.job_id);
        },
      },
    );
  }

  function reset() {
    setFile(null);
    setJobId(null);
    setValidationError(null);
    upload.reset();
    if (inputRef.current) inputRef.current.value = "";
  }

  // Surface a server error (e.g. 413 over Content-Length) under the picker.
  const serverError =
    upload.error instanceof ApiError
      ? `${upload.error.status}: ${upload.error.detail}`
      : upload.error?.message ?? null;

  const inProgress =
    status.data?.status === "queued" || status.data?.status === "running";
  const completed = status.data?.status === "completed";
  const failed = status.data?.status === "failed";

  return (
    <div className="pb-12">
      <header className="mb-7 border-b-[0.5px] border-border-subtle pb-5">
        <EyebrowLabel>Ingest</EyebrowLabel>
        <h1 className="text-[22px] font-medium leading-none tracking-[-0.01em] text-primary">
          Upload logs
        </h1>
        <p className="mt-2 max-w-[640px] text-[13px] text-secondary">
          Push a .log or .txt file into the live ingestion pipeline.
          Anomalies derived from your file appear in the dashboard,
          filtered to just this upload.
        </p>
      </header>

      {/* Pre-upload state — file picker */}
      {!jobId && (
        <div className="max-w-[560px]">
          <label
            htmlFor="logfile"
            className="block cursor-pointer rounded-lg border-[0.5px] border-dashed border-border-default bg-card px-6 py-10 text-center transition-colors hover:border-iris/50 hover:bg-hover/40"
          >
            <input
              id="logfile"
              ref={inputRef}
              type="file"
              accept=".log,.txt"
              onChange={onFileChange}
              className="sr-only"
              disabled={upload.isPending}
            />
            <div className="text-[13px] text-primary">
              {file ? file.name : "Click to choose a file"}
            </div>
            <div className="mt-1 text-[11px] text-tertiary">
              {file
                ? `${(file.size / (1024 * 1024)).toFixed(2)} MB`
                : ".log or .txt, up to 50 MB"}
            </div>
          </label>

          {validationError && (
            <ErrorMessage>{validationError}</ErrorMessage>
          )}
          {serverError && <ErrorMessage>{serverError}</ErrorMessage>}

          <div className="mt-5 flex items-center gap-3">
            <button
              type="button"
              onClick={onUpload}
              disabled={!file || upload.isPending}
              className="rounded-lg bg-iris px-4 py-2.5 text-[13px] font-medium text-page transition-colors hover:bg-iris-deep disabled:cursor-not-allowed disabled:opacity-60"
            >
              {upload.isPending ? "Uploading…" : "Upload"}
            </button>
            {file && (
              <button
                type="button"
                onClick={reset}
                disabled={upload.isPending}
                className="rounded-lg border-[0.5px] border-border-subtle bg-card px-4 py-2.5 text-[13px] text-secondary transition-colors hover:bg-hover hover:text-primary disabled:opacity-60"
              >
                Clear
              </button>
            )}
            {rateOverride && (
              <div className="ml-auto rounded-md border-[0.5px] border-iris/40 bg-iris/10 px-2.5 py-1 font-mono text-[11px] text-iris">
                rate={rateOverride}/s
              </div>
            )}
          </div>
        </div>
      )}

      {/* Post-upload state — progress */}
      {jobId && status.data && (
        <div className="max-w-[560px]">
          <ProgressCard
            status={status.data.status}
            linesStreamed={status.data.lines_streamed}
            totalLines={status.data.total_lines}
            etaSeconds={status.data.eta_seconds}
            error={status.data.error}
          />
          {(completed || failed) && (
            <div className="mt-5 flex items-center gap-3">
              <button
                type="button"
                onClick={reset}
                className="rounded-lg border-[0.5px] border-border-subtle bg-card px-4 py-2.5 text-[13px] text-secondary transition-colors hover:bg-hover hover:text-primary"
              >
                Upload another file
              </button>
              {completed && (
                <button
                  type="button"
                  onClick={() => navigate("/anomalies?origin=user-upload")}
                  className="rounded-lg bg-iris px-4 py-2.5 text-[13px] font-medium text-page transition-colors hover:bg-iris-deep"
                >
                  View anomalies →
                </button>
              )}
            </div>
          )}
          {inProgress && (
            <p className="mt-4 text-[12px] text-tertiary">
              You can leave this page open. We'll redirect you to the
              filtered Anomalies view as soon as ingestion completes.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ProgressCard({
  status,
  linesStreamed,
  totalLines,
  etaSeconds,
  error,
}: {
  status: "queued" | "running" | "completed" | "failed";
  linesStreamed: number;
  totalLines: number;
  etaSeconds: number | null;
  error: string | null;
}) {
  const pct =
    totalLines > 0 ? Math.min(100, (linesStreamed / totalLines) * 100) : 0;
  const tone =
    status === "failed"
      ? "critical"
      : status === "completed"
        ? "success"
        : "iris";
  return (
    <div className="rounded-lg border-[0.5px] border-border-subtle bg-card p-5">
      <div className="flex items-baseline justify-between">
        <div className="text-[11px] uppercase tracking-[0.08em] text-tertiary">
          Status
        </div>
        <div
          className={cn(
            "font-mono text-[12px]",
            tone === "critical" && "text-critical",
            tone === "success" && "text-success",
            tone === "iris" && "text-iris",
          )}
        >
          {status}
        </div>
      </div>
      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-hover">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-300",
            tone === "critical" && "bg-critical",
            tone === "success" && "bg-success",
            tone === "iris" && "bg-iris",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-3 flex items-center justify-between text-[12px]">
        <div className="font-mono text-secondary">
          {linesStreamed.toLocaleString()} / {totalLines.toLocaleString()} lines
        </div>
        <div className="font-mono text-tertiary">
          {status === "completed"
            ? "Done"
            : status === "failed"
              ? "Failed"
              : etaSeconds !== null
                ? `~${formatEta(etaSeconds)} remaining`
                : "Queued…"}
        </div>
      </div>
      {error && (
        <div className="mt-4 rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-3 py-2 text-[12px] text-critical">
          {error}
        </div>
      )}
    </div>
  );
}

function ErrorMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-4 rounded-md border-[0.5px] border-critical/40 bg-critical/10 px-3 py-2 text-[12px] text-critical">
      {children}
    </div>
  );
}

function formatEta(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s === 0 ? `${m}m` : `${m}m ${s}s`;
}
