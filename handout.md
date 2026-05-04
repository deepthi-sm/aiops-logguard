# LogGuard — Phase 1 Audit + Phase 2 Fix Handout

> Working document tracking the May 2026 UX-and-correctness audit on
> branch `backend/results-paper-numbers`. Reflects state up to the
> Training-page redesign wireframe; updated as each phase ships.

---

## Why this exists

Five user-reported issues against the live system, audited together
in Phase 1, fixed in phased commits in Phase 2. This file records
what was wrong, what changed, and what's still pending — so anyone
picking up the branch can read one document instead of trawling git.

The **constraints** held throughout:

- No changes to the scoring pipeline (audited earlier, working).
- No changes to the LLaMA / Ollama integration.
- No DB schema migrations without explicit approval.
- API contracts preserved; field additions are always additive optional.
- No new frontend dependencies; reuse existing components and styling.

---

## Phase 1 — five issues (audit only, no code)

| # | Severity | One-liner | Status |
|---|---|---|---|
| 1 | LOW | `origin=user-upload` rendered literally in Upload page copy | Fixed (`1201408`) |
| 2 | MEDIUM | Drift score stuck at 0.10; hard `min(0.099, …)` cap in `repository.py` | Fixed (`950bee2`, `06e4373`) |
| 3 | HIGH | Admin pages (System / Training / Incidents) hardcoded, not live | Incidents fixed (`1d189b0`); Training endpoint fixed (`5b98b3c`) + redesign in flight; System pending |
| 4 | LOW | "Anomalies" Y-axis label overlapping tick numbers on the dashboard chart | Fixed (`1201408`) |
| 5 | LOW | Sidebar order: move Feedback next to Anomalies | Fixed (`1201408`) |

Per-issue audit detail lives at the top of the relevant commit
message; see `git log --oneline backend/results-paper-numbers` for
the chain.

---

## Phase 2 — what shipped, in order

### Phase 2A — quick wins (commit `1201408`)

Three trivial cosmetic / ordering changes bundled because each is one
line of real change.

- `frontend/src/pages/Upload.tsx` — drop the `<code>origin=user-upload</code>`
  literal from the helper paragraph; replaced with prose
  ("filtered to just this upload").
- `frontend/src/components/TimelineChart.tsx` — bump `YAxis width` 36 → 56,
  bump `BarChart margin.left` 0 → 8, set rotated label `offset` to 0.
  Stops the "Anomalies" rotated label colliding with 4-digit tick numbers
  once anomaly counts pass 999.
- `frontend/src/components/Sidebar.tsx` — reorder `USER_ITEMS`:
  Feedback now sits between Anomalies and Upload.

### Phase 2B — drift score honest (commit `950bee2`)

Drift was permanently displaying 0.10 because of `psi = min(0.099, max(0.0, baseline))`
in `repository.py:drift_status`. The synthetic-mode score is the
std-dev of recent confidences (~0.20–0.30 across the trained domains)
but the cap was hiding it.

- `backend/api/repository.py` — drop the cap. New `_band_drift_status(psi)`
  helper banded by:
  - `psi <  0.40`           → `healthy`
  - `0.40 <= psi <  0.55`   → `drift_high`
  - `psi >= 0.55`           → `drift_critical`
  Both real-event and synthetic-mode paths use the same banding.
  Synthetic-mode path now sets `is_synthetic=True`.
- `backend/api/schemas.py` — added `is_synthetic: bool = False` to
  `DriftStatus` (additive optional, no breaking change).
- `frontend/src/types.ts` — mirrored `is_synthetic?: boolean`.
- `frontend/src/pages/System.tsx` — initially added a small subtext
  under the drift number; **subsequently removed** in commit
  `06e4373` per follow-up user request, alongside the
  "Last retrain X on the OpenStack dataset" sentence.

### Phase 2C.1 — Incidents page wired to real feedback (commit `1d189b0`)

The Incidents admin page used to render 20 hardcoded synthetic
"syn_001"–"syn_020" entries. It now lists rows where the user has
clicked **true positive** on the Feedback page.

- `backend/api/repository.py:list_feedback` — SQL extended with
  `root_cause`. Mapped into the per-item dict with `r["root_cause"] or ""`.
- `backend/api/schemas.py` — `FeedbackHistoryItem` gains
  `root_cause: str = ""` (additive, default empty).
- `frontend/src/types.ts` — mirrored `root_cause?: string`.
- `frontend/src/pages/Incidents.tsx` — full rewrite. `useFeedbackHistory(200)`,
  filter to `verdict === "true_positive"`. Source-filter chips built
  from real data, not a hardcoded tag taxonomy. Each row: severity
  badge → anomaly_id → source chip → relative time → log_template →
  2-line clamp of root_cause (with `ROOT CAUSE:` prefix and `IMPACT:`
  section trimmed for snippet density).

### Phase 2C.2 part 1 — Training endpoint + first-pass page (commit `5b98b3c`)

New backend endpoint, plus a first-pass rewrite of the page that
exposed the live data but kept too much of the legacy hero-card
visual style.

- `backend/api/schemas.py` — new `TrainingRun` + `TrainingRunsResponse`,
  plus `TrainingRunStatus` literal (`active | completed | failed`).
- `backend/api/repository.py` — new `list_training_runs(pool, limit)`
  returning `(items, active_id)` with server-side status derivation
  (`failed` when F1 is null or < 0.5; `active` for the most recently
  completed run with F1 ≥ 0.5; `completed` otherwise). `_TRAINING_RUN_F1_FLOOR`
  named (0.5).
- `backend/api/routes.py` — new `GET /api/v1/training/runs?limit=…`.
- `frontend/src/types.ts`, `api/client.ts`, `api/queries.ts` — type-mirrored,
  added `listTrainingRuns()`, added `useTrainingRuns(limit)` hook
  (60 s refetch).
- `frontend/src/pages/Training.tsx` — first-pass rewrite using the
  hook. **Now being redesigned** per Phase 2C.2 part 2 (next).

---

## Phase 2C.2 part 2 — Training page redesign (in progress)

### Why a redesign?

The first-pass page exposed real data but inherited the old layout's
two main UX problems:

1. F1/P/R rendered as huge `1.00 / 1.00 / 1.00` square cards — looked
   fake to anyone with ML experience, even though the underlying
   numbers are honest perfect scores on the saturated training domain.
2. The notes string ("Model B — Combined OS+HDFS (261,615 windows).
   lr=1e-4 + grad-clip max_norm=1.0 + pos_weight cap=10. Diverged at the
   original lr=2e-4...") was dumped raw into prime UI space, mixing a
   readable headline with hyperparameter detail.
3. "How to retrain" instruction box took as much vertical real-estate
   as the live model card.
4. Active run was duplicated — once as the hero card, once as the top
   row of the history table.
5. Run history was only 2 rows total, sparse and text-heavy.
6. Every section had equal visual weight; no clear hierarchy.

### What's being delivered

Frontend-only rewrite of `frontend/src/pages/Training.tsx`. No backend
change. Three sections, top-to-bottom:

#### Section 1 — Current model (compact, ~25% vertical)

One header line: `[active]  run #2  ·  trained May 2, 2026 · 22:16 UTC`.
Below it a single line: `<headline>  [dataset chip]`.
Then a tight three-tile metric strip:

```
F1          Precision    Recall
1.000       1.000        1.000
                   n = 261,615 windows · 16 min wall-clock
```

3-decimal precision always. The supporting caption (`n = … · … min
wall-clock`) is the honest counter-context that distinguishes "real
1.000 on 261k windows" from "1.000 on a toy 5-row run" — three
identical bare numbers should never appear without that caption.

A `<details>` element labelled `Training config` (closed by default).
When opened: artifacts path, started/completed/duration timestamps,
the parsed details portion of the notes (everything after the first
sentence). Native `<details><summary>` — no new component built.

#### Section 2 — Run history (dominant, ~60% vertical slot)

Active run is **excluded** (already shown above). Columns:

| Trained | Status | Dataset | F1 | P | R | Duration |

- Status: existing pill style (`failed` red, `done` muted).
- Dataset: inline chip (`border-[0.5px] px-1.5 py-0.5 text-[11px]`)
  matching the source-chip pattern used elsewhere.
- F1/P/R: 3 decimals, threshold-coloured (green ≥ 0.9, amber 0.5–0.9,
  red < 0.5).
- Duration: derived client-side from `completed_at - started_at`,
  formatted `Nm` or `Hh Mm`. `"in flight"` when `completed_at` is null.
- Click a row → toggles an inline expansion that reveals notes +
  artifacts_path. Single `expandedId` state — only one row open at
  a time. Caret in the rightmost cell flips ▸ ↔ ▾.
- Empty state: friendly "No previous runs." paragraph, no table chrome.

#### Section 3 — Maintenance (thin, ~15%)

A single closed `<details>` bar labelled `Developer: retrain command`.
When opened: the bash snippet (`cd backend && python -m
training.run_full_pipeline --dataset bgl`) and a paragraph explaining
the artifact-volume overwrite + worker-restart requirement. Same
content as the previous "How to retrain" section, demoted.

### Notes-string parser

Pure utility, derived three fields from the existing notes string:

| Field | Source |
|---|---|
| `headline` | After stripping `^Model [A-Z] —\s*`, take everything up to the first `.` or `(`, trim. Fallback: whole string up to first `.`/`(`. |
| `windows` | Match `\(([\d,]+)\s+windows?\)` anywhere; parse stripped int. `null` if no match → caption omits it. |
| `details` | Everything after the first `". "` of the prefix-stripped string. Empty → expander hides. |

Concrete output:

| id | headline | windows | details |
|---|---|---|---|
| 2 | Combined OS+HDFS | 261 615 | "lr=1e-4 + grad-clip max_norm=1.0 + pos_weight cap=10. Diverged at the original lr=2e-4; halving stabilised mixed-domain training." |
| 1 | OpenStack-only | 207 801 | "Honest 70/15/15 split. Cross-domain failure on HDFS (F1=0.000) is the headline finding that justifies Model B." |

### What's explicitly dropped versus the first-pass page

- The big square `MetricBox` cards.
- The `Per-model F1` 3-up grid (was misleading — we have ensemble
  metrics only).
- `RunMeta` blocks for Dataset / Artifacts in the active card →
  dataset reduced to a chip; artifacts moved into the expander.
- "How to retrain" full-card section → demoted to maintenance expander.
- Active run's row in history table → no duplication.
- History table's `Note` column → replaced with row-expand interaction.

### No new components, no new deps

| Reused | What for |
|---|---|
| Card chrome (`rounded-lg border-[0.5px] border-border-subtle bg-card p-5`) | Section containers |
| Existing status pill style | Run history status column |
| `EyebrowLabel`, `Skeleton`, `ErrorState`, `cn`, `formatRelativeTime` | as-is |
| Native `<details><summary>` | Both expanders — no shared expander component exists in the codebase |
| Inline chip pattern | Dataset chips |

---

## Phase 2C.3 — System page (pending, awaiting Training verification)

Three sub-tasks lined up:

### a. New backend endpoints

- `GET /api/v1/system/services` — per-service health probes for the
  five services in the existing hardcoded list (FastAPI, RAG worker,
  Redis, Ollama, Postgres). Probe strategy:
  - FastAPI: trivially "online" (the API serving this request is
    proof) — return `online`, version, uptime.
  - Redis: `await redis.ping()` — online if returns True; unreachable
    on exception.
  - Postgres: `await pool.fetchval("SELECT 1")` — online on success.
  - Ollama: `await llama.ping()` (existing helper) — online if
    `/api/tags` returns 200.
  - RAG worker: indirect — check the priority-queue Redis SET for
    recent activity, OR add a heartbeat key the worker writes every
    N seconds. Lean toward the latter (simpler, more honest), to be
    confirmed.
- `GET /api/v1/system/queue` — pending / ready / failed counts via a
  single `GROUP BY explanation_status` query, plus the oldest pending
  row's id and age.

### b. Active Models live wiring (per follow-up screenshot)

Current `/admin/system` shows three hardcoded model rows
(Transformer / AutoEncoder / Confidence MLP) with per-model F1 / P / R.
The `training_runs` table only stores **ensemble** metrics. Two paths
to actually live-wire those numbers — needs explicit approval before
implementing:

- **(a)** Show the active run's ensemble F1/P/R for all three model
  rows (same value across rows). Honest about what we store. No
  schema change.
- **(b)** Add `model_metrics JSONB` (or per-model F1 columns) to
  `training_runs`. Schema migration. Needs approval.

Recommendation: ship (a) immediately, document (b) as a follow-up.
Will propose with thresholds before applying.

### c. Page rewire

Replace the hardcoded `SERVICES` and `MODELS` consts with `useQuery`
hooks against the new endpoints, plus the queue-depth snippet. Drift
section already lives — keep it. No layout overhaul (just wiring).

---

## API surface diff at this point

| Endpoint | Status | Change |
|---|---|---|
| `GET /api/v1/anomalies` | unchanged | — |
| `GET /api/v1/anomalies/{id}` | unchanged | — |
| `GET /api/v1/anomalies/{id}/explanation` | unchanged | — |
| `POST /api/v1/anomalies/{id}/feedback` | unchanged | — |
| `GET /api/v1/feedback` | extended | `FeedbackHistoryItem.root_cause: str = ""` (additive optional) |
| `GET /api/v1/metrics/summary` | unchanged | — |
| `GET /api/v1/metrics/timeline` | unchanged | — |
| `GET /api/v1/system/drift` | extended | `DriftStatus.is_synthetic: bool = False` (additive optional). Score no longer capped at 0.099. |
| `GET /api/v1/training/runs` | **new** | List runs, derived status |
| `GET /api/v1/system/services` | **planned** | Phase 2C.3 |
| `GET /api/v1/system/queue` | **planned** | Phase 2C.3 |

Every change is additive. No breaking change for older API consumers.

---

## Commits on `backend/results-paper-numbers` (this audit cycle, oldest first)

```
1201408  fix: trio of small UX cleanups (Upload copy, chart axis, sidebar order)
950bee2  fix: drop drift-score 0.099 cap; band synthetic PSI honestly
06e4373  ui: drop synthetic-indicator subtext + last-retrain sentence on System
1d189b0  feat: Incidents page wired to real true-positive feedback
5b98b3c  feat: Training page wired to live training_runs table
(next)   feat: redesign Training page — compact current-model card, dense run history, maintenance demoted
(next)   feat: System page services + queue + Active Models live (Phase 2C.3)
```

---

## How to verify each phase landed

1. **Phase 2A** — Reload `/upload`: helper text reads "filtered to
   just this upload", no `origin=user-upload`. Reload `/dashboard`:
   "Activity over time" Y-axis label clears the tick numbers. Sidebar:
   Feedback sits between Anomalies and Upload.
2. **Phase 2B** — `curl /api/v1/system/drift` shows
   `drift_score: 0.238…, is_synthetic: true`. Was previously stuck
   at 0.099.
3. **Phase 2C.1** — Mark an anomaly true_positive on `/feedback`,
   then visit `/admin/incidents`: row appears with severity badge,
   anomaly id, source chip, relative time, template, explanation
   snippet.
4. **Phase 2C.2 part 1** — `curl /api/v1/training/runs` returns the
   two seeded runs with derived `status` and the `active_id` field.
5. **Phase 2C.2 part 2** (next) — `/admin/training` shows the compact
   active-model card with 3-decimal metrics + `n = … windows · …
   wall-clock` caption; run history table excludes the active run;
   "Developer: retrain command" sits collapsed at the bottom.
6. **Phase 2C.3** (planned) — `/admin/system` services grid driven by
   live probes; queue-depth section appears; Active Models card
   stops showing hardcoded F1s.

---

*End of handout. Updated continuously through Phase 2.*
