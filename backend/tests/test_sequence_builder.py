"""
Tests for the sliding-window builder used by both training and live ingestion.

CLAUDE.md hard rule: training and ingestion must produce byte-identical
windows. These tests pin the windowing semantics so that PR for ingestion
(Step 4) can re-export this module without surprises.
"""
import pytest

from training.sequence_builder import (
    WINDOW_SIZE,
    WINDOW_STRIDE,
    ParsedLog,
    Window,
    WindowBuilder,
    build_windows,
)


def _events(n: int, source: str = "host-1") -> list[ParsedLog]:
    return [
        ParsedLog(
            raw=f"line {i}",
            template=f"template_{i % 5}",
            template_id=str(i % 5),
            source=source,
            line_no=i,
        )
        for i in range(n)
    ]


# -- batch API: build_windows ----------------------------------------------

def test_default_dimensions_match_canonical_constants():
    assert WINDOW_SIZE == 20
    assert WINDOW_STRIDE == 1


def test_build_windows_emits_n_minus_size_plus_one_at_stride_1():
    events = _events(25)
    windows = build_windows(events)
    assert len(windows) == 25 - WINDOW_SIZE + 1
    for w in windows:
        assert len(w.templates) == WINDOW_SIZE
        assert len(w.raw_lines) == WINDOW_SIZE


def test_build_windows_returns_empty_when_too_few_events():
    assert build_windows(_events(WINDOW_SIZE - 1)) == []
    assert build_windows([]) == []


def test_build_windows_minimum_full_window():
    events = _events(WINDOW_SIZE)
    windows = build_windows(events)
    assert len(windows) == 1
    assert windows[0].line_range == (0, WINDOW_SIZE - 1)


def test_build_windows_stride_2_skips_every_other_window():
    events = _events(WINDOW_SIZE + 4)  # → 5 windows at stride=1
    windows = build_windows(events, stride=2)
    assert len(windows) == 3
    # Line ranges advance by stride
    starts = [w.line_range[0] for w in windows]
    assert starts == [0, 2, 4]


def test_build_windows_invalid_args_raise():
    with pytest.raises(ValueError):
        build_windows(_events(20), size=0)
    with pytest.raises(ValueError):
        build_windows(_events(20), stride=0)


def test_build_windows_label_fn_is_applied_per_window():
    events = _events(WINDOW_SIZE + 2)
    # Every other window is labelled "anomaly" based on whether the first event
    # has an even line_no.
    windows = build_windows(
        events,
        label_fn=lambda chunk: "anomaly" if chunk[0].line_no % 2 == 0 else "normal",
    )
    assert [w.label for w in windows] == ["anomaly", "normal", "anomaly"]


def test_build_windows_label_defaults_to_unknown():
    windows = build_windows(_events(WINDOW_SIZE))
    assert windows[0].label == "unknown"


def test_window_text_uses_sep_separator():
    events = _events(WINDOW_SIZE)
    w = build_windows(events)[0]
    assert " [SEP] " in w.text
    assert w.text == " [SEP] ".join(w.templates)


def test_window_id_is_unique_per_window():
    windows = build_windows(_events(WINDOW_SIZE + 5))
    ids = {w.window_id for w in windows}
    assert len(ids) == len(windows)


def test_build_windows_records_source_when_uniform():
    windows = build_windows(_events(WINDOW_SIZE, source="datanode-1"))
    assert windows[0].source == "datanode-1"


def test_build_windows_records_mixed_when_sources_disagree():
    a = _events(10, source="host-a")
    b = _events(10, source="host-b")
    # Re-number so positions are sequential
    for i, e in enumerate(a + b):
        e.line_no = i
    windows = build_windows(a + b)
    # The single window straddles the two sources
    assert len(windows) == 1
    assert windows[0].source == "mixed"


# -- streaming API: WindowBuilder ------------------------------------------

def test_window_builder_returns_none_until_full():
    wb = WindowBuilder()
    events = _events(WINDOW_SIZE)
    out = [wb.step(e) for e in events]
    assert all(o is None for o in out[:-1])
    assert isinstance(out[-1], Window)


def test_window_builder_emits_per_event_at_stride_1():
    wb = WindowBuilder()
    events = _events(WINDOW_SIZE + 5)
    emitted = [wb.step(e) for e in events]
    nones, windows = emitted[: WINDOW_SIZE - 1], emitted[WINDOW_SIZE - 1 :]
    assert all(o is None for o in nones)
    assert all(isinstance(o, Window) for o in windows)
    assert len(windows) == 6


def test_window_builder_stride_3_emits_every_third_event():
    wb = WindowBuilder(stride=3)
    events = _events(WINDOW_SIZE + 8)
    emitted = [wb.step(e) for e in events]
    # Buffer fills at index size-1, then a Window at indices size-1, size+2, size+5...
    windows = [(i, o) for i, o in enumerate(emitted) if o is not None]
    indices = [i for i, _ in windows]
    assert indices == [WINDOW_SIZE - 1, WINDOW_SIZE + 2, WINDOW_SIZE + 5]


def test_window_builder_invalid_args_raise():
    with pytest.raises(ValueError):
        WindowBuilder(size=0)
    with pytest.raises(ValueError):
        WindowBuilder(stride=0)


def test_window_builder_window_content_matches_batch_api():
    """Streaming and batch must produce equivalent window content for the same input.
    (window_id differs because it's a uuid, but everything else must match.)"""
    events = _events(WINDOW_SIZE + 3)
    batch = build_windows(events)
    wb = WindowBuilder()
    streamed = [w for w in (wb.step(e) for e in events) if w is not None]
    assert len(batch) == len(streamed)
    for a, b in zip(batch, streamed, strict=True):
        assert a.templates == b.templates
        assert a.raw_lines == b.raw_lines
        assert a.source == b.source
        assert a.line_range == b.line_range
        assert a.label == b.label
