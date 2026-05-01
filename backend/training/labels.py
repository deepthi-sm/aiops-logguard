"""
Apply LogHub anomaly labels to windows.

For OpenStack: LogHub ships a separate `anomaly_labels.txt` listing instance
ids labelled normal (0) or anomaly (1). A window is labelled "anomaly" if any
of its 20 raw lines mentions a flagged instance id; "normal" otherwise.

For HDFS: LogHub ships `anomaly_label.csv` with rows `BlockId,Label` where
Label is `Normal` or `Anomaly`. The flagged BlockId set feeds the same
substring-match window labeller as OpenStack — block IDs (e.g.
`blk_-1608999687919862906`) appear verbatim inside HDFS log lines.

For Apache: LogHub doesn't ship a labels file. The cross-dataset evaluation
(`training.eval_cross_dataset`) uses a log-level fallback (lines containing
[error] / [warn] / [fatal] count as the positive class).
"""
from __future__ import annotations

import csv
import re
from collections.abc import Callable
from pathlib import Path

from training.sequence_builder import Label, ParsedLog

# Same UUID shape used by the data_prep normaliser.
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def load_openstack_labels(label_file: Path) -> set[str]:
    """Returns the set of instance ids labelled '1' (anomaly) in OpenStack's
    `anomaly_labels.txt`.

    File format (whitespace-separated, one record per line):

        <instance_id>  <0|1>

    Empty lines and `#`-comments are ignored. Unknown trailing columns are
    tolerated (LogHub occasionally appends a third comment field).
    """
    flagged: set[str] = set()
    with label_file.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "1":
                flagged.add(parts[0])
    return flagged


def load_hdfs_labels(label_file: Path) -> set[str]:
    """Returns the set of BlockIds labelled `Anomaly` in HDFS's
    `anomaly_label.csv`.

    File format (CSV with header):

        BlockId,Label
        blk_-1608999687919862906,Normal
        blk_7503483334202473044,Anomaly
        ...

    Block IDs appear verbatim inside HDFS log lines, so the resulting
    flagged set feeds straight into `make_window_labeler` — the
    substring-match path picks them up without any further processing.
    """
    flagged: set[str] = set()
    with label_file.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            block_id = (row.get("BlockId") or "").strip()
            label = (row.get("Label") or "").strip().lower()
            if block_id and label == "anomaly":
                flagged.add(block_id)
    return flagged


def make_window_labeler(
    flagged_ids: set[str],
) -> Callable[[list[ParsedLog]], Label]:
    """Build a label_fn for `sequence_builder.build_windows(label_fn=...)`.

    A window is "anomaly" if any of its raw lines mentions a flagged id;
    "normal" otherwise. UUID-shaped flagged ids are matched via the project's
    canonical UUID regex (case-insensitive). Non-UUID ids fall back to plain
    substring matching.

    If `flagged_ids` is empty (e.g. unlabelled corpus), every window is
    labelled "normal" — calibration code will switch to the log-level
    fallback for that dataset.
    """
    if not flagged_ids:
        return _always_normal

    lc_flagged = {fid.lower() for fid in flagged_ids}
    non_uuid_ids = [fid for fid in flagged_ids if not _UUID_RE.fullmatch(fid)]

    def _fn(chunk: list[ParsedLog]) -> Label:
        for ev in chunk:
            # Fast path: extract every UUID-shaped substring once and check
            # against the lowercased flagged set.
            for match in _UUID_RE.findall(ev.raw):
                if match.lower() in lc_flagged:
                    return "anomaly"
            # Slower path: any non-UUID flagged ids need plain substring match.
            for nid in non_uuid_ids:
                if nid in ev.raw:
                    return "anomaly"
        return "normal"

    return _fn


def _always_normal(_chunk: list[ParsedLog]) -> Label:
    return "normal"
