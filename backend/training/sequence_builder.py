"""
Sliding-window builder for log sequences.

CLAUDE.md hard rule (non-negotiable):

  > the sequence builder logic must be **identical** between
  > `backend/training/sequence_builder.py` and `backend/ingestion/sequence_builder.py`.
  > Implement it once in a shared module and import from both. Drift here
  > causes silent training/inference mismatch.

This file is the canonical implementation. The Step 4 PR will add
`backend/ingestion/sequence_builder.py` as a thin re-export of this module so
both code paths execute literally the same code object — there is no second
copy to drift out of sync.

Two equivalent APIs are exposed:

  * `build_windows(events, label_fn=...)` — batch (training-time): take a list,
    return all windows.
  * `WindowBuilder().step(event)` — streaming (live-ingestion-time): feed events
    one at a time, get a Window back when one is ready.

Both go through the same `_make_window()` factory so the on-wire shape is
identical regardless of caller.
"""
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

# Canonical window dimensions. Bound into trained models — DO NOT change without
# retraining everything (the Transformer's positional encoding depends on size,
# and stride affects the train/inference distribution match).
WINDOW_SIZE = 20
WINDOW_STRIDE = 1

Label = Literal["normal", "anomaly", "unknown"]


@dataclass
class ParsedLog:
    """One log line after Drain3 + normalisation. Same shape produced by both
    training data prep and live ingestion.
    """
    raw: str            # original line (kept for top_contributing_lines display)
    template: str       # normalised Drain3 template
    template_id: str    # Drain3 cluster id — stable across runs (state persisted)
    source: str         # hostname / service identifier
    line_no: int        # 0-indexed position in the source stream


@dataclass
class Window:
    """One sliding window of WINDOW_SIZE consecutive ParsedLogs."""
    window_id: str
    templates: list[str]            # WINDOW_SIZE Drain3 templates
    raw_lines: list[str]            # WINDOW_SIZE original lines
    label: Label
    source: str                     # single source if all events agree, else "mixed"
    line_range: tuple[int, int]     # (first_line_no, last_line_no_inclusive)

    @property
    def text(self) -> str:
        """Concatenated form fed to SBERT.

        The `[SEP]` separator is part of the trained-model contract — changing
        it invalidates `embeddings_*.npy` and forces a retrain.
        """
        return " [SEP] ".join(self.templates)


# -- Internal: single source of truth for Window construction ---------------

def _make_window(chunk: list[ParsedLog], label: Label) -> Window:
    sources = {e.source for e in chunk}
    source = chunk[0].source if len(sources) == 1 else "mixed"
    return Window(
        window_id=str(uuid.uuid4()),
        templates=[e.template for e in chunk],
        raw_lines=[e.raw for e in chunk],
        label=label,
        source=source,
        line_range=(chunk[0].line_no, chunk[-1].line_no),
    )


# -- Batch API: used by training -------------------------------------------

def build_windows(
    events: Iterable[ParsedLog],
    *,
    size: int = WINDOW_SIZE,
    stride: int = WINDOW_STRIDE,
    label_fn: Callable[[list[ParsedLog]], Label] | None = None,
) -> list[Window]:
    """Slide a fixed window over `events` and emit a Window per stride step.

    Streams shorter than `size` produce zero windows — the model is trained
    on full windows only. Pass `label_fn` to assign each window a label
    based on its events (e.g. "anomaly" if any line touches a known-failed
    request id); without it every window is "unknown".
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if stride <= 0:
        raise ValueError("stride must be positive")

    events_list = list(events)
    if len(events_list) < size:
        return []

    windows: list[Window] = []
    for start in range(0, len(events_list) - size + 1, stride):
        chunk = events_list[start : start + size]
        label: Label = label_fn(chunk) if label_fn else "unknown"
        windows.append(_make_window(chunk, label))
    return windows


# -- Streaming API: used by live ingestion ---------------------------------

class WindowBuilder:
    """Stateful sliding-window emitter for the live ingestion path.

    Feed events one at a time via `step()`. Returns a Window the moment one
    becomes available; otherwise None. Maintains an internal ring buffer of
    `size` events.

    The streaming flow has no labels — every emitted Window is labelled
    "unknown". Severity/anomaly classification happens downstream.
    """

    def __init__(self, *, size: int = WINDOW_SIZE, stride: int = WINDOW_STRIDE) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if stride <= 0:
            raise ValueError("stride must be positive")
        self.size = size
        self.stride = stride
        self._buffer: list[ParsedLog] = []
        # Counts events since the last emission. We emit when the buffer is
        # full AND _emitted_distance has hit `stride`.
        self._emitted_distance = stride

    def step(self, event: ParsedLog) -> Window | None:
        """Push one event. Return a Window if one is now ready, else None."""
        self._buffer.append(event)
        if len(self._buffer) > self.size:
            self._buffer.pop(0)
        if len(self._buffer) < self.size:
            return None
        if self._emitted_distance < self.stride:
            self._emitted_distance += 1
            return None
        self._emitted_distance = 1
        return _make_window(list(self._buffer), label="unknown")
