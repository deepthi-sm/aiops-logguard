"""
Pre-generate LLaMA explanations for the demo stream's template pool.

Run once. Output goes to `backend/artifacts/precomputed_explanations.json`.
The RAG worker loads it at startup and uses it as a fast-path lookup:
when an anomaly's `log_template` SBERT-embeds within cosine ≥ 0.85 of
a precomputed entry, the cached explanation is written to Postgres
immediately — no LLaMA call. Cache miss falls back to live LLaMA at
~30 s/call.

Why this is needed: `llama3.2:1b` on CPU is the fastest model that
produces useable RAG output here, and even that costs ~30 s per call.
For the demo, we want clicked anomalies explained in <2 s. The demo
stream uses a *fixed* template pool of 17 entries (see
`api.demo_stream.TEMPLATES`) — pre-compute once, ship the artifact,
~99% of clicked anomalies are sub-second after that.

Usage:
    cd backend
    KMP_DUPLICATE_LIB_OK=TRUE PYTHONIOENCODING=utf-8 \\
      LOGGUARD_LLAMA_MODEL=llama3.2:1b \\
      python -m scripts.precompute_demo_explanations

Approx wall-clock: 17 templates × ~30 s/each ≈ 8-10 minutes, plus
SBERT + FAISS load time (~5 s).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Make `from api.demo_stream import ...` resolvable whether invoked
# as `python -m scripts.precompute_demo_explanations` (preferred) or
# `python scripts/precompute_demo_explanations.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np  # noqa: E402

from api.demo_stream import TEMPLATES  # noqa: E402
from ml.embedder import load_default_sbert  # noqa: E402
from rag.faiss_client import (  # noqa: E402
    DEFAULT_INDEX_PATH,
    FaissClient,
)
from rag.llama_client import OllamaClient  # noqa: E402
from rag.prompts import SYSTEM_PROMPT, build_user_prompt, parse_response  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("precompute")

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
OUT_PATH = ARTIFACTS_DIR / "precomputed_explanations.json"
TOP_K_FOR_PRECOMPUTE = 3  # richer than the live path (which uses 1)


def _representative_event(template_idx: int) -> dict[str, str]:
    """Build one fully-formed (no placeholder) event for the given
    template. Deterministic — same index always produces the same line.

    These concrete examples feed into the LLaMA prompt so the cached
    explanation talks about a real-looking event rather than placeholder
    syntax. The cache *match* at runtime uses the raw template pattern
    (with placeholders), not these concrete fillers."""
    template, source_pool, _ = TEMPLATES[template_idx]
    source = source_pool[0]  # deterministic
    raw = template.format(
        host=source_pool[0],
        ip="10.0.1.42",
        hex="deadbeef",
        n=12345,
        n2=42,
        temp=85,
        pid=4096,
        uuid="00000000-0000-4000-8000-000000000001",
        user="alice",
    )
    return {"source": source, "line": raw, "template": template}


def _embed_one(sbert, text: str) -> np.ndarray:
    """SBERT-embed a single string, normalised. Returns (384,) float32."""
    out = sbert.encode(
        [text],
        batch_size=1,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    arr = np.asarray(out, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(arr))
    if n > 1e-9:
        arr = arr / n
    return arr.astype(np.float32)


async def _generate_one(
    *,
    sbert,
    faiss: FaissClient,
    llama: OllamaClient,
    template_idx: int,
) -> dict:
    ev = _representative_event(template_idx)

    # Embed the CONCRETE example line, not the raw `{host}`/`{ip}`
    # pattern. Empirically, SBERT sees `{host}` as a literal token
    # and produces embeddings that don't match the runtime Drain3
    # form (where `{host}` becomes the actual host string and `{ip}`
    # becomes `<IP>`). With concrete fillers, cosine similarity to
    # runtime templates is consistently > 0.83 — see the v1→v2
    # cache rebuild for the empirical numbers. (cache schema v2)
    cache_key_text = ev["line"]
    cache_emb = _embed_one(sbert, cache_key_text)

    # FAISS query — uses the same embedding so we can reuse it.
    retrieved = faiss.query(cache_emb.reshape(1, -1).astype(np.float32), k=TOP_K_FOR_PRECOMPUTE)

    # The RAG prompt expects a Drain3-style log_template, a sequence
    # preview, a source string, and the FAISS hits. We use the raw
    # pattern as the "template" so LLaMA writes about the canonical
    # form, and a tiny synthetic sequence preview so the prompt has
    # context.
    user_prompt = build_user_prompt(
        log_template=ev["template"],
        sequence_preview=[ev["line"]] * 5,
        source=ev["source"],
        similar=retrieved,
    )

    log.info("template %d/%d: %s", template_idx + 1, len(TEMPLATES), ev["template"][:80])
    raw = await llama.generate(system=SYSTEM_PROMPT, user=user_prompt)
    parsed = parse_response(raw)

    similar_serialised = [
        {
            "incident_id": hit.record.incident_id,
            "template": hit.record.template,
            "resolved_at": hit.record.resolved_at,
            "similarity_score": float(hit.similarity),
        }
        for hit in retrieved
    ]

    return {
        "template_pattern": ev["template"],
        "example_line": ev["line"],
        "source_family_hint": ev["source"],
        "embedding": cache_emb.tolist(),
        "root_cause": parsed.root_cause,
        "recommended_fix": parsed.recommended_fix,
        "similar_incidents": similar_serialised,
    }


async def main() -> int:
    log.info("loading SBERT (sentence-transformers/all-MiniLM-L6-v2)...")
    sbert = load_default_sbert()

    log.info("loading FAISS from %s ...", DEFAULT_INDEX_PATH)
    faiss = FaissClient.from_artifacts()

    log.info("connecting to Ollama (model from LOGGUARD_LLAMA_MODEL)...")
    llama = OllamaClient()
    if not await llama.ping():
        log.error("Ollama ping failed — is it running on %s?", llama.base_url)
        await llama.aclose()
        return 1

    log.info("model=%s — generating %d cache entries...", llama.model, len(TEMPLATES))

    entries = []
    try:
        for i in range(len(TEMPLATES)):
            entry = await _generate_one(
                sbert=sbert, faiss=faiss, llama=llama, template_idx=i,
            )
            entries.append(entry)
    finally:
        await llama.aclose()

    payload = {
        "version": 2,
        "model": llama.model,
        "embedding_dim": len(entries[0]["embedding"]) if entries else 384,
        "match_threshold": 0.80,
        "embedding_source": "example_line",
        "entries": entries,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))
    log.info("[done] wrote %d entries to %s", len(entries), OUT_PATH)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
