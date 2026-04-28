# RAG + LLaMA Design

The Retrieval-Augmented Generation worker turns raw anomaly scores into human-readable root cause explanations. This is what makes the project genuinely novel for the paper.

## High-level flow

```
[Postgres anomaly row inserted, explanation_status='pending']
       ↓
   [Redis stream `anomalies:detected` gets the new ID]
       ↓
   [RAG worker process picks it up]
       ↓
   1. Load anomaly + sequence preview from Postgres
   2. Embed log_template with SBERT
   3. FAISS top-K (K=5) retrieval → similar past incidents
   4. Build prompt with anomaly + retrieved incidents
   5. Call Ollama (LLaMA 3 8B local) with the prompt
   6. Parse JSON response (fall back to plain text on parse failure)
   7. UPDATE anomalies SET root_cause=..., recommended_fix=..., similar_incidents=..., explanation_status='ready'
   8. Broadcast `explanation_ready` event on websocket
```

## Why a separate worker process

LLaMA inference is slow — 1 to 10 seconds per call depending on prompt length. If it ran inline in the detection path, detection latency would explode. So the RAG worker is a **separate process** subscribed to a Redis stream, processing anomalies asynchronously.

The frontend handles this gracefully:
- Initial anomaly arrives via websocket with `explanation_status: "pending"` → frontend shows a spinner
- RAG worker finishes → broadcasts `explanation_ready` event → frontend re-fetches and shows the explanation

## Files

```
backend/rag/
├── explainer.py          # main worker loop
├── prompts.py            # prompt templates
└── faiss_client.py       # wraps faiss.index + incidents.jsonl
```

## FAISS retrieval (`faiss_client.py`)

```python
import faiss
import json
from sentence_transformers import SentenceTransformer

class FaissClient:
    def __init__(self, index_path: str, incidents_path: str):
        self.index = faiss.read_index(index_path)
        with open(incidents_path) as f:
            self.incidents = [json.loads(line) for line in f]
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

    def retrieve(self, query_template: str, k: int = 5) -> list[dict]:
        query_vec = self.embedder.encode([query_template], normalize_embeddings=True)
        scores, indices = self.index.search(query_vec, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            inc = dict(self.incidents[idx])
            inc["similarity_score"] = float(score)
            results.append(inc)
        return results
```

`IndexFlatIP` does inner product. With normalised vectors, that's cosine similarity. Fine up to ~1M indexed vectors. If you ever exceed that, switch to `IndexIVFPQ`.

## Prompt template (`prompts.py`)

```python
SYSTEM_PROMPT = """You are a senior site reliability engineer analysing log anomalies.
Your job is to identify the root cause and recommend a fix.
Respond ONLY with valid JSON matching the schema given. No preamble, no markdown.
"""

USER_PROMPT_TEMPLATE = """Current anomaly:
- Source: {source}
- Severity: {severity}
- Log template: {template}
- Ensemble score: {ensemble_score:.2f}
- Failure probability: {failure_probability:.2f}
- Sequence preview (last 20 events):
{sequence_preview}

Similar past incidents (retrieved from incident database):
{retrieved_incidents}

Respond in this exact JSON schema:
{{
  "root_cause": "1-2 sentence explanation of what is likely wrong",
  "recommended_fix": "1-3 numbered actionable steps",
  "similar_incident_ids": ["list", "of", "incident_ids", "from", "above"]
}}"""

def format_retrieved_incidents(incidents: list[dict]) -> str:
    parts = []
    for i, inc in enumerate(incidents, 1):
        parts.append(
            f"{i}. [{inc['incident_id']}] (similarity: {inc['similarity_score']:.2f})\n"
            f"   Template: {inc['template']}\n"
            f"   Root cause: {inc['root_cause_text']}\n"
            f"   Fix: {inc['recommended_fix']}\n"
        )
    return "\n".join(parts)
```

## Ollama call

```python
import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3:8b"

async def call_llama(prompt: str, system: str) -> str:
    payload = {
        "model": MODEL,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,    # low — we want deterministic, factual output
            "num_ctx": 4096,       # context window
            "num_predict": 512,    # max output tokens
        },
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(OLLAMA_URL, json=payload)
        r.raise_for_status()
        return r.json()["response"]
```

## Parsing the response

LLaMA sometimes wraps JSON in markdown code blocks or adds preamble despite instructions. Handle both:

```python
import json
import re

def parse_llama_response(raw: str) -> dict:
    # Strip markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)

    # Find first { and last }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < 0:
        return _fallback(raw)

    try:
        parsed = json.loads(cleaned[start:end+1])
        return {
            "root_cause": parsed.get("root_cause", ""),
            "recommended_fix": parsed.get("recommended_fix", ""),
            "similar_incident_ids": parsed.get("similar_incident_ids", []),
        }
    except json.JSONDecodeError:
        return _fallback(raw)

def _fallback(raw: str) -> dict:
    """If LLaMA didn't produce valid JSON, return the raw text as the explanation."""
    return {
        "root_cause": raw[:500],
        "recommended_fix": "(LLaMA response was malformed — review raw output)",
        "similar_incident_ids": [],
    }
```

## Caching (the biggest performance win)

```python
from functools import lru_cache
import hashlib

def _cache_key(template: str, retrieved_ids: list[str]) -> str:
    h = hashlib.sha256()
    h.update(template.encode())
    for rid in sorted(retrieved_ids):
        h.update(rid.encode())
    return h.hexdigest()

# In production use Redis or a persistent cache, not lru_cache
# (lru_cache is per-process and lost on restart)
```

The same anomaly pattern shouldn't hit LLaMA twice. With dedup at Layer 4, most clusters share a template, so cache hit rate should exceed 80% in steady state.

## Worker loop skeleton

```python
async def run_worker():
    redis = await create_redis_pool()
    pg = await create_pg_pool()
    faiss_client = FaissClient("artifacts/faiss.index", "artifacts/incidents.jsonl")
    cache = ExplanationCache(redis)

    consumer_group = "rag-explainer"
    stream = "anomalies:detected"

    async for entry in consume_stream(redis, stream, consumer_group):
        anomaly_id = entry["anomaly_id"]
        try:
            await process_one(anomaly_id, pg, faiss_client, cache)
            await redis.xack(stream, consumer_group, entry["id"])
        except Exception:
            logger.exception("RAG worker failed for %s", anomaly_id)
            # Mark as failed, don't ack — let it retry or move to DLQ
            await pg.execute(
                "UPDATE anomalies SET explanation_status='failed' WHERE id=$1",
                anomaly_id,
            )

async def process_one(anomaly_id, pg, faiss_client, cache):
    anomaly = await pg.fetchrow("SELECT * FROM anomalies WHERE id=$1", anomaly_id)
    retrieved = faiss_client.retrieve(anomaly["log_template"], k=5)

    cache_key = _cache_key(anomaly["log_template"], [r["incident_id"] for r in retrieved])
    cached = await cache.get(cache_key)
    if cached:
        explanation = cached
    else:
        prompt = USER_PROMPT_TEMPLATE.format(
            source=anomaly["source"],
            severity=anomaly["severity"],
            template=anomaly["log_template"],
            ensemble_score=anomaly["ensemble_score"],
            failure_probability=anomaly["failure_probability"],
            sequence_preview="\n".join(anomaly["sequence_preview"]),
            retrieved_incidents=format_retrieved_incidents(retrieved),
        )
        raw = await call_llama(prompt, SYSTEM_PROMPT)
        explanation = parse_llama_response(raw)
        await cache.set(cache_key, explanation, ttl=86400)

    await pg.execute(
        """UPDATE anomalies
           SET root_cause=$1, recommended_fix=$2,
               similar_incidents=$3, explanation_status='ready'
           WHERE id=$4""",
        explanation["root_cause"],
        explanation["recommended_fix"],
        json.dumps(retrieved),
        anomaly_id,
    )

    # Broadcast websocket event
    await redis.publish("anomalies:broadcast", json.dumps({
        "type": "explanation_ready",
        "data": {"anomaly_id": anomaly_id, "explanation_status": "ready"},
    }))
```

## Example output

For an anomaly with template `ERROR blk_* NameNode connection refused from *`:

```json
{
  "root_cause": "The NameNode service is rejecting connections from data nodes, suggesting the connection pool has reached its configured limit. Pattern matches incident syn_001 (connection pool exhaustion).",
  "recommended_fix": "1. Check NameNode connection pool config (`dfs.namenode.handler.count`) and current active connection count\n2. Investigate any data node behaviour that could be holding connections open (slow block reports, network partition)\n3. If pool is saturated, restart the NameNode service after capturing a thread dump for post-mortem",
  "similar_incident_ids": ["syn_001", "inc_247"]
}
```

## Failure modes to handle

- **Ollama down** → `explanation_status='failed'`, surface error in UI, don't crash worker
- **LLaMA produces non-JSON** → fall back to raw text in `root_cause`, mark fix as malformed
- **FAISS returns 0 results** → still call LLaMA but with empty retrieved_incidents block. Output will be vaguer but usable.
- **Worker crash mid-process** → don't ack the stream entry; on restart it'll be redelivered. Idempotent updates by `anomaly_id` mean reprocessing is safe.
