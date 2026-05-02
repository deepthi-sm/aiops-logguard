"""
LLaMA prompt templates + response parser for the RAG worker.

The prompt is structured to produce a deterministic two-section
response that we can split mechanically:

    ROOT CAUSE:
    <one-paragraph plain-English explanation>

    RECOMMENDED FIX:
    <numbered steps>

The system prompt anchors the model in the "senior SRE" persona; the
user prompt feeds the new anomaly + retrieved similar incidents as
context. The paper directly quotes these templates as the LLaMA
contract — keeping them here rather than inlined in the worker keeps
the contract reviewable and unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rag.faiss_client import RetrievedIncident

# -- prompt templates ------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a senior site-reliability engineer reviewing an alert. "
    "Your job is to explain what's happening in plain English and "
    "give the on-call engineer a numbered list of actions to take. "
    "You MUST format your response with exactly these two sections, "
    "each starting on its own line:\n\n"
    "ROOT CAUSE:\n"
    "<one-paragraph explanation, 2-4 sentences>\n\n"
    "RECOMMENDED FIX:\n"
    "1. <first action>\n"
    "2. <second action>\n"
    "3. <third action>\n\n"
    "Ground your answer in the prior incidents provided as context. "
    "Do not invent details that aren't in the alert or the prior "
    "incidents. If similarity to the prior incidents is weak, say so."
)


def build_user_prompt(
    *,
    log_template: str,
    sequence_preview: list[str],
    source: str,
    similar: list[RetrievedIncident],
) -> str:
    """Render the user-side prompt for one anomaly."""
    lines = [
        "A new anomaly was just detected. Here are the facts:",
        "",
        f"Source: {source}",
        f"Log template: {log_template}",
        "",
        "Recent log lines from the same window:",
    ]
    # Cap the preview so we don't blow past the model's context.
    for raw in sequence_preview[-10:]:
        lines.append(f"  {raw}")

    if similar:
        lines.append("")
        lines.append(
            f"Top {len(similar)} most similar prior incidents from the "
            "incident knowledge base (sorted by similarity):"
        )
        for i, hit in enumerate(similar, 1):
            r = hit.record
            lines.append("")
            lines.append(
                f"[{i}] incident_id={r.incident_id} "
                f"similarity={hit.similarity:.2f} source={r.source}"
            )
            lines.append(f"    Template: {r.template}")
            lines.append(f"    Root cause: {r.root_cause}")
            lines.append(f"    Recommended fix: {r.recommended_fix}")
    else:
        lines.append("")
        lines.append(
            "No similar prior incidents were found in the knowledge "
            "base — generate the explanation from the alert facts alone."
        )

    lines.extend([
        "",
        "Now produce your response in the required two-section format.",
    ])
    return "\n".join(lines)


# -- response parsing ------------------------------------------------------


@dataclass(frozen=True)
class ParsedExplanation:
    """The two pieces extracted from a LLaMA response."""
    root_cause: str
    recommended_fix: str


# Match section headers in any of these shapes (case-insensitive):
#     ROOT CAUSE:                       canonical
#     root cause:                       lowercase
#     **ROOT CAUSE:**                   markdown bold, colon inside **
#     **ROOT CAUSE**:                   markdown bold, colon outside **
#     ## Root cause                     markdown heading, no colon
#     ## Root cause:                    markdown heading with colon
# The colon and ** are both optional; only the label is required.
_HEADER_RE = re.compile(
    r"(?im)^\s*"
    r"(?:#+\s*)?"                          # optional markdown heading prefix
    r"(?:\*\*\s*)?"                        # optional opening **
    r"(?P<label>root\s*cause|recommended\s*fix)"
    r"\s*[:\-]?"                           # optional : or - (inside the **)
    r"\s*(?:\*\*)?"                        # optional closing **
    r"\s*[:\-]?"                           # optional : or - (outside the **)
    r"\s*$"
)


def parse_response(text: str) -> ParsedExplanation:
    """Extract `root_cause` and `recommended_fix` sections.

    Tolerant to:
      * Markdown bold (`**ROOT CAUSE:**`) and headings (`## Root cause`)
      * Trailing whitespace
      * Sections in either order — though we expect ROOT CAUSE first

    Falls back gracefully when the model didn't follow the format:
      * If only one section is found, the rest is assigned to it.
      * If neither section is found, the whole text becomes root_cause
        and recommended_fix is empty (the worker will mark
        explanation_status = "failed" anyway).
    """
    if not text or not text.strip():
        return ParsedExplanation(root_cause="", recommended_fix="")

    # Find every section header line and bucket the body in between.
    sections: dict[str, list[str]] = {"root cause": [], "recommended fix": []}
    current: str | None = None
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            current = " ".join(m.group("label").lower().split())
            if current not in sections:
                # normalise — model may emit "rootcause" or "root  cause"
                current = "root cause" if "root" in current else "recommended fix"
            continue
        if current is not None:
            sections[current].append(line)

    root = "\n".join(sections["root cause"]).strip()
    fix = "\n".join(sections["recommended fix"]).strip()

    if not root and not fix:
        # Headers missing entirely — keep the whole text as root_cause
        # so the user at least sees what the model produced.
        return ParsedExplanation(root_cause=text.strip(), recommended_fix="")
    return ParsedExplanation(root_cause=root, recommended_fix=fix)
