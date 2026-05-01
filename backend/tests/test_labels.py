"""
Tests for training/labels.py — OpenStack-style and HDFS-style anomaly
label loading, plus the window labelling that uses the resulting flagged
sets.
"""
from pathlib import Path

from training.labels import (
    load_hdfs_labels,
    load_openstack_labels,
    make_window_labeler,
)
from training.sequence_builder import ParsedLog


def _events(*raw_lines: str) -> list[ParsedLog]:
    return [
        ParsedLog(
            raw=line,
            template="<TEMPLATE>",
            template_id="0",
            source="openstack",
            line_no=i,
        )
        for i, line in enumerate(raw_lines)
    ]


# -- load_openstack_labels --------------------------------------------------

class TestLoadOpenstackLabels:
    def test_parses_basic_format(self, tmp_path: Path):
        f = tmp_path / "anomaly_labels.txt"
        f.write_text(
            "f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa 1\n"
            "12345678-90ab-cdef-1234-567890abcdef 0\n"
            "deadbeef-dead-beef-dead-beefdeadbeef 1\n",
            encoding="utf-8",
        )
        flagged = load_openstack_labels(f)
        assert flagged == {
            "f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa",
            "deadbeef-dead-beef-dead-beefdeadbeef",
        }

    def test_skips_empty_lines_and_comments(self, tmp_path: Path):
        f = tmp_path / "labels.txt"
        f.write_text(
            "\n"
            "# Header comment — should be ignored\n"
            "abc 1\n"
            "\n"
            "  # Indented comment\n"
            "def 0\n",
            encoding="utf-8",
        )
        # Indented comments are not stripped (line.startswith('#') is False if
        # there's leading whitespace), but the parts split should still leave
        # us with `["#", "Indented", "comment"]` which fails the [1] == "1"
        # check, so it's correctly excluded.
        assert load_openstack_labels(f) == {"abc"}

    def test_tolerates_trailing_columns(self, tmp_path: Path):
        f = tmp_path / "labels.txt"
        f.write_text("abc 1 some-comment\nxyz 0\n", encoding="utf-8")
        assert load_openstack_labels(f) == {"abc"}

    def test_empty_file_returns_empty_set(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        assert load_openstack_labels(f) == set()


# -- make_window_labeler ----------------------------------------------------

class TestMakeWindowLabeler:
    def test_no_flagged_ids_labels_everything_normal(self):
        fn = make_window_labeler(set())
        assert fn(_events("ERROR something bad", "WARN this too")) == "normal"

    def test_uuid_match_in_any_line_returns_anomaly(self):
        flagged = {"f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa"}
        fn = make_window_labeler(flagged)
        events = _events(
            "INFO normal log line",
            "ERROR instance f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa failed to boot",
            "INFO another normal line",
        )
        assert fn(events) == "anomaly"

    def test_uuid_match_is_case_insensitive(self):
        # The label file might lowercase the UUIDs while the log lines uppercase them
        flagged = {"f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa"}
        fn = make_window_labeler(flagged)
        events = _events(
            "INFO instance F8B27F15-7E0D-4C7C-9A4D-AAAAAAAAAAAA created"
        )
        assert fn(events) == "anomaly"

    def test_no_match_returns_normal(self):
        flagged = {"deadbeef-dead-beef-dead-beefdeadbeef"}
        fn = make_window_labeler(flagged)
        events = _events(
            "INFO instance f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa is healthy",
            "INFO heartbeat ok",
        )
        assert fn(events) == "normal"

    def test_non_uuid_id_falls_back_to_substring_match(self):
        # Some LogHub-format datasets use non-UUID identifiers
        flagged = {"req-special-id-007"}
        fn = make_window_labeler(flagged)
        events = _events("ERROR request req-special-id-007 timed out")
        assert fn(events) == "anomaly"

    def test_mixed_uuid_and_non_uuid_ids(self):
        flagged = {
            "f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa",
            "req-007",
        }
        fn = make_window_labeler(flagged)
        events_uuid_hit = _events(
            "INFO event from f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa"
        )
        events_substring_hit = _events("ERROR req-007 failed")
        events_no_hit = _events("INFO unrelated event")
        assert fn(events_uuid_hit) == "anomaly"
        assert fn(events_substring_hit) == "anomaly"
        assert fn(events_no_hit) == "normal"

    def test_empty_chunk_is_normal(self):
        fn = make_window_labeler({"some-id"})
        assert fn([]) == "normal"

    def test_partial_uuid_substring_does_not_match(self):
        """A flagged UUID should only match when the FULL UUID appears in the log
        line — partial substrings of a UUID shouldn't trigger anomaly."""
        flagged = {"f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa"}
        fn = make_window_labeler(flagged)
        # First 8 chars of the UUID, but truncated — shouldn't match
        events = _events("INFO short id f8b27f15 here")
        assert fn(events) == "normal"


# -- load_hdfs_labels -------------------------------------------------------

class TestLoadHdfsLabels:
    def test_parses_hdfs_csv_format(self, tmp_path: Path):
        f = tmp_path / "anomaly_label.csv"
        f.write_text(
            "BlockId,Label\n"
            "blk_-1608999687919862906,Normal\n"
            "blk_7503483334202473044,Anomaly\n"
            "blk_-3544583377289625738,Anomaly\n",
            encoding="utf-8",
        )
        flagged = load_hdfs_labels(f)
        assert flagged == {
            "blk_7503483334202473044",
            "blk_-3544583377289625738",
        }

    def test_label_match_is_case_insensitive(self, tmp_path: Path):
        """LogHub variants sometimes write 'anomaly' lowercase."""
        f = tmp_path / "labels.csv"
        f.write_text(
            "BlockId,Label\n"
            "blk_111,anomaly\n"
            "blk_222,ANOMALY\n"
            "blk_333,Normal\n",
            encoding="utf-8",
        )
        assert load_hdfs_labels(f) == {"blk_111", "blk_222"}

    def test_empty_file_returns_empty_set(self, tmp_path: Path):
        f = tmp_path / "labels.csv"
        f.write_text("BlockId,Label\n", encoding="utf-8")
        assert load_hdfs_labels(f) == set()

    def test_block_ids_drive_substring_window_labeller(self, tmp_path: Path):
        """End-to-end: HDFS labels → make_window_labeler → window labelling
        on lines that mention the flagged block."""
        f = tmp_path / "labels.csv"
        f.write_text(
            "BlockId,Label\nblk_-1234567890,Anomaly\n", encoding="utf-8",
        )
        flagged = load_hdfs_labels(f)
        fn = make_window_labeler(flagged)
        events = _events(
            "INFO blk_-1234567890 receiving block from /10.0.1.42",
            "WARN blk_-1234567890 slow read from /10.0.1.42",
        )
        assert fn(events) == "anomaly"


# -- end-to-end with build_windows ------------------------------------------

def test_labeler_integrates_with_build_windows():
    """The label_fn must work when passed straight into build_windows()."""
    from training.sequence_builder import WINDOW_SIZE, build_windows

    flagged = {"f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa"}
    fn = make_window_labeler(flagged)

    raw_lines = ["INFO normal"] * WINDOW_SIZE
    raw_lines[10] = (
        "ERROR instance f8b27f15-7e0d-4c7c-9a4d-aaaaaaaaaaaa boot failed"
    )

    events = [
        ParsedLog(
            raw=line,
            template="t",
            template_id="0",
            source="src",
            line_no=i,
        )
        for i, line in enumerate(raw_lines)
    ]

    windows = build_windows(events, label_fn=fn)
    assert len(windows) == 1
    assert windows[0].label == "anomaly"
