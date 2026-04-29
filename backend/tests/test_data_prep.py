"""
Tests for training/data_prep.py — the Drain3 wrapper and normalisation pass.

CI does NOT download real LogHub archives (slow, brittle, gigabytes). Instead
we exercise the parser against an inline web-application-backend fixture that
mimics OpenStack/Apache style logs: HTTP requests, auth failures, slow queries,
service-to-service errors. This is enough to validate template extraction,
clustering, normalisation, and state persistence end-to-end.
"""
from pathlib import Path

import pytest

from training.data_prep import (
    NORMALISATION_PATTERNS,
    normalise_template,
    parse_log_file,
)
from training.sequence_builder import ParsedLog, build_windows

# A tiny synthetic web-app-backend log. Lines repeat templates with varying
# variable parts so Drain3 has something to cluster.
SYNTHETIC_LOG = """\
2026-04-28 10:00:00.123 INFO  nova-api req-abc12345 GET /v2/servers status=200 duration=42ms client=10.0.1.42
2026-04-28 10:00:00.456 INFO  nova-api req-bcd23456 GET /v2/servers status=200 duration=51ms client=10.0.1.43
2026-04-28 10:00:01.001 INFO  nova-api req-cde34567 POST /v2/servers status=202 duration=88ms client=10.0.1.44
2026-04-28 10:00:01.234 ERROR keystone-api req-def45678 Failed to authenticate user 'alice' from 192.168.1.42
2026-04-28 10:00:01.567 ERROR keystone-api req-efa56789 Failed to authenticate user 'bob' from 192.168.1.43
2026-04-28 10:00:02.001 WARN  neutron-server slow_query: SELECT * FROM ports took 1832ms
2026-04-28 10:00:02.234 WARN  neutron-server slow_query: SELECT * FROM subnets took 2104ms
2026-04-28 10:00:02.567 INFO  nova-api req-fab67890 GET /v2/servers/12345 status=200 duration=33ms
2026-04-28 10:00:03.001 INFO  nova-api req-abc78901 GET /v2/servers/67890 status=200 duration=29ms
2026-04-28 10:00:03.234 ERROR glance-api Image upload failed: connection reset by peer (host=10.0.2.5)
2026-04-28 10:00:03.567 ERROR glance-api Image upload failed: connection reset by peer (host=10.0.2.7)
2026-04-28 10:00:04.001 INFO  keystone-api Successful authentication for user 'charlie'
2026-04-28 10:00:04.234 INFO  keystone-api Successful authentication for user 'dave'
2026-04-28 10:00:04.567 WARN  nova-api request_id=req-001 throttled: rate limit 100/s exceeded
2026-04-28 10:00:05.001 WARN  nova-api request_id=req-002 throttled: rate limit 100/s exceeded
"""


@pytest.fixture
def synthetic_log_file(tmp_path: Path) -> Path:
    p = tmp_path / "synthetic.log"
    p.write_text(SYNTHETIC_LOG, encoding="utf-8")
    return p


# -- normalise_template ----------------------------------------------------

class TestNormaliseTemplate:
    def test_strips_ipv4_addresses(self):
        out = normalise_template("connection from 192.168.1.42 refused")
        assert "192.168.1.42" not in out
        assert "<IP>" in out

    def test_strips_uuids_case_insensitive(self):
        out = normalise_template(
            "request 550e8400-e29b-41d4-a716-446655440000 failed and "
            "550E8400-E29B-41D4-A716-446655440000 too"
        )
        assert "550e8400" not in out.lower()
        assert out.count("<UUID>") == 2

    def test_strips_block_ids_positive_and_negative(self):
        out = normalise_template("block blk_-123 vs blk_456 same")
        assert "blk_-123" not in out
        assert "blk_456" not in out
        assert out.count("<BLOCK_ID>") == 2

    def test_strips_hex_addresses(self):
        out = normalise_template("segfault at 0xdeadbeef in thread")
        assert "0xdeadbeef" not in out
        assert "<HEX>" in out

    def test_strips_iso_timestamps(self):
        out = normalise_template("2026-04-28T10:14:22Z something happened")
        assert "2026-04-28" not in out
        assert "<TIMESTAMP>" in out

    def test_strips_emails(self):
        out = normalise_template("notify alice.smith+filter@example.com on event")
        assert "alice" not in out
        assert "<EMAIL>" in out

    def test_strips_numeric_url_path_segments(self):
        out = normalise_template("GET /api/v1/users/12345/posts/67")
        assert "12345" not in out
        assert "67" not in out
        assert "<PATH_ID>" in out

    def test_preserves_short_path_segments(self):
        # Single-digit version numbers like /v1/ should NOT be stripped — they
        # disambiguate API versions and are stable.
        out = normalise_template("GET /api/v1/users")
        assert "v1" in out

    def test_strips_explicit_ports(self):
        out = normalise_template("connect to backend:8080 failed")
        assert ":8080" not in out
        assert "<PORT>" in out

    def test_preserves_log_level_words(self):
        out = normalise_template("INFO ERROR WARN DEBUG something")
        assert "INFO" in out
        assert "ERROR" in out
        assert "WARN" in out
        assert "DEBUG" in out

    def test_idempotent_on_already_normalised_input(self):
        once = normalise_template("connection from 192.168.1.42")
        twice = normalise_template(once)
        assert once == twice

    def test_pattern_set_is_documented(self):
        # If you add a pattern to NORMALISATION_PATTERNS, please add a test
        # above. This keeps the contract list visible at a glance.
        expected = {"ip", "block_id", "uuid", "hex", "timestamp", "email", "path_id", "port"}
        assert set(NORMALISATION_PATTERNS) == expected


# -- parse_log_file (Drain3 + normalisation) -------------------------------

class TestParseLogFile:
    def test_returns_one_parsedlog_per_non_empty_line(self, synthetic_log_file: Path, tmp_path: Path):
        out = parse_log_file(
            [synthetic_log_file],
            drain3_state_out=tmp_path / "drain3_state.bin",
        )
        # 15 non-empty lines in the fixture
        assert len(out) == 15
        assert all(isinstance(p, ParsedLog) for p in out)
        assert all(p.line_no == i for i, p in enumerate(out))

    def test_clusters_similar_lines_into_same_template(
        self, synthetic_log_file: Path, tmp_path: Path,
    ):
        out = parse_log_file(
            [synthetic_log_file],
            drain3_state_out=tmp_path / "drain3_state.bin",
        )
        # The two "Failed to authenticate user '...'" lines should share a template.
        auth_failures = [p for p in out if "authenticate user" in p.raw and "Failed" in p.raw]
        assert len(auth_failures) == 2
        assert auth_failures[0].template_id == auth_failures[1].template_id
        assert auth_failures[0].template == auth_failures[1].template

    def test_template_text_has_variables_normalised(
        self, synthetic_log_file: Path, tmp_path: Path,
    ):
        out = parse_log_file(
            [synthetic_log_file],
            drain3_state_out=tmp_path / "drain3_state.bin",
        )
        # No raw IP should leak into any template
        for p in out:
            assert "192.168" not in p.template
            assert "10.0.1" not in p.template
            assert "10.0.2" not in p.template

    def test_persists_state_file(self, synthetic_log_file: Path, tmp_path: Path):
        state = tmp_path / "drain3_state.bin"
        assert not state.exists()
        parse_log_file([synthetic_log_file], drain3_state_out=state)
        assert state.exists()
        assert state.stat().st_size > 0

    def test_state_file_loadable_for_inference(
        self, synthetic_log_file: Path, tmp_path: Path,
    ):
        """The Drain3 state file is the bridge between training and live
        ingestion. Loading it back must yield a usable miner."""
        from drain3 import TemplateMiner
        from drain3.file_persistence import FilePersistence
        from drain3.template_miner_config import TemplateMinerConfig

        state = tmp_path / "drain3_state.bin"
        parse_log_file([synthetic_log_file], drain3_state_out=state)

        # Reload — fresh miner, same persisted state
        miner2 = TemplateMiner(FilePersistence(str(state)), TemplateMinerConfig())
        assert len(miner2.drain.clusters) > 0

        # A novel-looking line that fits one of the trained templates should
        # match an existing cluster — proving templates are usable at inference.
        new_line = (
            "2026-04-28 11:00:00.000 ERROR keystone-api req-xxxxxxxx "
            "Failed to authenticate user 'eve' from 10.99.99.99"
        )
        result = miner2.add_log_message(new_line)
        # change_type is "none" when the line slots into an existing cluster.
        assert result["change_type"] == "none"

    def test_missing_input_file_raises_clearly(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="not found"):
            parse_log_file(
                [tmp_path / "nope.log"],
                drain3_state_out=tmp_path / "drain3_state.bin",
            )

    def test_output_feeds_directly_into_sequence_builder(
        self, synthetic_log_file: Path, tmp_path: Path,
    ):
        """End-to-end: parsed events feed straight into the windower with
        no shape adapter in between."""
        events = parse_log_file(
            [synthetic_log_file],
            drain3_state_out=tmp_path / "drain3_state.bin",
        )
        # The fixture is shorter than WINDOW_SIZE, so we use a smaller window
        # only for this test.
        windows = build_windows(events, size=5, stride=1)
        assert len(windows) == len(events) - 5 + 1
        assert windows[0].line_range == (0, 4)
        assert all(len(w.templates) == 5 for w in windows)
