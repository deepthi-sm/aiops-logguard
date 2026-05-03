"""
Async HTTP client for Ollama, the local LLaMA host.

Ollama exposes `POST /api/generate` with a stream-of-JSON body. We use
the non-streaming form (`stream: false`) since we want one full
response per anomaly, not a token-by-token stream.

CLAUDE.md hard rule: the LLaMA call is async. The detection path must
NEVER block on it — that's why this lives in the separate RAG worker
process, not in the live runner.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3:8b"
# 5 min default: LLaMA 3 8B on CPU takes 60–180 s per call (longer cold).
# Override via `LOGGUARD_LLAMA_TIMEOUT_S` if running on a fast box.
DEFAULT_TIMEOUT_S = 300.0

log = logging.getLogger(__name__)


class LlamaClientLike(Protocol):
    """Subset of the API the explainer needs. Stubbed in tests so we
    don't spin up Ollama for unit tests."""

    async def generate(self, *, system: str, user: str) -> str: ...
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
        self._client = httpx.AsyncClient(timeout=timeout_s)

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

    async def generate(self, *, system: str, user: str) -> str:
        """Send one prompt, get one full response back as plain text.

        Raises:
            httpx.HTTPError on connection / HTTP failures.
            ValueError on malformed JSON response from Ollama.
        """
        url = f"{self._base_url}/api/generate"
        payload = {
            "model": self._model,
            "system": system,
            "prompt": user,
            "stream": False,
            # `keep_alive` keeps the model warm between calls so the
            # 8B doesn't cold-start every time the worker fires.
            "keep_alive": "5m",
            "options": {
                # Determinism knobs — for the demo we want consistent
                # output across reruns. Low temperature; the spec ranks
                # consistency over creativity for SRE incident summaries.
                "temperature": 0.2,
                # Cap response length. Without this, the 8B will
                # generate ~400-600 tokens for a typical incident
                # (~60-90s on CPU). 200 tokens is enough for the
                # root-cause + recommended-fix sections (each ~3-5
                # sentences) and brings per-call latency down to
                # ~20-30s — a 3x speedup that meaningfully improves
                # the demo UX without truncating useful output.
                "num_predict": 200,
            },
        }
        log.debug("ollama: POST %s model=%s", url, self._model)
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "response" not in data:
            raise ValueError(
                f"unexpected Ollama response shape (no 'response' key): "
                f"{list(data.keys())}"
            )
        return str(data["response"]).strip()

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
