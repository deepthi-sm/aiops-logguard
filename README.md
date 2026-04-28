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

## Team

3-person academic project, Phase 1 Review 3.

- Backend & ML: [Person A]
- Frontend: [Person B]
- Documentation: [Person C]

## License

(TBD — pick one before publishing)
