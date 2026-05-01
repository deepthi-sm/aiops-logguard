"""
Live-ingestion sliding-window builder.

CLAUDE.md hard rule: training and live ingestion MUST use byte-identical
windowing logic. This module is a thin re-export of `training.sequence_builder`
so both code paths execute the exact same code object — there is literally
nothing to drift.

The streaming `WindowBuilder` (re-exported here) is the path Step 4's Redis
consumer feeds events into; the batch `build_windows()` is what training calls.
Both produce equivalent `Window` objects (verified by
`tests/test_sequence_builder.py::test_window_builder_window_content_matches_batch_api`).
"""
from training.sequence_builder import (
    WINDOW_SIZE,
    WINDOW_STRIDE,
    Label,
    ParsedLog,
    Window,
    WindowBuilder,
    build_windows,
)

__all__ = [
    "WINDOW_SIZE",
    "WINDOW_STRIDE",
    "Label",
    "ParsedLog",
    "Window",
    "WindowBuilder",
    "build_windows",
]
