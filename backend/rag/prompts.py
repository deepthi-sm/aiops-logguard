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
    "You are a senior site-reliability engineer writing a short "
    "postmortem note for the on-call team. Use confident, specific "
    "technical language — name the failure mode (kernel panic, ECC "
    "memory error, network timeout, auth failure, disk I/O, etc.). "
    "Do not hedge with phrases like 'this might be' or 'possibly'. "
    "Keep the whole note to 4-6 sentences. Do not invent host or "
    "incident identifiers — use only the ones present in the alert. "
    "Do not write 'training data', 'knowledge base', 'prior "
    "incidents', or 'similar incidents' in your output; the reader "
    "only knows about this one alert.\n\n"
    "Your reply must contain exactly these three section headers, "
    "in this order, and nothing after the last fix step:\n\n"
    "ROOT CAUSE:\n"
    "<1-2 sentences naming the failure mode>\n\n"
    "IMPACT:\n"
    "<1 sentence on what's at risk for users or dependent services>\n\n"
    "RECOMMENDED FIX:\n"
    "1. <first concrete action>\n"
    "2. <second concrete action>\n"
    "3. <third concrete action>"
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

    # NOTE on the FAISS hits: we still pass them in so the model has
    # technical context (similar log shapes), but the SYSTEM_PROMPT
    # forbids referencing them by id or as "prior incidents". The hits
    # are background context for the model — never quoted in the
    # output. This is critical for demo-grade output: previously the
    # model was happily echoing "incident_id=train_001731" into the
    # user-facing explanation.
    if similar:
        lines.append("")
        lines.append(
            "Background context (for your reasoning only — DO NOT "
            "reference these by id, do NOT mention 'prior incidents' "
            "or 'knowledge base' in your output):"
        )
        for i, hit in enumerate(similar, 1):
            r = hit.record
            lines.append("")
            lines.append(f"  Reference {i}: source={r.source}")
            lines.append(f"    Template: {r.template}")
            lines.append(f"    Failure mode: {r.root_cause}")
    else:
        # Explicit empty-context note. With no FAISS hits we used to
        # leave the prompt with no context block at all, which a few
        # times let small models drift into rambling or skip the
        # required format. The single-line directive anchors the model
        # back to the alert facts and the three-section template.
        lines.append("")
        lines.append(
            "No background context is available for this alert. "
            "Reason from the alert facts above alone."
        )

    lines.extend([
        "",
        "Now write the postmortem note in the required three-section format.",
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
#     IMPACT:                           the new SRE-style middle section
# The colon and ** are both optional; only the label is required.
_HEADER_RE = re.compile(
    r"(?im)^\s*"
    r"(?:#+\s*)?"                          # optional markdown heading prefix
    r"(?:\*\*\s*)?"                        # optional opening **
    r"(?P<label>root\s*cause|impact|recommended\s*fix)"
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
    # IMPACT is its own bucket so we can preserve the section header in
    # the rendered output ("ROOT CAUSE: ...  IMPACT: ...") rather than
    # losing the IMPACT prose between known sections.
    sections: dict[str, list[str]] = {
        "root cause": [],
        "impact": [],
        "recommended fix": [],
    }
    current: str | None = None
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            label = " ".join(m.group("label").lower().split())
            if label in sections:
                current = label
            elif "root" in label:
                current = "root cause"
            elif "impact" in label:
                current = "impact"
            else:
                current = "recommended fix"
            continue
        if current is not None:
            sections[current].append(line)

    root_text = "\n".join(sections["root cause"]).strip()
    impact_text = "\n".join(sections["impact"]).strip()
    if root_text and impact_text:
        # Re-emit both sections with their labels so the frontend can
        # render them as a structured postmortem note rather than a
        # single paragraph that hides the IMPACT framing.
        root = f"ROOT CAUSE: {root_text}\n\nIMPACT: {impact_text}"
    elif impact_text and not root_text:
        root = f"IMPACT: {impact_text}"
    else:
        root = root_text
    fix = "\n".join(sections["recommended fix"]).strip()

    if not root and not fix:
        # Headers missing entirely — keep the whole text as root_cause
        # so the user at least sees what the model produced.
        return ParsedExplanation(root_cause=text.strip(), recommended_fix="")
    return ParsedExplanation(root_cause=root, recommended_fix=fix)
