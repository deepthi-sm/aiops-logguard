# AIOps-LogGuard

AI-powered log anomaly detection with RAG-based root cause analysis.

A real-time system that watches server logs, uses an ensemble of a Transformer encoder and AutoEncoder to detect anomalies before they cause failures, and uses a local LLaMA 3 model with FAISS-based retrieval over past incidents to produce human-readable root cause explanations and recommended fixes.

## What makes it different

Most prior log-anomaly systems do one of: anomaly detection, failure prediction, uncertainty quantification, or explainability. This one does all four in a single pipeline, plus RAG-based natural-language root cause and severity-routed alerting.

## Architecture

Six layers, three pipelines. See `docs/architecture/system_overview.md` for the full walkthrough.

```
Layer 1 — Log sources       → Redis Streams (burst buffer)
Layer 2 — Ingestion         → Drain3 templates + sliding-window sequences
Layer 3 — Vectorization     → SBERT embeddings (TF-IDF baseline)
Layer 4 — Detection         → Transformer + AutoEncoder ensemble + confidence + drift
Layer 5 — RAG explanation   → FAISS retrieval + local LLaMA 3 8B via Ollama
Layer 6 — Alerting          → PagerDuty / Slack / email by severity
```

## Quick start

```bash
# bring up Redis, Postgres, Ollama
docker-compose up -d

# train models (Pipeline 2) — runs once, produces all artifacts
cd backend
python -m training.run_full_pipeline --dataset hdfs

# start the live system (Pipeline 1)
docker-compose up backend rag-worker

# in another terminal: replay logs to drive the demo
python tools/log_replay.py training/data/hdfs/HDFS.log --rate 100 --inject-anomaly

# frontend
cd ../frontend
npm install
npm run dev   # http://localhost:5173
```

## Repo layout

```
aiops-logguard/
├── backend/        # FastAPI + ML + RAG worker + training pipeline
├── frontend/       # React + Vite + TypeScript dashboard
├── docs/           # Architecture, paper, report, diagrams
├── docker-compose.yml
└── .github/workflows/
```

## Documentation

- **Architecture:** `docs/architecture/system_overview.md`
- **Pipelines:** `docs/architecture/pipelines.md`
- **API contract:** `docs/architecture/api_contract.md`
- **Training:** `docs/architecture/training_pipeline.md`
- **RAG design:** `docs/architecture/rag_design.md`
- **For Claude Code agents:** `CLAUDE.md`

## LLaMA / GPU deployment

The RAG worker calls Ollama on every detected anomaly — no precomputed
cache short-circuit. Per-call latency is bounded by model + hardware:

| Model         | CPU         | GPU       |
| ------------- | ----------- | --------- |
| `llama3.2:1b` | ~15-30 s    | ~1-2 s    |
| `llama3:8b`   | ~60-180 s   | ~3-5 s    |

For the demo we point the worker at a GPU-hosted Ollama and run
`llama3:8b` for postmortem-quality output. For local CPU dev we
fall back to `llama3.2:1b`.

Two env vars on the RAG worker (and on the precompute scripts) control
this:

```bash
# Default — talk to the docker-compose Ollama on this machine.
LOGGUARD_LLAMA_HOST=http://localhost:11434
LOGGUARD_LLAMA_MODEL=llama3:8b

# CPU-only laptop dev — switch to the smaller model.
LOGGUARD_LLAMA_MODEL=llama3.2:1b

# Remote GPU deployment — point at the GPU box's Ollama.
LOGGUARD_LLAMA_HOST=http://gpu-box.example:11434
LOGGUARD_LLAMA_MODEL=llama3:8b
```

The remote Ollama needs to be reachable from the RAG worker over HTTP
(port 11434 by default) and have the requested model already pulled
(`ollama pull llama3:8b` on the GPU box).

`LOGGUARD_LLAMA_TIMEOUT_S` (default 300) bounds individual call time.
Tighten for GPU runs if you want faster failure detection on a hung
remote.

## Team

3-person academic project, Phase 1 Review 3.

- Backend & ML: [Person A]
- Frontend: [Person B]
- Documentation: [Person C]

## License

(TBD — pick one before publishing)
