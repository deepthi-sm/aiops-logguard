"""
Tests for `rag.prompts` — prompt builder + LLaMA response parser.
"""
from __future__ import annotations

from rag.faiss_client import RetrievedIncident
from rag.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    parse_response,
)
from training.build_faiss import IncidentRecord


def _hit(incident_id: str, similarity: float) -> RetrievedIncident:
    return RetrievedIncident(
        record=IncidentRecord(
            incident_id=incident_id,
            template=f"ERROR template for {incident_id}",
            root_cause=f"cause for {incident_id}",
            recommended_fix=f"fix for {incident_id}",
            resolved_at=None,
            source="synthetic",
        ),
        similarity=similarity,
    )


# -- system prompt --------------------------------------------------------


def test_system_prompt_pins_three_section_format():
    """The parser depends on these section headers — if the system
    prompt drifts, parsing silently breaks. Pin the SRE-style contract
    (ROOT CAUSE / IMPACT / RECOMMENDED FIX) here."""
    assert "ROOT CAUSE:" in SYSTEM_PROMPT
    assert "IMPACT:" in SYSTEM_PROMPT
    assert "RECOMMENDED FIX:" in SYSTEM_PROMPT


def test_system_prompt_forbids_rag_machinery_leakage():
    """The new prompt must instruct LLaMA NOT to mention training
    corpora, prior incidents, or incident IDs in its output. Older
    prompts were producing 'consistent with prior incidents in the
    incident knowledge base where similar anomalies were observed in
    OpenStack training corpora' — exactly what we forbid now."""
    sp = SYSTEM_PROMPT.lower()
    assert "training corpora" in sp or "training data" in sp
    assert "knowledge base" in sp
    assert "prior incidents" in sp or "similar incidents" in sp


# -- user prompt builder --------------------------------------------------


class TestBuildUserPrompt:
    def test_includes_anomaly_facts(self):
        out = build_user_prompt(
            log_template="ERROR keystone-api auth failed",
            sequence_preview=["INFO line a", "ERROR line b"],
            source="nova-api-prod-3",
            similar=[],
        )
        assert "ERROR keystone-api auth failed" in out
        assert "nova-api-prod-3" in out

    def test_includes_similar_incidents_as_background_only(self):
        """Similar hits are passed in as background context for the
        model's reasoning, but the prompt explicitly tells the model
        NOT to quote them by id or label. This stops the previous
        regression where LLaMA echoed `incident_id=train_001731` into
        the user-facing output. The retrieved templates and root
        causes are still included so the model can pattern-match.
        """
        hits = [_hit("syn_001", 0.95), _hit("syn_002", 0.80)]
        out = build_user_prompt(
            log_template="ERROR template_x",
            sequence_preview=["x"],
            source="host-1",
            similar=hits,
        )
        # The model still sees the failure-mode descriptions (so it
        # can write a more specific explanation), in retrieval order.
        assert "cause for syn_001" in out
        assert "cause for syn_002" in out
        assert out.index("cause for syn_001") < out.index("cause for syn_002")
        # The prompt instructs the model NOT to reference these by id
        # or call them "prior incidents".
        assert "DO NOT" in out
        assert "prior incidents" in out

    def test_zero_hits_skips_context_block(self):
        """When FAISS returns nothing, the prompt skips the background
        block entirely — we don't need to apologise to the model for
        the absence."""
        out = build_user_prompt(
            log_template="t",
            sequence_preview=[],
            source="h",
            similar=[],
        )
        # No context-block header should appear with empty hits.
        assert "Background context" not in out
        # The closing instruction is still there.
        assert "three-section format" in out

    def test_caps_sequence_preview_length(self):
        """A 1000-line preview would blow the model's context window —
        cap to last 10 lines."""
        many = [f"line {i}" for i in range(50)]
        out = build_user_prompt(
            log_template="t", sequence_preview=many, source="h", similar=[],
        )
        # First lines should be excluded; last 10 included.
        assert "line 0" not in out
        assert "line 40" in out
        assert "line 49" in out


# -- response parser ------------------------------------------------------


class TestParseResponse:
    def test_canonical_two_section_response(self):
        text = """
ROOT CAUSE:
This is the cause. Two sentences.

RECOMMENDED FIX:
1. Step one
2. Step two
"""
        out = parse_response(text)
        assert "This is the cause" in out.root_cause
        assert "Step one" in out.recommended_fix
        assert "Step two" in out.recommended_fix

    def test_markdown_bold_headers_accepted(self):
        text = """**ROOT CAUSE:**
The cause.

**RECOMMENDED FIX:**
1. Do thing
"""
        out = parse_response(text)
        assert "The cause" in out.root_cause
        assert "Do thing" in out.recommended_fix

    def test_lowercase_headers_accepted(self):
        text = """root cause:
A cause.

recommended fix:
A fix.
"""
        out = parse_response(text)
        assert "A cause" in out.root_cause
        assert "A fix" in out.recommended_fix

    def test_heading_style_headers_accepted(self):
        """Some models prefer markdown headings over labels."""
        text = """## Root cause
The cause.

## Recommended fix
The fix.
"""
        out = parse_response(text)
        assert "The cause" in out.root_cause
        assert "The fix" in out.recommended_fix

    def test_only_root_cause_section_returns_empty_fix(self):
        text = """ROOT CAUSE:
Stuff happened.
"""
        out = parse_response(text)
        assert "Stuff happened" in out.root_cause
        assert out.recommended_fix == ""

    def test_no_headers_keeps_text_in_root_cause(self):
        """Graceful fallback — if the model ignored the format
        instructions, surface the whole response so the user at least
        sees something. The worker will mark this anomaly as failed
        anyway, but the text isn't lost."""
        out = parse_response("Just a freeform paragraph with no headers.")
        assert "Just a freeform paragraph" in out.root_cause
        assert out.recommended_fix == ""

    def test_empty_input(self):
        out = parse_response("")
        assert out.root_cause == ""
        assert out.recommended_fix == ""

    def test_whitespace_only_input(self):
        out = parse_response("   \n\n   ")
        assert out.root_cause == ""
        assert out.recommended_fix == ""

    def test_extra_whitespace_around_sections_trimmed(self):
        text = """

ROOT CAUSE:


   Cause text.


RECOMMENDED FIX:


   Fix text.


"""
        out = parse_response(text)
        assert out.root_cause == "Cause text."
        assert out.recommended_fix == "Fix text."

    def test_sections_in_reverse_order(self):
        """Tolerant: if the model emits FIX before CAUSE, parser still
        attributes correctly."""
        text = """RECOMMENDED FIX:
1. Do this.

ROOT CAUSE:
Because of that.
"""
        out = parse_response(text)
        assert "Because of that" in out.root_cause
        assert "Do this" in out.recommended_fix
