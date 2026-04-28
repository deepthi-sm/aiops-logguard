# Two-Day Sprint Priorities

This is a 3-person academic project with a hard deadline. If time runs out, **cut from the bottom**, never from the top. The order below is what ships in what order.

## The "must ship" core (steps 1–6)

These give you a working demo. Without all six, you don't have a project.

### 1. Skeleton + docker-compose (~1 hour)

`docker-compose.yml` brings up Redis, Postgres, Ollama. FastAPI boots with a single `/api/v1/health` route returning `{"status": "ok"}`. Postgres migration runs the schema from `docs/architecture/database_schema.sql`.

**Done when:** `docker-compose up` works, `curl http://localhost:8000/api/v1/health` returns 200.

### 2. Pydantic schemas + stub endpoints (~2 hours) — HIGHEST LEVERAGE

Implement every endpoint listed in `docs/architecture/api_contract.md` returning **hardcoded fake anomaly data**. The Pydantic models in `backend/api/schemas.py` must be complete and correct.

**Why this is the most important hour of the project:** the moment FastAPI publishes `openapi.json`, Person B can generate her TypeScript client and start real integration. Every hour you delay this is an hour she wastes against her local mocks.

**Done when:** every endpoint in the contract returns a 200 with fake data, `openapi.json` is at `http://localhost:8000/openapi.json`, and Person B confirms her client generation works.

### 3. Pipeline 2 — train all models (~6–10 hours)

Run the full training pipeline. See `docs/architecture/training_pipeline.md` for step-by-step.

`python -m training.run_full_pipeline --dataset hdfs` produces:
- `drain3_state.bin`
- `embeddings_hdfs.npy`
- `tfidf.npz`
- `transformer.pt`
- `autoencoder.pt`
- `confidence_scorer.pt`
- `thresholds.json`
- `faiss.index`
- `incidents.jsonl`
- `RESULTS.md`

**Time cost note:** SBERT embedding on CPU is the long pole. On a GPU it's minutes. If you're CPU-only, kick this off the moment skeleton is ready and let it run in the background while you do step 2 in parallel.

**Done when:** all artifacts exist, `RESULTS.md` has F1 numbers, and you can load the `.pt` files in a Python REPL without errors.

### 4. Pipeline 1 — live detection (~6 hours)

Wire up the live path:
- Redis consumer reading `logs:raw`
- Drain3 parser (loading the persisted state)
- Sequence builder
- Detector loading the `.pt` files
- Postgres insert + Redis pubsub broadcast

Replace the stub `GET /api/v1/anomalies` with a real Postgres query. Replace the stub websocket with one that subscribes to `anomalies:broadcast`.

**Done when:** running `python tools/log_replay.py training/data/hdfs/HDFS.log --rate 100` causes anomalies to appear in Postgres and on the websocket.

### 5. RAG worker (~3 hours)

Separate process: subscribes to `anomalies:detected` stream, does FAISS retrieval, calls Ollama, updates Postgres. See `docs/architecture/rag_design.md`.

**Done when:** within 30 seconds of an anomaly being inserted, its `explanation_status` flips to `ready` and `root_cause` + `recommended_fix` are populated.

### 6. `tools/log_replay.py` (~1 hour) — critical for demo

Reads an HDFS log file, pushes lines to Redis stream `logs:raw` at configurable rate. Has a `--inject-anomaly` flag that interleaves known-anomalous block IDs every N seconds.

**Without this, the demo has nothing to show.** Don't skip even if you're behind. It's an hour and it's what evaluators see.

**Done when:** running the script produces a steady stream of normal anomalies plus reliable critical alerts at the configured cadence.

---

## The cut line — below here is hardening

Steps 1–6 give a working demo. If time is short, ship those, then do 7–10 in priority order.

### 7. Severity routing + dedup (~2 hours)

The dedup logic and severity rules from `docs/architecture/system_overview.md` Layer 4c. Without these, the demo will show 50 identical critical alerts for one underlying problem (looks bad).

### 8. Drift detector (~2 hours)

The PSI-based drift detector. The frontend's `/system` page expects the `/api/v1/system/drift` endpoint to return a real value. Until this exists, return a hardcoded 0.12.

### 9. Real alerting (~3 hours)

PagerDuty / Slack / email integration. Mock these in dev with feature flags. For the demo, you can fake all three with console logs and it'll be fine.

### 10. Test suite (~3 hours)

Unit tests, e2e test that replays known anomalies, schemathesis contract tests. Critical for CI but not for the demo.

---

## What "demo-ready" means

The minimum bar to walk into Review 3 and not be embarrassed:

1. ✅ `docker-compose up` brings up the whole system
2. ✅ Person B's frontend loads and connects to the websocket
3. ✅ `tools/log_replay.py --inject-anomaly` is running in a terminal
4. ✅ Anomalies appear in the live feed within seconds
5. ✅ Clicking an anomaly shows the LLaMA-generated root cause and recommended fix
6. ✅ The attention-weighted log lines render with shading on the detail page
7. ✅ The KPI cards show real numbers
8. ✅ The timeline chart shows real bucketed counts
9. ✅ Marking true/false positive posts back to the API and persists

If all 9 work, you have a demo. Anything else is bonus.

---

## Time-saving shortcuts (use only if you must)

These compromise quality but ship faster. Document each shortcut in your code so Person C knows what's "future work" for the paper.

| Shortcut | Time saved | Cost |
|---|---|---|
| Skip BGL dataset, only use HDFS | 4 hours | Paper has weaker robustness claim |
| Use only `all-MiniLM-L6-v2`, skip mpnet upgrade path | 0 hours | Paper claims mpnet would be better — fine to defer |
| Skip the confidence scorer MLP, just use a fixed confidence threshold | 2 hours | Higher false positive rate; mention as limitation |
| Hardcode 5 hand-written incidents instead of 20–30 | 1 hour | LLaMA explanations less specific |
| Skip TF-IDF baseline | 1 hour | Paper has no baseline comparison — only do this if absolutely desperate |
| Skip drift detector, hardcode `0.12` | 2 hours | `/system` page is static; mention as future work |
| Mock PagerDuty/Slack/email with console logs | 3 hours | Demo still works (the routing logic is what matters) |

Never cut: training pipeline correctness, RAG worker, websocket, log_replay.

---

## Daily checklist

End of Day 1 should have:
- ✅ Repo on GitHub with branch protection
- ✅ docker-compose.yml works
- ✅ All API endpoints stubbed (Person B unblocked)
- ✅ Training pipeline running (might still be embedding overnight)

End of Day 2 should have:
- ✅ Real models loaded into detector
- ✅ Live anomalies appearing on Person B's dashboard
- ✅ RAG worker producing explanations
- ✅ log_replay.py demoing reliably
- ✅ At least the README.md is up-to-date

If Day 2 ends without one of those four, you're in cut-from-the-bottom territory.
