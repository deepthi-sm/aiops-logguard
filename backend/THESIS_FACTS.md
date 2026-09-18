# LogGuard — Thesis Fact Sheet

> Single-source reference of what is actually built, drawn from the
> repository state. Pure facts; final-state only. Use directly in the
> thesis write-up.

---

## 1. Project identity

- **Project title:** AIOps-LogGuard — Real-Time Log Anomaly Detection with Ensemble Deep Learning and RAG-Based Root-Cause Explanation
- **Authors:**
  - Deepthi M Sharma — `1BM23CD015`
  - Khushi P Vernerker — `1BM23CD026`
  - Geetha R — `1BM24CD400`
- **Guide:** Prof. Navya Damodar
- **Course code:** *(insert course code from your project handbook — not stored in repo)*
- **Institution / dept:** B.M.S. College of Engineering, Computer Science (Data Science)

---

## 2. Final architecture (six layers)

| # | Layer | Components / files | Key tech |
|---|---|---|---|
| 1 | **Log sources** | `POST /api/v1/upload` (file), `POST /api/v1/connect` (URL fetch), `GET /demo/stream` (synthetic NDJSON). Output written to Redis stream `logs:raw`. | FastAPI multipart, httpx URL fetch, Redis Streams (`XADD`) |
| 2 | **Ingestion + parsing** | `backend/ingestion/runner.py` consumes `logs:raw` (`XREAD`); `ingestion/parser.py` runs Drain3 against persisted `drain3_state.bin`; `ingestion/sequence_builder.py` produces 20-event sliding windows (stride 1). | Drain3 0.9.11 (template mining), Redis Streams |
| 3 | **Vectorisation** | `ml/embedder.py` SBERT-embeds each templated event in a window. | `sentence-transformers/all-MiniLM-L6-v2` (HuggingFace, 384-dim) |
| 4 | **Detection ensemble** | `ml/detector.py` loads three TorchScript artefacts: `transformer.pt`, `autoencoder.pt`, `confidence_scorer.pt`. Outputs are combined in `ml/ensemble.py` using calibrated weights `w1/w2`. `ml/postprocess.py` produces final severity + `top_contributing_lines` from per-event attention. | PyTorch 2.5.1 |
| 5 | **RAG explanation** | `rag/explainer.py` is a separate worker process. For each `pending` anomaly: SBERT-embeds `log_template`, runs FAISS top-K against the indexed past-incident corpus, builds a structured prompt (`rag/prompts.py`), calls Ollama via `rag/llama_client.py`, parses the three-section response, writes `root_cause` + `recommended_fix` + `similar_incidents` back to Postgres. | FAISS-CPU 1.9.0, Ollama (`llama3:8b` GPU / `llama3.2:1b` CPU) |
| 6 | **Persistence + UI** | Postgres tables `anomalies`, `drift_events`, `training_runs`. WebSocket at `/api/v1/ws/anomalies` pushes broadcast events. React/Vite SPA renders the live dashboard, anomaly detail, system health, training history, and incident review. | asyncpg 0.30.0, Postgres 16, FastAPI WS, React 18 + TanStack Query 5 |

### Data flow

```
[client]              [layer 1]            [layer 2]           [layer 3]
upload .log/.txt   ─►  FastAPI       ─►  XADD logs:raw    ─►  ingestion runner
                                                              ↓
                                                              Drain3 parse + sliding window
                                                              ↓
                                                          [layer 3]
                                                          SBERT embed (20 × 384)
                                                              ↓
                                                          [layer 4]
                                                          Transformer + AE + Confidence MLP
                                                              ↓
                                                          severity + cluster + dedupe
                                                              ↓
[layer 6] Postgres ◄─ INSERT anomaly ◄─────────────────────  runner
                       (status='pending')
                       ↓
                       publish anomalies:detected
                       publish anomalies:broadcast
                       ↓                         ↓
                  [layer 5]                 [layer 6]
                  RAG worker                WebSocket /ws → frontend live
                  ↓
                  SBERT(log_template) → FAISS top-K
                  ↓
                  build prompt → Ollama HTTP /api/generate
                  ↓
                  parse response
                  ↓
                  UPDATE anomalies SET root_cause=…, status='ready'
```

---

## 3. Final ML configuration

### Drain3 (template parser)

- Library: `drain3==0.9.11`
- Persistence: `FilePersistence(drain3_state.bin)`. Training calls `add_log_message()`; inference calls `match()` only — guarantees byte-identical templates between training and live ingestion.
- Output template normalisation (after Drain3): hex / IP / UUID / numeric placeholders applied via `training/data_prep.normalise_template()`.

### SBERT embedder

- Model: `sentence-transformers/all-MiniLM-L6-v2`
- Embedding dim: **384**
- Normalisation: unit-norm, batch-encode each window's templated events.

### Sliding window (training and inference, byte-identical)

- `WINDOW_SIZE = 20`
- `WINDOW_STRIDE = 1`
- Input shape to the transformer: `(B, 20, 384)`.

### Transformer encoder (`ml/transformer.py`)

| Hyperparameter | Value |
|---|---|
| `d_input` (SBERT dim) | 384 |
| `d_model` | **256** |
| `n_layers` | **4** |
| `n_heads` | **8** |
| `dim_feedforward` | **1024** (`4 × d_model`) |
| activation | **GELU** |
| dropout | 0.1 |
| positional encoding | learned, `(1, 20, 256)` parameter |
| classification head | mean-pool → `Linear(256, 1)` (anomaly logit) |
| failure-window head | `Linear(256, 1)` (regression on minutes) |
| attention export | per-event saliency `(B, 20)` summing to ~1 |
| serialisation | `torch.jit.script` → `transformer.pt` |

### AutoEncoder (`ml/autoencoder.py`)

```
384 → 256 → 128 → 64 → 128 → 256 → 384      (ReLU activations)
```

- `d_bottleneck = 64`
- Loss: MSE
- Trained on **normal-only** windows; reconstruction error is the anomaly signal.
- Operates on mean-pooled window embedding (single 384-vector per window).

### Confidence MLP (`training/calibrate.py`)

```
4 → 32 → 16 → 1   (ReLU, sigmoid output)
```

- `CONFIDENCE_INPUT_DIM = 4`. Input features: `(transformer_score, ae_error_normalised, seq_len_norm, time_of_day_norm)`.
- Loss: BCE.
- Target: `1` if combined-score-based prediction matches ground-truth label, else `0`.

### Training hyperparameters

| | Transformer | AutoEncoder | Confidence MLP |
|---|---|---|---|
| optimiser | AdamW | Adam | Adam |
| learning rate | `1e-4` | `1e-3` | (default Adam) |
| weight decay | `0.01` | — | — |
| LR schedule | CosineAnnealingLR (`T_max=epochs`) | none | none |
| batch size | 64 | 256 | (per `calibrate.py`) |
| epochs | 30 | 50 | (per `calibrate.py`) |
| early-stop patience | 5 (val F1) | 10 (val recon loss) | — |
| `val_split` | 0.20 | 0.20 | — |
| class-imbalance handling | `pos_weight` cap = 10, grad-clip `max_norm=1.0` | — | — |

### Calibration (`backend/artifacts/thresholds.json`, current Model B)

| Field | Value |
|---|---|
| `w1` (transformer weight) | **0.85** |
| `w2` (AE weight) | **0.15** |
| `anomaly_threshold` | **0.60** |
| `confidence_threshold` | **0.0** |
| `ae_error_p10` | `1.40 × 10⁻⁸` |
| `ae_error_p90` | `1.50 × 10⁻⁷` |

(`w1 + w2 = 1`. The combined ensemble score is `w1 · sigmoid(transformer_logit) + w2 · ae_error_normalised`.)

---

## 4. Datasets used

| Dataset | Source files | Total lines | Role | Labelling method |
|---|---|---:|---|---|
| **OpenStack** | `openstack_normal1.log` + `openstack_normal2.log` + `openstack_abnormal.log` | **207,820** | Train + held-out test for Models A and B | UUID list in `anomaly_labels.txt`. A window is "anomaly" if any of its raw lines mentions a flagged UUID (canonical UUID regex; substring match for non-UUID ids). |
| **HDFS** | `HDFS.log` (LogHub HDFS_v1) | **11,175,629** | Train (Model B only) + held-out test | Block-id-based positives from LogHub's `anomaly_label.csv`. |
| **Apache** | `Apache.log` | **56,481** | Cross-dataset test only — never seen by either model | Log-level fallback: `[error]` / `[warn]` / `[fatal]` → anomaly. |
| **BGL** | `BGL_2k.log` (LogHub 2k sample) | **1,999** | Demo upload only; not used in training or evaluation | n/a |
| **Thunderbird** | `Thunderbird_2k.log` (LogHub 2k sample) | **1,999** | Demo upload only; not used in training or evaluation | n/a |

Held-out splits used `TEST_FRACTION = 0.15`, `TEST_SEED = 99` — test slices were excluded from both gradient updates and threshold calibration.

---

## 5. Final evaluation results

Source: `backend/artifacts_proper/RESULTS_SUMMARY.md` (auto-generated by `training/run_proper_eval.py`).

### F1 — head-to-head

| | OpenStack test | HDFS test | Apache (never seen) |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | 0.936 | 0.000 | 0.984 |
| **Model B — Combined OS+HDFS** | 1.000 | 0.516 | 0.914 |

### AUC — threshold-independent ranking quality

| | OpenStack test | HDFS test | Apache (never seen) |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | 0.996 | 0.396 | 0.458 |
| **Model B — Combined OS+HDFS** | 1.000 | 0.670 | 0.368 |

### Precision / Recall (per slice)

| Model | Test set | Precision | Recall |
|---|---|---:|---:|
| Model A — OpenStack-only | OpenStack | 0.894 | 0.982 |
| Model A — OpenStack-only | HDFS | 0.000 | 0.000 |
| Model A — OpenStack-only | Apache | 0.994 | 0.974 |
| Model B — Combined OS+HDFS | OpenStack | 1.000 | 1.000 |
| Model B — Combined OS+HDFS | HDFS | 0.395 | 0.745 |
| Model B — Combined OS+HDFS | Apache | 0.989 | 0.849 |

### Sample sizes for the held-out tests

| Slice | n total | n positive (rate) |
|---|---:|---|
| OpenStack held-out test | 31,170 | 2,720 (8.7 %) |
| HDFS held-out test | 14,997 | 4,639 (30.9 %) |
| Apache full corpus (cross-dataset) | 56,463 | 55,896 (99.0 %) |

### Reading guide

- *OpenStack test*: in-distribution headline number for both models (Model B saturates at 1.000 — perfect classification on the held-out OpenStack slice with TP = 2,720 / FN = 0 / FP = 0 / TN = 28,450).
- *HDFS test*: cross-dataset for Model A, in-distribution for Model B. Model A ranking is better than its F1 implies (AUC = 0.396 ≪ 0.5 says the threshold mis-fires; the model essentially never predicts anomaly on HDFS).
- *Apache*: full cross-dataset robustness check. Both models keep > 0.9 F1 here; AUC < 0.5 indicates that the high F1 is largely because Apache is 99 % positive (logs labelled by `[error]`/`[warn]`/`[fatal]` fallback) and the models default-predict positive on saturated inputs.

---

## 6. System contracts

### REST API (FastAPI, prefix `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check + version + uptime. |
| `GET` | `/anomalies?limit&since&severity&source&origin&cursor` | Paginated anomaly list. |
| `DELETE` | `/anomalies` | Wipe all anomaly + drift rows + Redis priority queue (demo reset). |
| `GET` | `/anomalies/{id}` | Single anomaly. |
| `GET` | `/anomalies/{id}/explanation` | RAG explanation; 200 / 202 (pending) / 500 (failed). |
| `POST` | `/anomalies/{id}/feedback` | Engineer marks `true_positive` / `false_positive`. |
| `GET` | `/feedback?limit` | List feedback history (denormalised; includes `root_cause`). |
| `GET` | `/metrics/summary` | Top-line KPIs (24h totals, severity counts, drift, last retrain). |
| `GET` | `/metrics/timeline?window=1h\|24h\|7d` | Stacked counts per bucket. |
| `GET` | `/system/drift` | Synthetic-PSI proxy + status banding (healthy / drift_high / drift_critical). |
| `GET` | `/system/services` | Live probes: FastAPI, Postgres, Redis, Ollama. |
| `GET` | `/system/queue` | `pending` / `ready` / `failed` counts + oldest pending. |
| `GET` | `/training/runs?limit` | Historical training runs; derived `status`. |
| `POST` | `/upload` | Multipart `.log`/`.txt` ingest into Redis stream. |
| `POST` | `/connect` | Stream from a URL or keyword-matched server-side sample file. |
| `GET` | `/upload/{job_id}/status` | Streaming job progress. |
| `WS` | `/api/v1/ws/anomalies` | Live anomaly + explanation_ready push. |
| `GET` | `/demo/stream?count&seed` | Synthetic NDJSON feed for the **Connect** demo flow. |

### Redis channels and keys

| Name | Type | Producer | Consumer |
|---|---|---|---|
| `logs:raw` | Stream | upload + connect handlers | ingestion runner (`XREAD`) |
| `anomalies:detected` | Pub/Sub | runner (after detection) | RAG worker (legacy fan-out path; currently uses DB-poll instead) |
| `anomalies:broadcast` | Pub/Sub | runner | WebSocket handler `/api/v1/ws/anomalies` |
| `anomalies:priority:set` | Set (`SADD`/`SPOP`) | API (`GET /explanation` on a pending anomaly) | RAG worker (priority pop before LIFO DB poll) |

### Severity rules (`ml/postprocess.py`)

```python
CRITICAL_ENSEMBLE_SCORE = 0.95
WARNING_ENSEMBLE_SCORE  = 0.75

if ensemble_score > 0.95 and source in critical_sources:
    severity = "critical"
elif ensemble_score > 0.75:
    severity = "warning"
else:
    severity = "info"
```

`DEFAULT_DEDUP_WINDOW_S = 60` — same `(template, source)` within 60 s collapses into one anomaly cluster (incrementing `cluster_size`). `DEFAULT_TOP_CONTRIBUTING = 4` — top-4 attention-weighted lines surfaced per anomaly.

### `DEFAULT_CRITICAL_SOURCES`

```python
frozenset({
    # OpenStack production-like sources from the training corpus
    "nova-api-prod-3", "neutron-server-1", "glance-api-2",
    "keystone-api-2", "namenode-prod-1",
    # entry-point tag for /upload
    "user-upload",
    # synthetic /demo/stream + log_replay default
    "mixed",
    # filename-stem slugs for the demo upload datasets
    "bgl", "bgl-2k", "bgl-500",
    "thunderbird", "thunderbird-2k", "thunderbird-500",
    "hdfs", "hdfs-200", "hdfs-100k",
    "apache", "apache-1000",
    "openstack", "openstack-abnormal",
})
```

Override at runtime with the `LOGGUARD_CRITICAL_SOURCES` env var (comma-separated list).

### Anomaly id format

`anom_<iso8601>_<4hex>` — e.g. `anom_2026-05-04T17:35:02_8a35`. Generated server-side, opaque to the frontend.

### Postgres tables (`backend/api/schema.sql`)

- `anomalies` — primary table, indexed on `(detected_at DESC)`, `severity`, `cluster_id`, `explanation_status`, `origin`, and a composite `(detected_at, severity)`.
- `drift_events` — periodic drift detector output. Currently empty; the System page falls back to a synthetic-PSI proxy until rows arrive.
- `training_runs` — append-only training history. Auto-seeded with two rows on first API boot (Model A + Model B).

---

## 7. What works end-to-end

- **Upload flow.** Drag-and-drop `.log` / `.txt` file at `/upload` (max 50 MB) → `XADD logs:raw` → ingestion runner → detection → Postgres → WebSocket broadcast → frontend live update.
- **URL-fetch flow.** Paste any URL (or keyword for a server-side sample) at `/connect` → API HTTP-fetches NDJSON → same downstream path as upload.
- **Synthetic demo stream.** `GET /demo/stream?count=200` returns NDJSON with the project's fixed template pool (BGL / Thunderbird / HDFS / OpenStack-style mix). Used by the Connect demo.
- **Live anomaly detection.** Drain3 + SBERT + ensemble + confidence MLP run at ~3 windows/sec on CPU (host laptop).
- **Severity routing.** Three-tier (`critical` / `warning` / `info`) with the rules above; demonstrably end-to-end on user-uploaded BGL/HDFS/etc. files via `DEFAULT_CRITICAL_SOURCES`.
- **Cluster deduplication.** 60-second window collapses repeated `(template, source)` pairs into a single anomaly with `cluster_size > 1`.
- **RAG explanation worker.** Real Ollama HTTP call per anomaly. Three-section postmortem output (`ROOT CAUSE` / `IMPACT` / `RECOMMENDED FIX`). 15-min hard timeout per call. Structured logs with `rid=<anomaly_id>`, prompt size, eval-token count, elapsed time.
- **Priority queue.** When a user clicks a `pending` anomaly, the API `SADD`s its id onto `anomalies:priority:set` so the RAG worker pops it before the LIFO DB queue.
- **Live dashboard.** `/dashboard` (KPI strip, timeline, recent anomalies), `/anomalies` (paginated list with severity and source filters), `/anomalies/{id}` (detail with metric tiles, explanation, attention-weighted contributing lines, similar-incident retrieval, feedback buttons).
- **Feedback loop.** Engineer marks `true_positive` / `false_positive` from the detail page; the row is denormalised into the Feedback page and the Incidents page (true-positives only).
- **Admin pages.** `/admin/system` (drift gauge with synthetic-PSI banding 0.40 / 0.55, live service probes, queue depth, active models from training_runs); `/admin/training` (compact active-model card with 3-decimal saturated-aware metrics, run history with click-to-expand notes, retrain command); `/admin/incidents` (curated true-positive history filtered from feedback).
- **WebSocket live push.** Initial frame of newest anomaly + per-event push on the `anomalies:broadcast` channel.
- **CI.** GitHub Actions runs `ruff` lint, `mypy` (advisory), `pytest` against Postgres + Redis service containers, and frontend `tsc --noEmit` + `vite build`.

---

## 8. Planned but not yet done (explicit)

- **API key authentication** — backend has *no* auth middleware. All `/api/v1/*` endpoints are publicly reachable on `localhost`. Frontend Firebase auth gates the *frontend pages*, not the API. Adding `LOGGUARD_API_KEY` middleware is approximately 1 hour of work.
- **Notifications UI** — there is no in-app notifications panel. Severity-coloured rows on the dashboard are the current alerting surface.
- **Email / Slack / Teams / PagerDuty alerting** — `backend/api/alerting.py` does not exist. Severity is computed and stored on the anomaly row, but no outbound integration ships.
- **Persistent drift detector** — `drift_events` rows are never inserted by any runtime component. The System-page drift score is a synthetic proxy (std-dev of recent confidences, banded into healthy / drift_high / drift_critical at 0.40 / 0.55).
- **Per-model F1 / P / R storage in `training_runs`** — table only stores ensemble metrics. The Active Models card on `/admin/system` therefore shows the same row of numbers across Transformer / AutoEncoder / Confidence MLP, with an explicit caveat banner.
- **Real Filebeat / log-shipper ingestion** — referenced in early design notes; not implemented. The actual ingestion path is HTTP upload + URL fetch.
- **Container-registry push / CD step** — CI runs lint + tests + frontend build; there is no deploy step.

---

## 9. Tech stack — full list

### Backend (Python 3.11)

```
fastapi==0.115.4
uvicorn[standard]==0.32.0
pydantic==2.9.2
python-multipart==0.0.27
drain3==0.9.11
torch==2.5.1
sentence-transformers==3.3.1
numpy==1.26.4
scipy==1.14.1
scikit-learn==1.5.2
faiss-cpu==1.9.0
redis==5.2.0
asyncpg==0.30.0

# tooling (CI)
ruff==0.7.2
mypy==1.13.0
pytest==8.3.3
pytest-asyncio==0.24.0
httpx==0.27.2
fakeredis==2.26.1
```

### Frontend (TypeScript / React)

Runtime dependencies:
```
react              ^18.3.1
react-dom          ^18.3.1
react-router-dom   ^6.27.0
@tanstack/react-query ^5.59.0
recharts           ^2.13.0
date-fns           ^4.1.0
firebase           ^12.12.1
framer-motion      ^12.38.0
lucide-react       ^0.460.0
react-countup      ^6.5.3
react-intersection-observer ^10.0.3
```

Dev dependencies:
```
vite               ^5.4.8
@vitejs/plugin-react ^4.3.2
typescript         ^5.6.2
tailwindcss        ^3.4.13
postcss            ^8.4.47
autoprefixer       ^10.4.20
openapi-typescript ^7.4.0
@types/node        ^22.7.4
@types/react       ^18.3.11
@types/react-dom   ^18.3.0
```

### Infrastructure (Docker images)

| Service | Image | Purpose |
|---|---|---|
| Redis | `redis:7` | Streams + Pub/Sub + priority Set |
| Postgres | `postgres:16` | `anomalies`, `drift_events`, `training_runs` |
| Ollama | `ollama/ollama:latest` | Local LLaMA host |
| Backend (optional) | local `Dockerfile` | FastAPI app |

### LLaMA model

- **Default (GPU deployment):** `llama3:8b`
- **CPU dev / fallback:** `llama3.2:1b`
- Override: `LOGGUARD_LLAMA_HOST` (default `http://localhost:11434`), `LOGGUARD_LLAMA_MODEL`, `LOGGUARD_LLAMA_TIMEOUT_S` (default 900 s).
- Generation options used: `temperature=0.2`, `num_predict=200`, `keep_alive="5m"`, `stream=False`.

### CI

- GitHub Actions, two parallel jobs (`backend`, `frontend`) on every PR + push to `main`.
- Backend job spins up Postgres + Redis service containers, runs `ruff check`, `mypy` (advisory), `pytest`.
- Frontend job runs `npm run lint` (`tsc --noEmit`) + `vite build`.

### Deployment

- `docker-compose.yml` brings up Redis + Postgres + Ollama + (optional) backend container.
- Artifacts directory is **volume-mounted, never baked into images** — `.pt` files, `faiss.index`, `drain3_state.bin` live on the host filesystem (gitignored). CI does not build images for deploy.

---

## 10. Available figures on disk

**There are no PNG / SVG / PDF figures committed in this repository.** A search across all `*.png`, `*.svg`, `*.pdf`, `*.jpg`, `*.jpeg` files in the tree (excluding `node_modules`, `.git`, `.venv`) returns only:

- `frontend/dist/favicon.svg` — the LogGuard favicon (build artefact, regenerated by `vite build`; not a thesis figure).

For the thesis you will need to **author the diagrams from scratch** (or screenshot the live dashboard). Recommended set, with the canonical source for each:

| Figure | Source / how to produce it | Recommended use |
|---|---|---|
| **System architecture (six-layer)** | Use the table in §2 above. Draw left-to-right or top-to-bottom in draw.io / Mermaid / TikZ. | Methods chapter — overall pipeline diagram. |
| **Detection-ensemble block diagram** | Boxes for Drain3 → SBERT → (Transformer ‖ AutoEncoder) → ensemble combiner → Confidence MLP → severity. Hyperparameters in §3. | Methods chapter — ML model description. |
| **Sliding-window illustration** | 20-event window over a synthetic event sequence; arrow showing stride 1. | Methods chapter — sequence construction. |
| **F1 head-to-head bar chart** | Plot the table in §5.F1. Three groups (OpenStack / HDFS / Apache), two bars (Model A / B). Use `matplotlib`. | Results chapter — headline. |
| **AUC head-to-head bar chart** | Same shape from §5.AUC. | Results chapter — discussion of threshold-vs-ranking quality. |
| **Confusion matrices (Model B, OpenStack & HDFS)** | Numbers in `RESULTS_OPENSTACK_TEST.md` and `RESULTS_HDFS_TEST.md`. Plot as 2 × 2 heat-map. | Results chapter — appendix. |
| **Live dashboard screenshots** | Open `/dashboard`, `/anomalies/{id}`, `/admin/system`, `/admin/training`, `/admin/incidents` on `localhost:5173`. | Results / system-walkthrough chapter. |
| **RAG prompt + response example** | Run a click on a real anomaly; copy the resulting `root_cause` + `recommended_fix` from the explanation card. | RAG-design chapter — qualitative example. |

The Markdown tables in `backend/artifacts_proper/RESULTS_*.md` are paste-ready for any of the headline numbers above.
