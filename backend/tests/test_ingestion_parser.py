"""
Tests for the live-ingestion Drain3 wrapper (`ingestion.parser`).

Strategy: build a fresh `drain3_state.bin` from a tiny synthetic corpus
(via the existing `training.data_prep.parse_log_file`), then load it back
through `LogParser` and confirm that:

  1. Templates are byte-identical for lines that share a template.
  2. The on-disk state file is NOT mutated by inference (so restarts
     don't drift).
  3. `parse()` produces ParsedLog objects with sequential `line_no`s.
"""
from pathlib import Path

import pytest

from ingestion.parser import LogParser
from training.data_prep import parse_log_file

# Each template appears ≥4 times AND each line has a distinct timestamp /
# request id / variable token, so Drain3 generalises every variable
# position into `<*>` rather than baking a literal that happened to be
# constant across the fixture. Production OpenStack training (207k lines)
# never hits this because real timestamps are always unique, but a
# synthetic fixture has to spell that out.
SYNTHETIC_LOG = """\
2026-05-01 09:00:00 INFO nova-api req-aaaa GET /v2/servers status=200 duration=42ms client=10.0.1.1
2026-05-01 09:00:01 INFO nova-api req-bbbb GET /v2/servers status=200 duration=51ms client=10.0.1.2
2026-05-01 09:00:02 INFO nova-api req-cccc GET /v2/servers status=200 duration=33ms client=10.0.1.3
2026-05-01 09:00:03 INFO nova-api req-dddd GET /v2/servers status=200 duration=27ms client=10.0.1.4
2026-05-01 09:00:04 INFO nova-api req-eeee GET /v2/servers status=200 duration=64ms client=10.0.1.5
2026-05-01 09:01:00 ERROR keystone-api req-ffff Failed to authenticate user 'alice' from 192.168.1.42
2026-05-01 09:01:01 ERROR keystone-api req-gggg Failed to authenticate user 'bob' from 192.168.1.43
2026-05-01 09:01:02 ERROR keystone-api req-hhhh Failed to authenticate user 'carol' from 192.168.1.44
2026-05-01 09:01:03 ERROR keystone-api req-iiii Failed to authenticate user 'dan' from 192.168.1.45
2026-05-01 09:02:00 WARN neutron-server slow_query SELECT FROM ports took 1832ms
2026-05-01 09:02:01 WARN neutron-server slow_query SELECT FROM subnets took 2104ms
2026-05-01 09:02:02 WARN neutron-server slow_query SELECT FROM routers took 1543ms
2026-05-01 09:02:03 WARN neutron-server slow_query SELECT FROM networks took 2287ms
"""


@pytest.fixture
def trained_state(tmp_path: Path) -> Path:
    """Run the training-side parser over the synthetic corpus to produce
    a real drain3_state.bin we can hand to `LogParser`."""
    log_path = tmp_path / "synthetic.log"
    log_path.write_text(SYNTHETIC_LOG, encoding="utf-8")
    state_path = tmp_path / "drain3_state.bin"
    parse_log_file([log_path], drain3_state_out=state_path, source_label="test")
    return state_path


def test_parser_loads_persisted_state(trained_state: Path):
    parser = LogParser(trained_state)
    # Three distinct templates: GET /v2/servers, auth failure, slow_query
    assert parser.template_count >= 3


def test_parser_missing_state_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        LogParser(tmp_path / "does_not_exist.bin")


def test_parser_returns_consistent_template_for_same_pattern(trained_state: Path):
    """Two lines that share a template should map to the same template
    string AND the same template_id."""
    parser = LogParser(trained_state)
    a = parser.parse(
        "2026-05-01 09:01:00 INFO nova-api req-xxxx GET /v2/servers status=200 duration=12ms client=10.0.1.99",
        source="nova-api-prod-1",
    )
    b = parser.parse(
        "2026-05-01 09:01:00 INFO nova-api req-yyyy GET /v2/servers status=200 duration=99ms client=10.0.1.100",
        source="nova-api-prod-2",
    )
    assert a.template == b.template
    assert a.template_id == b.template_id
    assert a.template_id != "unknown"


def test_parser_assigns_sequential_line_numbers(trained_state: Path):
    parser = LogParser(trained_state)
    lines = SYNTHETIC_LOG.strip().splitlines()
    parsed = [parser.parse(line, source="host-1") for line in lines]
    assert [p.line_no for p in parsed] == list(range(len(lines)))


def test_parser_preserves_raw_and_source(trained_state: Path):
    parser = LogParser(trained_state)
    raw = "2026-05-01 09:02:00 ERROR keystone-api req-zzzz Failed to authenticate user 'eve' from 192.168.1.99"
    p = parser.parse(raw, source="keystone-api-prod-1")
    assert p.raw == raw
    assert p.source == "keystone-api-prod-1"


def test_parser_does_not_mutate_state_file_on_disk(trained_state: Path):
    """Inference must not rewrite the on-disk state — that's the
    invariant CLAUDE.md is most strict about."""
    before = trained_state.read_bytes()
    parser = LogParser(trained_state)
    # Parse a brand-new template Drain3 hasn't seen before
    parser.parse(
        "2026-05-01 09:03:00 ERROR cinder-volume Volume attach failed for volume vol-12345",
        source="cinder-volume-1",
    )
    after = trained_state.read_bytes()
    assert before == after, "drain3 state file was mutated during inference"


def test_parser_templates_normalised(trained_state: Path):
    """The normalisation regex pass should canonicalise IPs / UUIDs etc.
    so two lines with different IPs produce the same template."""
    parser = LogParser(trained_state)
    p1 = parser.parse(
        "2026-05-01 09:04:00 ERROR keystone-api req-1111 Failed to authenticate user 'x' from 10.0.0.1",
        source="host-a",
    )
    p2 = parser.parse(
        "2026-05-01 09:04:00 ERROR keystone-api req-2222 Failed to authenticate user 'y' from 172.16.5.7",
        source="host-b",
    )
    assert p1.template == p2.template
