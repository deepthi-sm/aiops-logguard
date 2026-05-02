import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, UPLOAD_MAX_BYTES } from "../api/client";
import { useUpload, useUploadStatus } from "../api/queries";
import { EyebrowLabel } from "../components/EyebrowLabel";
import { cn } from "../lib/cn";

/**
 * /upload — push a user-supplied .log/.txt file into the live ingestion
 * pipeline.
 *
 *   1. Pick a file (`.log` or `.txt`, <= 50 MB)
 *   2. Click Upload
 *   3. Backend returns a job_id; we poll `/upload/{id}/status` every 2s
 *   4. When the job hits `completed`, redirect to `/anomalies?source=user-upload`
 *      so the user sees the anomalies derived from their file
 *
 * The hidden `?rate=N` URL param (default 50, max 1000) accelerates
 * ingestion for demos. e.g. `/upload?rate=500` tells the backend to
 * push 500 lines/sec instead of the default 50.
 */
export function Upload() {
  const [searchParams] = useSearchParams();
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

  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useUpload();
  const status = useUploadStatus(jobId);

  // When the polled status hits `completed`, redirect after a short
  // delay so the user can read the "Done!" line. `failed` stays on this
  // page with the error visible.
  useEffect(() => {
    if (status.data?.status === "completed") {
      const t = setTimeout(() => {
        navigate("/anomalies?source=user-upload");
      }, 1200);
      return () => clearTimeout(t);
    }
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
          Push a `.log` or `.txt` file into the live ingestion pipeline.
          Anomalies derived from your file appear in the dashboard tagged{" "}
          <code className="font-mono text-primary">source=user-upload</code>.
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
                  onClick={() => navigate("/anomalies?source=user-upload")}
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
