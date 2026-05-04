"""
Extend `precomputed_explanations.json` with templates harvested from
real LogHub-style sample files (BGL, Thunderbird, Apache, HDFS,
OpenStack) — so file-upload demos hit the cache too, not just the
synthetic /demo/stream URL flow.

Why this exists: the original precompute (scripts/precompute_demo_explanations.py)
covers only the 17 synthetic templates the /demo/stream endpoint
emits. Real LogHub uploads have a completely different vocabulary
("- 1122144024 2005.07.23 R24-M1-N2-C ..." vs the synthetic
"FATAL {host} ciod: Error reading from {ip}: ..."). SBERT cosine
between the two is ~0.25, well below the 0.80 cache threshold —
every upload click would hit live LLaMA at ~17s/each.

This script:
  1. Reads up to 500 lines from each sample file in training/data/
  2. Runs each line through the same Drain3 parser the live
     ingestion uses (artifacts/drain3_state.bin) — produces
     normalized template strings byte-identical to what the runtime
     anomaly's `log_template` field will hold
  3. Deduplicates: many lines collapse to the same template
  4. Caps at TEMPLATES_PER_DATASET unique templates per dataset
  5. For each new template, embeds via SBERT, runs FAISS top-3,
     calls LLaMA (~17s on 1b), parses, appends to the cache JSON

Run once after the initial precompute_demo_explanations.py:
    cd backend
    KMP_DUPLICATE_LIB_OK=TRUE PYTHONIOENCODING=utf-8 \\
      LOGGUARD_LLAMA_MODEL=llama3.2:1b \\
      python -m scripts.extend_cache_with_uploads

Approx wall-clock: 5 datasets × ~5 templates × ~17s = ~7 min, plus
~5s for SBERT/FAISS/Drain3 startup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np  # noqa: E402

from ingestion.parser import LogParser  # noqa: E402
from ml.embedder import load_default_sbert  # noqa: E402
from rag.faiss_client import FaissClient  # noqa: E402
from rag.llama_client import OllamaClient  # noqa: E402
from rag.prompts import SYSTEM_PROMPT, build_user_prompt, parse_response  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("extend_cache")

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"
DATA_DIR = Path(__file__).resolve().parent.parent / "training" / "data"
CACHE_PATH = ARTIFACTS_DIR / "precomputed_explanations.json"
DRAIN3_STATE = ARTIFACTS_DIR / "drain3_state.bin"

# Cap how much we ingest per file. Goal isn't full coverage — just the
# most common templates so the demo's first ~80% of windows hit cache.
#
# Bumped from (500, 5) to (2000, 20) after a smoke test on BGL showed
# only 41% hit rate — BGL has 12+ distinct templates in the first 2000
# lines (core configuration register, data storage interrupt, generating
# core.N, instruction cache parity error, double-hummer alignment
# exceptions, NodeCard not fully functional, etc.) and the first-5 cap
# missed most of them. With the dedup-on-rerun logic, this is safe to
# re-run any time without re-LLM-generating already-cached entries.
LINES_PER_FILE = 2000
TEMPLATES_PER_DATASET = 20
TOP_K_FOR_PRECOMPUTE = 3

# (dataset_label, file_path, source_string_used_at_runtime)
# `source_string` matches what the upload flow tags (filename stem
# lowercased+sanitized) so the cached entry's `source_family_hint` is
# accurate. Caller doesn't actually use that field for matching, just
# for human-readable logging.
DATASETS: list[tuple[str, Path, str]] = [
    ("BGL",         DATA_DIR / "bgl"         / "BGL_2k.log",         "bgl-2k"),
    ("Thunderbird", DATA_DIR / "thunderbird" / "Thunderbird_2k.log", "thunderbird-2k"),
    ("Apache",      DATA_DIR / "apache"      / "Apache.sample-1000.log", "apache-1000"),
    ("HDFS",        DATA_DIR / "hdfs"        / "HDFS.sample-200.log",   "hdfs-200"),
    ("OpenStack",   DATA_DIR / "openstack"   / "openstack_abnormal.sample-500.log", "openstack-abnormal"),
]


def _embed_one(sbert, text: str) -> np.ndarray:
    out = sbert.encode([text], batch_size=1, normalize_embeddings=True, show_progress_bar=False)
    arr = np.asarray(out, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(arr))
    if n > 1e-9:
        arr = arr / n
    return arr.astype(np.float32)


def _extract_templates(parser: LogParser, file: Path) -> list[tuple[str, str]]:
    """Run the first LINES_PER_FILE non-blank lines through Drain3.
    Return up to TEMPLATES_PER_DATASET `(normalized_template, example_raw_line)`
    tuples — deduplicated, in first-seen order so common templates
    surface first."""
    seen: dict[str, str] = {}  # template -> first raw line that produced it
    with file.open("r", encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f):
            if i >= LINES_PER_FILE:
                break
            line = raw.strip()
            if not line:
                continue
            parsed = parser.parse(line, source="precompute-extend")
            tmpl = parsed.template
            if tmpl not in seen:
                seen[tmpl] = line
                if len(seen) >= TEMPLATES_PER_DATASET:
                    break
    return list(seen.items())


async def _generate_one(
    *,
    sbert,
    faiss: FaissClient,
    llama: OllamaClient,
    template: str,
    example_line: str,
    source_family: str,
    dataset_label: str,
) -> dict:
    # Embed the EXAMPLE LINE (concrete, post-Drain3 form) — same key as
    # the v2 cache uses, so all entries are searched the same way.
    cache_emb = _embed_one(sbert, example_line)
    retrieved = faiss.query(cache_emb.reshape(1, -1).astype(np.float32), k=TOP_K_FOR_PRECOMPUTE)
    user_prompt = build_user_prompt(
        log_template=template,
        sequence_preview=[example_line] * 5,
        source=source_family,
        similar=retrieved,
    )
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
        "template_pattern": template,
        "example_line": example_line,
        "source_family_hint": source_family,
        "dataset": dataset_label,
        "embedding": cache_emb.tolist(),
        "root_cause": parsed.root_cause,
        "recommended_fix": parsed.recommended_fix,
        "similar_incidents": similar_serialised,
    }


async def main() -> int:
    if not CACHE_PATH.exists():
        log.error("cache file %s missing — run precompute_demo_explanations first", CACHE_PATH)
        return 1
    if not DRAIN3_STATE.exists():
        log.error("drain3 state %s missing — train pipeline must have produced it", DRAIN3_STATE)
        return 1

    log.info("loading existing cache from %s ...", CACHE_PATH)
    payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    existing_count = len(payload.get("entries", []))
    existing_templates = {e["template_pattern"] for e in payload["entries"]}
    log.info("  existing entries: %d", existing_count)

    log.info("loading SBERT ...")
    sbert = load_default_sbert()

    log.info("loading FAISS ...")
    faiss = FaissClient.from_artifacts()

    log.info("loading Drain3 parser from %s ...", DRAIN3_STATE)
    parser = LogParser(DRAIN3_STATE)

    log.info("connecting to Ollama (model from LOGGUARD_LLAMA_MODEL)...")
    llama = OllamaClient()
    if not await llama.ping():
        log.error("ollama ping failed — is it running on %s?", llama.base_url)
        await llama.aclose()
        return 1

    new_entries: list[dict] = []
    try:
        for dataset_label, file_path, source_family in DATASETS:
            if not file_path.exists():
                log.warning("  [%s] file missing: %s — skipping", dataset_label, file_path)
                continue
            log.info("[%s] extracting templates from %s ...", dataset_label, file_path.name)
            templates = _extract_templates(parser, file_path)
            log.info("  %s: %d unique templates harvested (cap=%d)",
                     dataset_label, len(templates), TEMPLATES_PER_DATASET)

            for tmpl, example in templates:
                if tmpl in existing_templates:
                    log.info("  [%s] skip (already cached): %s", dataset_label, tmpl[:80])
                    continue
                log.info("  [%s] generating for: %s", dataset_label, tmpl[:80])
                entry = await _generate_one(
                    sbert=sbert, faiss=faiss, llama=llama,
                    template=tmpl, example_line=example,
                    source_family=source_family, dataset_label=dataset_label,
                )
                new_entries.append(entry)
                existing_templates.add(tmpl)
    finally:
        await llama.aclose()

    if not new_entries:
        log.info("[done] no new entries to add — cache already covers all sampled templates")
        return 0

    payload["entries"].extend(new_entries)
    # Mark schema bump so consumers know which version they're reading.
    payload["version"] = max(int(payload.get("version", 1)), 3)
    payload["match_threshold"] = float(payload.get("match_threshold", 0.80))
    CACHE_PATH.write_text(json.dumps(payload, indent=2))
    log.info("[done] wrote %d new entries (%d total) to %s",
             len(new_entries), len(payload["entries"]), CACHE_PATH)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
