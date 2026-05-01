"""
Re-export integrity check for `ingestion.sequence_builder`.

CLAUDE.md hard rule: training and ingestion windowing must execute the
same code object. This test pins that they really do — same classes,
same constants, no shadow copy.
"""
from ingestion import sequence_builder as ingest_sb
from training import sequence_builder as train_sb


def test_ingestion_re_exports_training_classes():
    """Each public name resolves to the exact same object as in training."""
    assert ingest_sb.WINDOW_SIZE is train_sb.WINDOW_SIZE
    assert ingest_sb.WINDOW_STRIDE is train_sb.WINDOW_STRIDE
    assert ingest_sb.ParsedLog is train_sb.ParsedLog
    assert ingest_sb.Window is train_sb.Window
    assert ingest_sb.WindowBuilder is train_sb.WindowBuilder
    assert ingest_sb.build_windows is train_sb.build_windows


def test_ingestion_window_builder_works_end_to_end():
    """Sanity: a few events through the streaming builder still produce a Window."""
    wb = ingest_sb.WindowBuilder()
    events = [
        ingest_sb.ParsedLog(
            raw=f"line {i}",
            template=f"tpl_{i % 3}",
            template_id=str(i % 3),
            source="host-1",
            line_no=i,
        )
        for i in range(ingest_sb.WINDOW_SIZE)
    ]
    out = [wb.step(e) for e in events]
    assert out[-1] is not None
    assert isinstance(out[-1], ingest_sb.Window)
    assert len(out[-1].templates) == ingest_sb.WINDOW_SIZE
