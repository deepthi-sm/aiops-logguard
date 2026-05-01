# System Overview — Six-Layer Architecture

This is the full technical walkthrough of AIOps-LogGuard. Read CLAUDE.md first for the high-level picture and integration contract; this doc explains how each layer actually works.

## Layer 1 — Log sources

The system accepts logs from four types of sources simultaneously:
- Application servers (Java, Python, Node — all different formats)
- Containers running on Kubernetes
- CI/CD pipeline output
- Databases and microservices

Logs are pushed into **Redis Streams** as the entry point. Redis Streams act as a burst buffer: if 100,000 log lines arrive in one second during a traffic spike, Redis holds them in order so nothing is dropped and the AI pipeline isn't overwhelmed. This is the production-grade detail that separates this from a toy demo.

**Stream name:** `logs:raw`
**Format:** each entry is a single log line as `{ "source": "<hostname>", "line": "<raw text>", "ingested_at": "<iso>" }`

## Layer 2 — Ingestion + preprocessing

Raw log lines are messy. Example:

```
2024-01-15 14:32:11 ERROR blk_-1234567890 NameNode connection refused from 192.168.1.45
```

The block ID and IP are different every time. If the model treats them as meaningful tokens, it never generalises. So this layer strips them out.

### Drain3 (template extraction)

Drain3 is a well-known log parsing library that extracts the stable part of a log line. The above becomes:

```
ERROR blk_* NameNode connection refused from *
```

Now the model recognises this pattern regardless of which block ID or IP appears.

**Critical detail:** Drain3 builds a tree of templates as it sees logs. We persist this tree to `artifacts/drain3_state.bin` during training and **load the exact same file at inference time**. If templates differ between training and inference, the whole pipeline silently degrades.

### Normalisation (after Drain3)

Strip these patterns regardless of what Drain3 left in:
- Timestamps (multiple formats)
- IPs (regex)
- Block IDs (`blk_-?\d+`)
- UUIDs
- Hex addresses
- Email addresses
- File paths beyond a depth (replace with `*`)

### Sequence builder

Single log lines lack context. A single "connection refused" isn't an emergency, but 15 of them followed by 3 "memory pressure" events followed by 2 "retry failed" events absolutely is.

So the sequence builder groups **20 consecutive log events per source** into one window, then slides forward by 1 (stride=1). Each window becomes the unit of analysis from here on.

**Important:** the sequence builder logic must be **identical** between `backend/training/sequence_builder.py` and `backend/ingestion/sequence_builder.py`. Implement it once in a shared module and import from both. Drift here causes silent training/inference mismatch.

## Layer 3 — Vectorization

Computers can't operate on text — everything becomes numbers.

### SBERT (primary)

`sentence-transformers` with `all-MiniLM-L6-v2` (384-d, fast, good enough for prototype) — upgrade path to `all-mpnet-base-v2` (768-d, slower, better) for the final paper.

**Embedding strategy:** one vector per **window**, not per line. Concatenate the 20 templates in the window with `[SEP]` as a separator and embed the whole thing. This captures sequence context.

**Performance note:** re-embedding 10M sequences is the slowest step in the project. Cache embeddings to `artifacts/embeddings_hdfs.npy` and never recompute unless source data changes.

### TF-IDF (baseline only)

`sklearn.TfidfVectorizer` saved to `artifacts/tfidf.npz`. This is **not used in production** — it exists so the paper has a baseline to compare against. The paper claim is "SBERT outperforms TF-IDF on this task by X% F1," and you need TF-IDF numbers to make that claim.

## Layer 4 — Anomaly detection + failure prediction

This is the brain. Three sub-layers.

### Sub-layer 4a — Models (run in parallel)

**Transformer encoder** (`backend/ml/transformer.py`):
- 4 layers, 8 attention heads, 256-d hidden, dropout 0.1
- Self-attention looks at every event in the 20-event window in relation to every other event — not just sequential neighbours
- **Two output heads:**
  - Anomaly classifier — binary cross-entropy, outputs anomaly score in [0,1]
  - Failure-window regressor — predicts minutes-to-failure if the window leads to a failure
- **Saves attention weights from the last layer at inference.** The frontend renders these as the per-line attention scores in `top_contributing_lines`.
- Trained with AdamW, lr=2e-4, cosine schedule, 30 epochs, early stop on validation F1
- Saved as TorchScript: `artifacts/transformer.pt`

**AutoEncoder** (`backend/ml/autoencoder.py`):
- Symmetric encoder → bottleneck (64-d) → decoder
- MSE reconstruction loss
- **Trained only on normal sequences.** The whole point: it learns to reconstruct normal logs perfectly, so anomalous sequences produce high reconstruction error.
- Saved as TorchScript: `artifacts/autoencoder.pt`

**Why two models?** They fail in different ways. The Transformer captures sequence patterns; the AutoEncoder captures distributional drift. An anomaly that fools one usually doesn't fool both. The ensemble compensates for each model's weaknesses.

### Sub-layer 4b — Scoring

**Weighted ensemble** (`backend/ml/ensemble.py`):
```
combined_score = w1 * transformer_score + w2 * autoencoder_error
```
`w1` and `w2` are tuned on the validation set during training (grid search optimising F1). Stored in `artifacts/thresholds.json`.

**Confidence scorer:** a small MLP that takes `(transformer_score, ae_error, sequence_length, time_of_day)` and outputs a confidence in [0,1]. It's trained on a held-out set with labels = "did this prediction match ground truth?". This is what stops the system from firing alerts on borderline cases — only confident anomalies get through.

### Sub-layer 4c — Decision

Three steps in `backend/ml/postprocess.py`:

1. **Thresholding** — binary yes/no based on `combined_score > anomaly_threshold` AND `confidence > confidence_threshold`.
2. **Deduplication** — cluster anomalies by `(template_hash, source, 60-second window)` so the same problem doesn't generate 500 separate tickets. Same `cluster_id` if matched, increment `cluster_size`.
3. **Severity scoring** — three rules, applied in order:
   - `failure_probability > 0.75` AND source is in critical set → `critical`
   - `ensemble_score > 0.85` → `warning`
   - else → `info`

   **The critical-source set.** Rule 1 only fires when `source` matches a configured set of "critical infrastructure" hostnames. The set is resolved at runtime by `backend/ml/postprocess.get_critical_sources()`, with this priority:
   1. The `LOGGUARD_CRITICAL_SOURCES` env var (comma-separated hostnames) — this is the production hook for ops to declare "these specific services pager me at 3am."
   2. A demo default baked into `DEFAULT_CRITICAL_SOURCES`: `nova-api-prod-3`, `neutron-server-1`, `glance-api-2`, `keystone-api-2`, `namenode-prod-1`. Names cover one host per infrastructure pillar — compute (nova), networking (neutron), images (glance), auth (keystone), storage (HDFS namenode) — and align with the OpenStack training corpus and the frontend mock fixtures so the live demo and the dashboard's seeded data tell a coherent story.

   Why ship a non-empty default? An empty set means rule 1 can never fire, so the entire critical tier silently drops to `warning`. That breaks the demo — and worse, it would silently break production deployments where someone forgot to set the env var. The default is small enough that real deployments will always override, but large enough that the demo behaves correctly out of the box.

   **Contract with `tools/log_replay.py` (Step 8).** The replayer must emit `source` field values from this default set on a sufficient fraction of replayed lines so the critical branch actually exercises. The unit test `test_postprocess.TestGetCriticalSources::test_default_includes_every_log_replay_source` pins the list here so any future drift between the default and the replayer's emitted hostnames trips CI.

Plus a **drift detector** (`backend/ml/drift.py`) running on a separate timer:
- Maintains a rolling buffer of recent embeddings (last 10k windows)
- Hourly, computes Population Stability Index (PSI) between buffer mean and training mean
- PSI > 0.25 → log `drift_high` event
- PSI > 0.4 → emit a retrain trigger event (does NOT retrain inline)

## Layer 5 — RAG + LLaMA root cause analysis

This is what makes the project different from standard AIOps work. Detecting an anomaly is one thing. Explaining it in plain English with a recommended fix is another.

**RAG = Retrieval-Augmented Generation.** The flow:

1. New anomaly is detected → its embedding is computed
2. FAISS index returns top-K (K=5) most similar past incidents — each with metadata `{ incident_id, template, root_cause_text, recommended_fix, resolved_at }`
3. Current anomaly + retrieved incidents are formatted into a prompt
4. Local LLaMA 3 8B (via Ollama) generates a structured JSON response with `root_cause`, `recommended_fix`, `similar_incident_ids`
5. Response is parsed and written to Postgres; `explanation_status` flips to `ready`

**Why local LLaMA?** Privacy. Log data often contains PII or proprietary system info. Sending it to OpenAI is a non-starter for most enterprises. Local LLaMA via Ollama means **no log data ever leaves the system**. This is a key paper claim.

**Why a separate worker process?** LLaMA inference is slow (1–10 seconds per call). If it ran inline in the detection path, detection would block. Instead, the worker subscribes to Redis stream `anomalies:detected`, processes asynchronously, and updates Postgres when done. The frontend polls or refreshes to see `explanation_status` change from `pending` to `ready`.

**Caching:** LRU cache on `(template_hash, top5_ids_hash)`. The same incident pattern shouldn't hit LLaMA twice. This is the single biggest performance win.

**FAISS seeding:** at training time, seed the index with:
- Labelled HDFS anomalies (with synthesised root cause text)
- 20–30 hand-written synthetic incidents covering common patterns: connection pool exhaustion, disk full, OOM, network partition, certificate expiry, DNS failure, etc.

Without this seeding, LLaMA has nothing to retrieve and produces vague output. The hand-written incidents are what make the demo look impressive.

See `docs/architecture/rag_design.md` for the full prompt template and example outputs.

## Layer 6 — Output + alerting

Outputs are routed by severity:

- `critical` → **PagerDuty Events API** (wakes someone at 3am)
- `warning` → **Slack incoming webhook** (team sees it in the morning)
- `info` → **SMTP email** (informational, full LLaMA explanation included)

All three integrations live behind feature flags so dev/staging runs without real API keys.

The dashboard (`frontend/`, owned by Person B) shows everything live:
- Anomaly timeline
- Severity distribution
- Per-anomaly attention heatmap (using `top_contributing_lines`)
- LLaMA explanation
- Engineer feedback buttons (true/false positive)

Engineer feedback flows back via `POST /api/v1/anomalies/{id}/feedback` and is stored on the anomaly row. This builds the labelled dataset for the next retrain cycle — closing the human-in-the-loop story for the paper.

## End-to-end timing

For a single log line during normal operation:

1. Line hits Redis Streams (~1ms)
2. Consumer batches and parses with Drain3 (~5ms per batch of 200)
3. Sequence builder waits until the per-source window fills (variable, depends on log rate)
4. SBERT embedding (~50ms per window on CPU, ~5ms on GPU)
5. Transformer + AutoEncoder forward pass (~20ms)
6. Ensemble + confidence + threshold (~1ms)
7. If anomaly: Postgres insert + websocket broadcast (~10ms)
8. RAG worker picks it up async (separate timeline, 1–10 seconds for LLaMA)

Detection-to-dashboard latency target: **under 1 second**. LLaMA explanation latency target: **under 30 seconds**.
