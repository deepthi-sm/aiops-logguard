"""
Live Drain3 wrapper used by the ingestion consumer.

Loads the template tree persisted by `training.data_prep` (`drain3_state.bin`)
so live log lines are parsed against the same template clusters that the
trained models were taught on. CLAUDE.md hard rule: "Don't share Drain3
state by reloading from raw — both training and inference load the same
persisted drain3_state.bin so templates are byte-identical."

Important behavioural difference from training:

  * Training calls `add_log_message()`, which both classifies the line
    AND grows the template tree if the line is novel — then runs a
    finalisation pass that rewrites every line with its cluster's settled
    template, and saves the state to disk.
  * Inference (this module) calls `match()` only. That:
      - Never adds new clusters → on-disk state is byte-identical across
        restarts (the invariant CLAUDE.md is strictest about).
      - Never generalises an existing cluster → a line parsed early in
        the stream gets the same template as the same line parsed later.
        Streaming and the batch-finalised training output now agree
        without any post-pass.
      - For lines that don't match any known cluster, falls back to a
        normalised version of the raw line and `template_id = "unknown"`
        so downstream code can detect the rare-template signal.

The same `normalise_template()` regex pass used during training is applied
here so the resulting `template` field is identical for identical lines
regardless of which code path produced them.
"""
from __future__ import annotations

from pathlib import Path

from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.template_miner_config import TemplateMinerConfig

from ingestion.sequence_builder import ParsedLog
from training.data_prep import normalise_template

# Template id reported when an incoming line matches no known cluster.
# Downstream can treat this as a low-confidence signal — the trained models
# never saw an embedding for an unknown template, so detection on these
# windows is best-effort.
UNKNOWN_TEMPLATE_ID = "unknown"


class LogParser:
    """Drain3-backed log parser for live ingestion.

    Construct with the path to a `drain3_state.bin` produced by
    `training.data_prep`. Each `parse(raw, source)` call returns one
    `ParsedLog` ready to be fed into `WindowBuilder.step()`.

    Thread-safety: the underlying Drain3 TemplateMiner is NOT thread-safe.
    One LogParser per consumer task. asyncio coroutines on a single event
    loop are fine because they don't run concurrently.
    """

    def __init__(self, state_path: Path | str) -> None:
        state_path = Path(state_path)
        if not state_path.exists():
            raise FileNotFoundError(
                f"drain3 state file not found: {state_path}\n"
                "  Run `python -m training.run_full_pipeline --dataset openstack` first "
                "to produce artifacts/drain3_state.bin."
            )
        self._state_path = state_path
        self._miner = self._load_miner(state_path)
        self._line_no = 0

    @staticmethod
    def _load_miner(state_path: Path) -> TemplateMiner:
        config = TemplateMinerConfig()
        # FilePersistence both reads existing state on construction AND would
        # write it back on save_state(). We intentionally never call
        # save_state() so the file stays exactly as training produced it.
        persistence = FilePersistence(str(state_path))
        return TemplateMiner(persistence, config)

    @property
    def template_count(self) -> int:
        """Number of Drain3 clusters currently loaded in memory."""
        return len(self._miner.drain.clusters)

    def parse(self, raw: str, source: str, *, origin: str = "live-stream") -> ParsedLog:
        """Parse one log line against the loaded template tree.

        Match-only — never adds new clusters, never saves state.

        Args:
            raw: the full original line (newline already stripped by caller).
            source: hostname or service identifier (e.g. "nova-api-prod-3").
                    Stored on the ParsedLog so windows can be tagged by source.
            origin: entry-point tag — "live-stream" (default) or "user-upload".
                    Propagated through to the Anomaly so the dashboard can
                    filter by origin without overloading the displayed source.

        Returns:
            A ParsedLog with the matched cluster's settled template, the
            cluster id as a string (or `UNKNOWN_TEMPLATE_ID` for novel
            lines), and an auto-incrementing line_no relative to this
            parser instance's lifetime.
        """
        cluster = self._miner.match(raw)
        if cluster is not None:
            template = normalise_template(cluster.get_template())
            template_id = str(cluster.cluster_id)
        else:
            # Novel line — fall back to a normalised raw so the downstream
            # SBERT embedder still gets text that's been through the same
            # canonicalisation pipeline as known templates.
            template = normalise_template(raw)
            template_id = UNKNOWN_TEMPLATE_ID

        parsed = ParsedLog(
            raw=raw,
            template=template,
            template_id=template_id,
            source=source,
            line_no=self._line_no,
            origin=origin,
        )
        self._line_no += 1
        return parsed
