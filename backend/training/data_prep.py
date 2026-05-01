"""
Step 3 (training pipeline) — Stage 1: data prep.

Downloads the OpenStack (primary) and Apache (secondary, cross-dataset eval)
datasets from LogHub's Zenodo mirror, runs Drain3 to extract stable log
templates, and applies a normalisation pass that strips the variables Drain3
sometimes preserves (IPs, UUIDs, request ids, hex addresses, numeric URL ids).

Produces:
  * `training/data/<dataset>/...` — raw downloaded log files (gitignored)
  * `artifacts/drain3_state.bin`  — persisted Drain3 template tree
                                    (CRITICAL: live ingestion loads the same file
                                    so templates are byte-identical at inference)

CLI:
  python -m training.data_prep --dataset openstack --download --parse
  python -m training.data_prep --dataset apache    --download --parse
  python -m training.data_prep --dataset openstack --parse        # skip download

Idempotent: download skipped if archive present, extract skipped if directory
populated, Drain3 state file overwritten on each --parse (templates accumulate
across both datasets if you run the command twice with different --dataset).

Datasets:
  OpenStack — production cloud-platform backend (Nova / Neutron / Glance /
              Keystone). ~207K lines, labelled. Web-application backend per
              the project's "web app backend logs" requirement.
  Apache    — classic web-server access + error log. ~52K lines, labelled.
              Used for cross-dataset robustness eval (paper claim).
  Both from LogHub: https://github.com/logpai/loghub
  Mirror:           https://zenodo.org/record/3227177
"""
from __future__ import annotations

import argparse
import re
import sys
import tarfile
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.template_miner_config import TemplateMinerConfig

from training.sequence_builder import ParsedLog

LOGHUB_ZENODO_BASE = "https://zenodo.org/record/3227177/files"

# Per-dataset metadata. `log_files` are the file basenames inside the extracted
# archive that contain raw log lines (we feed every one of them into Drain3).
DATASETS: dict[str, dict] = {
    "openstack": {
        "archive": "OpenStack.tar.gz",
        "extract_to": "openstack",
        "log_files": [
            "openstack_normal1.log",
            "openstack_normal2.log",
            "openstack_abnormal.log",
        ],
        "label_file": "anomaly_labels.txt",
    },
    "apache": {
        "archive": "Apache.tar.gz",
        "extract_to": "apache",
        "log_files": ["Apache.log"],
        # LogHub's Apache release ships without a separate label file; the
        # error/warn lines are treated as the positive class downstream.
        "label_file": None,
    },
    "hdfs": {
        # HDFS_1 is the labelled v1 release (~162 MB compressed,
        # ~1.5 GB raw HDFS.log + anomaly_label.csv inside). Used for
        # cross-dataset evaluation and combined-training experiments.
        "archive": "HDFS_1.tar.gz",
        "extract_to": "hdfs",
        "log_files": ["HDFS.log"],
        # HDFS labels are CSV (`BlockId,Label`), not the OpenStack-style
        # newline-delimited file. `training.labels.load_hdfs_labels`
        # handles the conversion.
        "label_file": "anomaly_label.csv",
    },
}


# Normalisation patterns — applied to each Drain3 template after mining. Drain3
# replaces high-cardinality tokens with `<*>`, but it sometimes keeps things
# like IPs and UUIDs that share substrings with stable tokens. This pass
# explicitly canonicalises them so two semantically identical templates end up
# byte-equal regardless of which numbers happened to appear during mining.
NORMALISATION_PATTERNS: dict[str, re.Pattern[str]] = {
    "ip":        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "block_id":  re.compile(r"\bblk_-?\d+\b"),
    "uuid":      re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        re.IGNORECASE,
    ),
    "hex":       re.compile(r"\b0x[0-9a-fA-F]+\b"),
    "timestamp": re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"),
    "email":     re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b"),
    # Web-app addition: numeric segment of a URL path like /api/v1/users/12345
    "path_id":   re.compile(r"(?<=/)\d{2,}(?=/|$|\s)"),
    # Web-app addition: explicit ports `:8080`, `:443` at end of host
    "port":      re.compile(r"(?<=[a-zA-Z\]]):\d{2,5}\b"),
}


def normalise_template(template: str) -> str:
    """Apply each pattern in `NORMALISATION_PATTERNS`, replacing matches with
    `<NAME>`. Order is fixed (Python 3.7+ dict ordering is insertion order)."""
    out = template
    for name, pat in NORMALISATION_PATTERNS.items():
        out = pat.sub(f"<{name.upper()}>", out)
    return out


# -- Download + extract -----------------------------------------------------

def download(url: str, dest: Path, *, timeout: int = 60) -> None:
    """Stream `url` into `dest`. Idempotent: skips if dest exists and is non-empty."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] already downloaded: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {url}\n         → {dest}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length", "0") or "0")
            chunk_size = 1 << 14  # 16 KB
            seen = 0
            while True:
                buf = r.read(chunk_size)
                if not buf:
                    break
                f.write(buf)
                seen += len(buf)
                if total:
                    pct = seen / total * 100
                    print(
                        f"\r          {seen / 1e6:6.1f} / {total / 1e6:6.1f} MB ({pct:5.1f}%)",
                        end="",
                        flush=True,
                    )
            print()
    except (urllib.error.URLError, TimeoutError) as e:
        # Don't leave a half-written file behind — re-run --download will think it's done.
        if dest.exists():
            dest.unlink()
        raise RuntimeError(
            f"download failed: {url}\n"
            f"  Check internet connectivity, or download {dest.name} manually from {LOGHUB_ZENODO_BASE} "
            f"and place it at {dest}."
        ) from e


def extract_tar_gz(archive: Path, target_dir: Path) -> None:
    """Extract `.tar.gz` into `target_dir`. Idempotent: skips if target has any files."""
    if any(target_dir.glob("*")):
        print(f"[skip] already extracted: {target_dir}")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[extract] {archive.name} → {target_dir}")
    with tarfile.open(archive, "r:gz") as tar:
        # filter='data' rejects unsafe members (absolute paths, .., devices) — Python 3.11.4+.
        tar.extractall(target_dir, filter="data")


# -- Drain3 parsing ---------------------------------------------------------

def parse_log_file(
    log_paths: Iterable[Path],
    *,
    drain3_state_out: Path,
    source_label: str = "training",
) -> list[ParsedLog]:
    """Parse one or more raw log files through Drain3 + the normalisation pass.

    Persists the Drain3 state to `drain3_state_out` so the live ingestion path
    loads the identical template tree at inference time. CLAUDE.md hard rule:
    "Don't share Drain3 state by reloading from raw."

    Returns a flat list of ParsedLog (one per non-empty input line) in stream
    order, ready to be fed into `sequence_builder.build_windows()`.
    """
    drain3_state_out.parent.mkdir(parents=True, exist_ok=True)
    miner = _new_template_miner(drain3_state_out)

    parsed: list[ParsedLog] = []
    line_no = 0
    next_progress_print = 100_000
    for path in log_paths:
        if not path.exists():
            raise FileNotFoundError(f"log file not found: {path}")
        print(f"[parse] {path}")
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                result = miner.add_log_message(line)
                template_raw: str = result["template_mined"]
                template = normalise_template(template_raw)
                parsed.append(
                    ParsedLog(
                        raw=line,
                        template=template,
                        template_id=str(result["cluster_id"]),
                        source=source_label,
                        line_no=line_no,
                    )
                )
                line_no += 1
                if line_no >= next_progress_print:
                    print(
                        f"  {line_no:>10,} lines | "
                        f"{len(miner.drain.clusters):>5} templates"
                    )
                    next_progress_print += 100_000

    # Drain3 generalises a cluster's template as it sees more examples — the
    # `template_mined` value captured the instant a line was first added is
    # usually less general than the cluster's settled template after the full
    # corpus is processed. Rewrite each ParsedLog with the final cluster
    # template so two semantically identical lines end up byte-identical
    # regardless of arrival order. This matters because the embedder (SBERT)
    # is sensitive to literal text, and the live ingestion path (which loads
    # the persisted state and only matches, never adds) will produce these
    # final templates by definition.
    cluster_final_template: dict[int, str] = {
        cluster.cluster_id: normalise_template(cluster.get_template())
        for cluster in miner.drain.clusters
    }
    for p in parsed:
        final = cluster_final_template.get(int(p.template_id))
        if final is not None:
            p.template = final

    miner.save_state("data_prep finalize")
    print(
        f"[done] {line_no:,} lines → {len(miner.drain.clusters)} templates "
        f"→ saved {drain3_state_out}"
    )
    return parsed


def _new_template_miner(state_path: Path) -> TemplateMiner:
    """Build a TemplateMiner with file-backed persistence. Reuses existing state
    if `state_path` exists so re-running --parse over a second dataset extends
    the same template tree instead of starting over."""
    config = TemplateMinerConfig()
    # Default Drain3 hyperparameters work well on web-app logs. Tuning is
    # possible via a drain3.ini file alongside this module — see drain3 docs.
    persistence = FilePersistence(str(state_path))
    return TemplateMiner(persistence, config)


# -- CLI --------------------------------------------------------------------

def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, dict]:
    spec = DATASETS[args.dataset]
    data_dir = Path(args.data_dir).resolve() / spec["extract_to"]
    artifact_dir = Path(args.artifact_dir).resolve()
    return data_dir, artifact_dir, spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download + Drain3-parse a LogHub web-application-backend log dataset.",
    )
    parser.add_argument(
        "--dataset",
        choices=sorted(DATASETS),
        required=True,
        help="Dataset name (openstack=primary, apache=secondary cross-dataset eval).",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the dataset archive from Zenodo and extract it.",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse the log files through Drain3, write artifacts/drain3_state.bin.",
    )
    parser.add_argument(
        "--data-dir",
        default="training/data",
        help="Where to keep raw downloaded log files (default: training/data, gitignored).",
    )
    parser.add_argument(
        "--artifact-dir",
        default="artifacts",
        help="Where to write Drain3 state (default: artifacts, gitignored).",
    )
    args = parser.parse_args(argv)

    if not (args.download or args.parse):
        parser.print_help()
        print("\nerror: pass at least one of --download / --parse", file=sys.stderr)
        return 1

    data_dir, artifact_dir, spec = _resolve_paths(args)

    if args.download:
        url = f"{LOGHUB_ZENODO_BASE}/{spec['archive']}"
        archive_path = data_dir.parent / spec["archive"]
        download(url, archive_path)
        extract_tar_gz(archive_path, data_dir)

    if args.parse:
        log_paths = [data_dir / lf for lf in spec["log_files"]]
        missing = [p for p in log_paths if not p.exists()]
        if missing:
            print(
                "[error] missing log files:\n  "
                + "\n  ".join(str(m) for m in missing)
                + "\n  Run with --download first.",
                file=sys.stderr,
            )
            return 1
        drain3_state = artifact_dir / "drain3_state.bin"
        parse_log_file(log_paths, drain3_state_out=drain3_state, source_label=args.dataset)

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
