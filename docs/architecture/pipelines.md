# The Three Pipelines

The system runs in three modes. Understand which pipeline you're working on before changing code — they have different lifecycles, different inputs, and different SLAs.

## Pipeline 1 — Real-time data flow

**Runs:** 24/7 against live logs
**Input:** Redis stream `logs:raw`
**Output:** Anomaly rows in Postgres + websocket broadcasts + alerts
**SLA:** detection-to-dashboard under 1 second

### Flow

```
Backend app emits log line
    ↓
Filebeat / log shipper tails it, pushes to Redis Streams
    ↓
[backend/ingestion/consumer.py] reads from logs:raw
    ↓
[backend/ingestion/parser.py] Drain3 extracts template
    ↓
[backend/ingestion/sequence_builder.py] window fills to 20 events
    ↓
[backend/ml/detector.py] SBERT embeds the window
    ↓
Transformer encoder → anomaly_score, failure_prob, attention_weights
AutoEncoder → reconstruction_error_score
    ↓
[backend/ml/ensemble.py] weighted combine + confidence scorer
    ↓
Confidence threshold met?
    NO → discard
    YES ↓
    ↓
[backend/ml/postprocess.py] dedup + severity scoring
    ↓
Write to Postgres `anomalies` table
Push to Redis stream `anomalies:detected` (RAG worker picks this up)
Broadcast on Redis pubsub `anomalies:broadcast` (websocket pushes to frontend)
    ↓
[backend/rag/explainer.py] (async, separate process)
    ↓
FAISS top-5 retrieval + LLaMA via Ollama
    ↓
Update Postgres row: explanation_status='ready', root_cause, recommended_fix
    ↓
[backend/api/alerting.py] severity-routed alert sent
```

### Code organisation

```
backend/
├── ingestion/      # everything from Redis to a windowed sequence
├── ml/             # detection, scoring, post-processing
├── rag/            # async LLaMA explanation worker (separate process)
├── api/            # FastAPI surface + websocket + alerting
```

## Pipeline 2 — Offline training

**Runs:** once at project start; then only when the drift detector triggers retraining
**Input:** HDFS dataset from LogHub (and BGL as secondary)
**Output:** all files in `backend/artifacts/`
**SLA:** can take hours — runs offline, no latency constraint

### Flow

```
Download HDFS dataset from LogHub
(backend/training/data_prep.py)
    ↓
Parse with Drain3, persist state to artifacts/drain3_state.bin
Strip IDs, IPs, timestamps, block IDs, UUIDs, hex
    ↓
Build sliding window sequences (size=20, stride=1)
HDFS labels: anomaly if any block ID in window appears in labelled anomaly set
(backend/training/sequence_builder.py — SHARED with ingestion)
    ↓
SBERT embed every window
Cache to artifacts/embeddings_hdfs.npy (slow — never recompute)
Also produce TF-IDF baseline → artifacts/tfidf.npz (paper baseline only)
(backend/training/embed.py)
    ↓
Train Transformer encoder (anomaly head + failure-window head)
AdamW, lr=2e-4, cosine schedule, 30 epochs, early stop on val F1
Save TorchScript to artifacts/transformer.pt
(backend/training/train_transformer.py)
    ↓
Train AutoEncoder (only on normal sequences)
Symmetric, bottleneck=64-d, MSE loss
Save TorchScript to artifacts/autoencoder.pt
(backend/training/train_autoencoder.py)
    ↓
Calibrate ensemble:
  - Grid search (w1, w2, anomaly_threshold) on val set, optimise F1
  - Train confidence scorer MLP on held-out predictions
  - Save to artifacts/thresholds.json
(backend/training/calibrate.py)
    ↓
Build FAISS index:
  - Embed labelled HDFS anomalies
  - Add 20–30 hand-written synthetic incidents (critical for RAG quality)
  - Save artifacts/faiss.index + artifacts/incidents.jsonl
(backend/training/build_faiss.py)
    ↓
All artifacts saved to artifacts/
Live system loads these at startup. No retraining until drift detected.
```

### Single-command entry point

```bash
python -m training.run_full_pipeline --dataset hdfs
```

This must produce every file in `artifacts/` end-to-end. Document F1, precision, recall in `backend/training/RESULTS.md` — Person C lifts these numbers into the paper.

### Why train first?

You can't test the live pipeline if the models don't exist. Pipeline 2 is build-order dependency #3 (after the skeleton and stub endpoints) precisely because Pipeline 1 needs `*.pt`, `faiss.index`, and `thresholds.json` to start.

### Drift-triggered retrain

The drift detector emits a `retrain_needed` event when PSI > 0.4. A separate cron job (or manual run) re-executes Pipeline 2. Live system continues running on old artifacts during retrain — atomic swap when done.

## Pipeline 3 — CI/CD

**Runs:** on every PR and every merge to main
**Input:** code commits
**Output:** Docker images deployed to staging, then production

### Flow

```
Developer opens PR
    ↓
GitHub Actions runs ci.yml:
  - pytest (backend tests)
  - ruff (lint)
  - npm test + npm run build (frontend)
  - schemathesis (API contract tests against openapi.json)
    ↓
Tests pass? NO → block merge
              YES ↓
    ↓
Code review + merge to main
    ↓
GitHub Actions builds Docker images:
  - backend
  - frontend
  - rag-worker (separate from backend so it scales independently)
    ↓
Push images to registry
    ↓
Deploy to staging: docker-compose up
    ↓
Smoke test: replay sample logs via tools/log_replay.py, assert anomalies appear
    ↓
Smoke pass? NO → halt deploy
             YES ↓
    ↓
Deploy to production: docker-compose / Kubernetes rollout
    ↓
Model artifacts mounted as volumes — NO retraining on deploy
```

### Why three separate Docker services

- **backend** — FastAPI + ingestion + detection. Stateless, can scale horizontally.
- **rag-worker** — RAG explainer. CPU-heavy (LLaMA via Ollama). Different scaling profile.
- **frontend** — static React build served by nginx. Trivial to scale.

Splitting them lets you scale RAG independently when LLaMA becomes a bottleneck without scaling the rest.

### Artifact handling in CI/CD

Critical: model artifacts are **never** baked into Docker images. They're mounted as volumes from a separate `artifacts/` location (in production: a shared NFS mount or object storage; in dev: a local directory). This enforces the architecture's "no retraining on deploy" rule and means a model update doesn't require a new image build.

## How the three pipelines interact

- Pipeline 2 produces artifacts → Pipeline 1 consumes them at startup
- Pipeline 1 detects drift → triggers a Pipeline 2 retrain
- Pipeline 3 deploys both Pipeline 1 (live system) and Pipeline 2 (training scripts) but doesn't *run* training
- Engineer feedback (from frontend) → Postgres → next Pipeline 2 retrain uses it as labels
