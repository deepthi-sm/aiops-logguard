"""
Async HTTP client for Ollama, the local LLaMA host.

Ollama exposes `POST /api/generate` with a stream-of-JSON body. We use
the non-streaming form (`stream: false`) since we want one full
response per anomaly, not a token-by-token stream.

CLAUDE.md hard rule: the LLaMA call is async. The detection path must
NEVER block on it — that's why this lives in the separate RAG worker
process, not in the live runner.

Robustness contract (added after the "explanations stuck pending"
incident):

  * Every call has a hard wall-clock timeout (`LOGGUARD_LLAMA_TIMEOUT_S`,
    default 900 s = 15 min). httpx.ReadTimeout propagates from there.
  * Every call logs structured start/end records at INFO so the
    operator can tell which inputs were slow vs which were stuck.
  * `num_predict` caps generation length so a runaway response can't
    eat the whole timeout window.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Protocol

import httpx

DEFAULT_OLLAMA_URL = "http://localhost:11434"
# Default to llama3:8b — the GPU deployment target. For CPU testing
# override with `LOGGUARD_LLAMA_MODEL=llama3.2:1b` (faster but weaker).
# Override `LOGGUARD_LLAMA_HOST` to point at a remote GPU-hosted
# Ollama instance, e.g. `http://gpu-box.local:11434`.
DEFAULT_MODEL = "llama3:8b"
# 15 min hard ceiling per call. Sized so:
#   * llama3:8b on GPU       (~3-5 s)        — never near the limit
#   * llama3.2:1b on CPU     (~30-120 s)     — well under
#   * llama3:8b on CPU       (~60-180 s)     — comfortable headroom
#   * pathological prompts   (rare, ~7-10 m) — still inside the window
# Anything over 15 min is genuinely stuck (Ollama hung / model crashed
# / network black-holed) and we want it surfaced as a failure rather
# than left to spin. Override via `LOGGUARD_LLAMA_TIMEOUT_S`.
DEFAULT_TIMEOUT_S = 900.0
# Hard cap on output tokens. Same reason `num_predict` is capped at
# the model layer: a runaway response that loops on whitespace would
# otherwise eat the whole timeout window before failing.
DEFAULT_NUM_PREDICT = 200

log = logging.getLogger(__name__)


class LlamaClientLike(Protocol):
    """Subset of the API the explainer needs. Stubbed in tests so we
    don't spin up Ollama for unit tests."""

    # `request_id` is optional for log correlation; tests may omit it.
    async def generate(
        self, *, system: str, user: str, request_id: str | None = None,
    ) -> str: ...
    async def aclose(self) -> None: ...


class OllamaClient:
    """Async Ollama HTTP wrapper.

    One HTTP client per worker process; reuses the underlying connection
    pool across calls. `aclose()` on shutdown.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("LOGGUARD_LLAMA_HOST", DEFAULT_OLLAMA_URL)
        ).rstrip("/")
        self._model = (
            model or os.environ.get("LOGGUARD_LLAMA_MODEL", DEFAULT_MODEL)
        )
        if timeout_s is None:
            env_timeout = os.environ.get("LOGGUARD_LLAMA_TIMEOUT_S")
            timeout_s = float(env_timeout) if env_timeout else DEFAULT_TIMEOUT_S
        self._timeout_s = timeout_s
        self._client = httpx.AsyncClient(timeout=timeout_s)
        log.info(
            "ollama: client ready base_url=%s model=%s timeout_s=%.0f num_predict=%d",
            self._base_url, self._model, timeout_s, DEFAULT_NUM_PREDICT,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout_s(self) -> float:
        return self._timeout_s

    async def generate(
        self,
        *,
        system: str,
        user: str,
        request_id: str | None = None,
    ) -> str:
        """Send one prompt, get one full response back as plain text.

        `request_id` is logged at start and end so operators can trace a
        slow call back to the anomaly it was generating for. If omitted,
        a synthetic id is generated so every call still has a tag in
        the logs.

        Raises:
            httpx.TimeoutException — server didn't respond inside
                LOGGUARD_LLAMA_TIMEOUT_S (default 900 s).
            httpx.HTTPError — connect / HTTP-level failure.
            ValueError — malformed JSON response from Ollama.
        """
        rid = request_id or f"llm_{uuid.uuid4().hex[:8]}"
        url = f"{self._base_url}/api/generate"
        prompt_chars = len(system) + len(user)
        payload = {
            "model": self._model,
            "system": system,
            "prompt": user,
            "stream": False,
            # `keep_alive` keeps the model warm between calls so the
            # 8B doesn't cold-start every time the worker fires.
            "keep_alive": "5m",
            "options": {
                # Determinism knobs — for SRE postmortem output we want
                # consistent, technical phrasing across reruns. Low
                # temperature; the spec ranks consistency over creativity
                # for incident summaries.
                "temperature": 0.2,
                # Cap response length to fit the three-section
                # ROOT CAUSE / IMPACT / RECOMMENDED FIX format the
                # prompt enforces. ~200 tokens (~150 words) is enough
                # for a 4-6 sentence postmortem with a numbered fix
                # list. On GPU (llama3:8b) this is ~3-5 s; on CPU
                # ~30-90 s depending on model.
                "num_predict": DEFAULT_NUM_PREDICT,
            },
        }
        log.info(
            "ollama: start rid=%s model=%s prompt_chars=%d num_predict=%d timeout_s=%.0f",
            rid, self._model, prompt_chars, DEFAULT_NUM_PREDICT, self._timeout_s,
        )

        t0 = time.monotonic()
        try:
            resp = await self._client.post(url, json=payload)
        except httpx.TimeoutException:
            elapsed = time.monotonic() - t0
            log.warning(
                "ollama: TIMEOUT rid=%s model=%s elapsed_s=%.1f limit_s=%.0f "
                "prompt_chars=%d — server did not respond within the limit",
                rid, self._model, elapsed, self._timeout_s, prompt_chars,
            )
            raise
        except httpx.HTTPError as e:
            elapsed = time.monotonic() - t0
            log.error(
                "ollama: HTTP error rid=%s model=%s elapsed_s=%.1f err=%s",
                rid, self._model, elapsed, e,
            )
            raise

        elapsed = time.monotonic() - t0
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error(
                "ollama: bad status rid=%s status=%d elapsed_s=%.1f body=%r",
                rid, e.response.status_code, elapsed, e.response.text[:200],
            )
            raise

        data = resp.json()
        if "response" not in data:
            log.error(
                "ollama: malformed response rid=%s elapsed_s=%.1f keys=%s",
                rid, elapsed, list(data.keys()),
            )
            raise ValueError(
                f"unexpected Ollama response shape (no 'response' key): "
                f"{list(data.keys())}"
            )
        out = str(data["response"]).strip()

        # Ollama reports prompt_eval_count + eval_count + durations on
        # success. Logging eval_count tells us if the model actually
        # generated content vs returned an empty completion that looks
        # successful from a status-code perspective.
        eval_count = int(data.get("eval_count", 0))
        prompt_eval_count = int(data.get("prompt_eval_count", 0))
        log.info(
            "ollama: done rid=%s elapsed_s=%.1f response_chars=%d "
            "prompt_tokens=%d output_tokens=%d",
            rid, elapsed, len(out), prompt_eval_count, eval_count,
        )
        return out

    async def ping(self) -> bool:
        """Best-effort liveness check on `GET /api/tags`. Returns False
        on any error so the worker can decide whether to retry or bail."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags")
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def aclose(self) -> None:
        await self._client.aclose()
