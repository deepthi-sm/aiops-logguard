# CLAUDE.md

> Context for Claude Code working on the **AIOps-LogGuard** project. Read this file first, then `docs/architecture/system_overview.md` for deeper technical context.

## What this project is

**AIOps-LogGuard** is a real-time log anomaly detection system. It watches logs from servers, uses an AI ensemble (Transformer + AutoEncoder) to spot anomalies before they cause failures, uses a local LLaMA model with RAG (FAISS retrieval over past incidents) to generate human-readable root cause explanations, and routes severity-tagged alerts to engineers (PagerDuty / Slack / email).

The novelty is the combination: most prior systems do anomaly detection OR explainability OR uncertainty OR failure prediction — none do all of them in one pipeline. This one does, plus RAG-based natural-language root cause + severity routing + deduplication.

## Team split (3 people, ~2-day sprint per phase)

This is a 3-person academic project for a Phase 1 Review 3 evaluation. The work is split across three roles. **Claude Code is helping Person A (backend/ML).**

- **Person A — Backend & ML (the user driving Claude Code).** Owns everything from raw log to anomaly object: ingestion, ML training, detection, RAG worker, API, websocket, alerting, CI/CD, Docker.
- **Person B — Frontend.** Owns the React/Vite/TypeScript dashboard. Consumes the API. Already has her brief; do not modify her work or files in `frontend/`.
- **Person C — Documentation.** Owns the report, paper, Gantt chart, risk register, SDG write-up. Does not write code.

**Important:** Person B and Person C have already received their own briefs. Claude Code's job is to help Person A ship the backend.

## The integration contract — never break this

Person A and Person B integrate through two things only:

1. **REST + WebSocket API endpoints** (Person A implements, Person B calls)
2. **The canonical anomaly JSON shape** (every anomaly object that crosses the boundary looks identical)

If you change either, you break Person B's frontend silently. The Pydantic models in `backend/api/schemas.py` are the source of truth. FastAPI auto-generates `openapi.json` from those models, and Person B generates her TypeScript client from that file. So: **the schema file IS the contract.**

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/health` | Liveness check |
| `GET` | `/api/v1/anomalies?limit=50&since=<iso>&severity=<critical\|warning\|info>` | Paginated list |
| `GET` | `/api/v1/anomalies/{id}` | Single anomaly |
| `GET` | `/api/v1/anomalies/{id}/explanation` | RAG + LLaMA root cause |
| `GET` | `/api/v1/metrics/timeline?window=1h\|24h\|7d` | Counts over time |
| `GET` | `/api/v1/metrics/summary` | Top-line KPIs |
| `POST` | `/api/v1/anomalies/{id}/feedback` | Engineer marks true/false positive |
| `WS` | `/api/v1/ws/anomalies` | Live anomaly push |
| `GET` | `/api/v1/system/drift` | Drift status |

### Canonical anomaly shape

```json
{
  "id": "anom_2026-04-28T10:14:22_a1b2",
  "detected_at": "2026-04-28T10:14:22Z",
  "severity": "critical",
  "source": "namenode-prod-3",
  "ensemble_score": 0.92,
  "confidence": 0.87,
  "failure_probability": 0.78,
  "predicted_failure_window_min": 12,
  "log_template": "ERROR blk_* NameNode connection refused from *",
  "sequence_preview": ["...", "...", "..."],
  "top_contributing_lines": [{ "line": "...", "attention": 0.31 }],
  "explanation_status": "ready",
  "cluster_id": "clu_77",
  "cluster_size": 14
}
```

- `severity` is exactly `"critical" | "warning" | "info"` — no other strings ever.
- `explanation_status` is `"pending" | "ready" | "failed"`.
- All timestamps are ISO 8601 UTC with `Z` suffix.
- `predicted_failure_window_min` may be `null` when failure prediction doesn't apply.

## Stack

- Python 3.11
- FastAPI + Pydantic v2
- asyncpg + Postgres
- Redis (streams for ingestion + pubsub for websocket broadcast)
- PyTorch (Transformer + AutoEncoder)
- sentence-transformers (`all-MiniLM-L6-v2` for prototype, `all-mpnet-base-v2` upgrade path)
- Drain3 (log template parsing)
- FAISS (vector retrieval for RAG)
- Ollama running LLaMA 3 8B locally (no log data leaves the system — privacy is a key paper claim)
- pytest + schemathesis for tests
- Docker + docker-compose

## Repo layout

```
aiops-logguard/
├── backend/                       # Person A (you)
│   ├── api/
│   │   ├── main.py                # FastAPI app + CORS for http://localhost:5173
│   │   ├── routes.py              # all REST endpoints
│   │   ├── ws.py                  # /ws/anomalies websocket
│   │   ├── schemas.py             # Pydantic models — THE CONTRACT
│   │   ├── db.py                  # asyncpg pool + queries
│   │   └── alerting.py            # PagerDuty / Slack / email routing
│   ├── ingestion/
│   │   ├── consumer.py            # async Redis stream consumer (logs:raw)
│   │   ├── parser.py              # Drain3 wrapper, loads drain3_state.bin
│   │   └── sequence_builder.py    # sliding window size=20, stride=1
│   ├── ml/
│   │   ├── detector.py            # loads .pt files, runs ensemble per window
│   │   ├── transformer.py         # model class
│   │   ├── autoencoder.py         # model class
│   │   ├── ensemble.py            # weighted combine + confidence scorer
│   │   ├── postprocess.py         # dedup + severity scoring
│   │   └── drift.py               # PSI drift computation
│   ├── rag/
│   │   ├── explainer.py           # async worker on anomalies:detected stream
│   │   ├── prompts.py             # LLaMA prompt templates (paper quotes these)
│   │   └── faiss_client.py        # loads faiss.index + incidents.jsonl
│   ├── training/
│   │   ├── data_prep.py           # download HDFS, run Drain3, normalise
│   │   ├── sequence_builder.py    # SHARED with ingestion — same logic
│   │   ├── embed.py               # SBERT primary + TF-IDF baseline
│   │   ├── train_transformer.py
│   │   ├── train_autoencoder.py
│   │   ├── calibrate.py           # tune w1, w2, thresholds, train confidence MLP
│   │   ├── build_faiss.py
│   │   ├── run_full_pipeline.py   # one command produces all artifacts
│   │   └── RESULTS.md             # F1/precision/recall — Person C lifts this
│   ├── tools/
│   │   └── log_replay.py          # replays HDFS file → Redis (CRITICAL for demo)
│   ├── artifacts/                 # gitignored — see .gitignore
│   ├── tests/
│   ├── Dockerfile
│   ├── docker-compose.dev.yml
│   └── requirements.txt
├── frontend/                      # Person B — DO NOT TOUCH
├── docs/                          # Person C — DO NOT TOUCH
├── docker-compose.yml             # Person A owns
├── .github/workflows/ci.yml       # Person A owns
├── .gitignore
└── README.md
```

## What lives in `backend/artifacts/` (all gitignored)

- `drain3_state.bin` — persisted Drain3 templates, shared between training and live
- `embeddings_hdfs.npy` — cached SBERT vectors (slow to recompute)
- `tfidf.npz` — TF-IDF baseline for paper comparison
- `transformer.pt` — TorchScript-saved model
- `autoencoder.pt` — TorchScript-saved model
- `thresholds.json` — `{ "w1": 0.62, "w2": 0.38, "anomaly_threshold": 0.71, "confidence_threshold": 0.65 }`
- `faiss.index` — FAISS index of past incidents
- `incidents.jsonl` — metadata per indexed incident

These get **mounted as a Docker volume**, never baked into images. The architecture explicitly forbids retraining on deploy.

## Build order — strict, do not skip ahead

Each step depends on the previous one working.

1. **Skeleton + docker-compose.** Redis + Postgres + Ollama up. FastAPI boots with stub `/health`. Postgres migration runs the schema (see `docs/architecture/database_schema.sql`).
2. **Pydantic schemas + stub endpoints returning fake data. HIGHEST PRIORITY.** Implement every endpoint with hardcoded mock anomaly objects. The instant `openapi.json` is published, Person B can generate her client and start real integration. Every hour delayed here is an hour she wastes against her own mocks.
3. **Pipeline 2 — offline training.** Cannot test live pipeline without trained artifacts. Output: every file in `artifacts/` exists and `python -m training.run_full_pipeline --dataset hdfs` works end-to-end.
4. **Pipeline 1 — live ingestion + detection.** Redis consumer → parser → sequence builder → detector → Postgres + websocket broadcast.
5. **RAG worker.** Separate process subscribing to `anomalies:detected`. FAISS retrieval → Ollama → update Postgres `explanation_status='ready'`.
6. **Postprocess (severity + dedup) + drift detector.**
7. **Alerting (PagerDuty / Slack / email).** Behind feature flags so dev runs without real keys.
8. **`tools/log_replay.py` — critical for demo.** Without this there's nothing to demo.
9. **Tests** — unit + e2e + schemathesis contract tests.

If time runs out, cut from the bottom. Steps 1–5 give a working demo.

## Hard rules

- **Don't bake artifacts into Docker images.** Mount `backend/artifacts/` as a volume.
- **Don't change the anomaly schema after Person B has generated her client.** If you must, post in the team channel BEFORE merging the PR. Bump an API version if breaking.
- **Don't run LLaMA inference inline in the detection path.** Always async via the explanation worker. Detection must stay fast.
- **Don't share Drain3 state by reloading from raw.** Both training and inference load the same persisted `drain3_state.bin` so templates are byte-identical.
- **Don't push directly to `main`.** Use `backend/<feature>` branches and PRs. CI must pass.
- **Don't skip the stub endpoints (Step 2).** It's the single highest-leverage hour of the whole project.

## Naming conventions

- Python: `snake_case.py`, `snake_case` functions and variables, `PascalCase` classes
- Anomaly IDs: `anom_<iso8601>_<4hex>` — generated server-side, opaque to the frontend
- Severity values: exactly `"critical" | "warning" | "info"`
- Timestamps: ISO 8601 UTC with `Z` suffix
- Env vars: `LOGGUARD_<SCOPE>_<NAME>` — e.g. `LOGGUARD_REDIS_URL`, `LOGGUARD_LLAMA_HOST`
- Branches: `backend/<feature>` for Person A's work
- Redis streams: `logs:raw` (ingest), `anomalies:detected` (for RAG worker), `anomalies:broadcast` (for websocket)

## How Claude Code should work in this repo

- **Default to small, reviewable PRs.** A whole pipeline in one PR is unreviewable.
- **Run tests before claiming work is done.** `cd backend && pytest`.
- **Never modify `frontend/` or `docs/`** — those are Person B and Person C's territory.
- **When changing `api/schemas.py`, flag it loudly in the PR description.** This is a contract change.
- **Always check this CLAUDE.md when starting fresh.** If something here contradicts a user instruction, ask the user — don't silently override the rules.
- **Read `docs/architecture/system_overview.md` before working on a layer you haven't touched yet.** It has the full per-layer technical detail.

## Reference docs in this repo

- `docs/architecture/system_overview.md` — six-layer architecture walkthrough
- `docs/architecture/pipelines.md` — three pipelines (data flow, training, CI/CD) explained
- `docs/architecture/database_schema.sql` — Postgres DDL
- `docs/architecture/api_contract.md` — full endpoint + schema reference
- `docs/architecture/training_pipeline.md` — Pipeline 2 detailed steps + hyperparameters
- `docs/architecture/ml_models.md` — model architectures, ensemble math, drift detection
- `docs/architecture/rag_design.md` — RAG worker, prompt design, FAISS setup
- `docs/architecture/two_day_priorities.md` — what to ship if time runs out

When in doubt, the source of truth order is: (1) `api/schemas.py`, (2) this CLAUDE.md, (3) `docs/architecture/*.md`, (4) the user's chat instructions.
