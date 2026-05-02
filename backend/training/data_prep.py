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
import time
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

# Download timing constants. The pre-fix version of `download()` had a
# 60 s handshake timeout but no per-chunk timeout, so a stalled TCP
# connection mid-stream could hang the process for hours with no log
# output. These constants harden against that:
#
#   - PER_CHUNK_TIMEOUT_S: every `r.read()` call must complete inside
#     this budget (set as the socket-level timeout). If the server stops
#     sending bytes, the read raises socket.timeout instead of blocking
#     forever.
#   - DOWNLOAD_MAX_RETRIES: exponential-backoff retry budget. A flaky
#     connection drops to retry; permanent failure is a real error.
#   - DOWNLOAD_TOTAL_TIMEOUT_S: hard wall-clock cap so a download that's
#     making slow progress still terminates inside a known budget.
PER_CHUNK_TIMEOUT_S = 30
DOWNLOAD_MAX_RETRIES = 3
DOWNLOAD_TOTAL_TIMEOUT_S = 60 * 60  # 60 minutes


def download(
    url: str,
    dest: Path,
    *,
    handshake_timeout: int = 60,
    per_chunk_timeout: int = PER_CHUNK_TIMEOUT_S,
    max_retries: int = DOWNLOAD_MAX_RETRIES,
    total_timeout: int = DOWNLOAD_TOTAL_TIMEOUT_S,
) -> None:
    """Stream `url` into `dest`, chunked, with per-read timeouts + retry.

    Idempotent: skips if `dest` exists and is non-empty. On a fresh run
    the file is opened `wb`. On retry after a partial failure the
    function reopens with HTTP `Range: bytes=N-` and appends, so the
    bytes already on disk aren't refetched.

    Each `r.read()` is bounded by `per_chunk_timeout` (set as the socket
    timeout), so a stalled connection raises `socket.timeout` instead of
    blocking forever. Up to `max_retries` attempts with exponential
    backoff (2 s, 4 s, 8 s). Hard `AssertionError` if the entire
    download exceeds `total_timeout`.
    """
    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] already downloaded: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] {url}\n         -> {dest}")

    overall_t0 = time.monotonic()
    chunk_size = 1 << 14  # 16 KB
    bytes_so_far = 0  # we never have a half-file at this point (idempotent guard above)
    total: int | None = None
    last_progress_pct = -1.0
    attempt = 0

    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url)
            if bytes_so_far > 0:
                # Resume from where the previous attempt died.
                req.add_header("Range", f"bytes={bytes_so_far}-")

            # `handshake_timeout` covers the connect + headers exchange.
            # We replace it with `per_chunk_timeout` on the live socket
            # immediately afterwards so subsequent reads have the
            # tighter bound.
            with urllib.request.urlopen(req, timeout=handshake_timeout) as r:
                # Tighten the socket timeout for the body read loop.
                _set_response_timeout(r, per_chunk_timeout)

                if total is None:
                    # First successful handshake — record total size.
                    cl = r.headers.get("Content-Length", "0") or "0"
                    body_size = int(cl)
                    if r.status == 206:
                        # Partial content: Content-Length is the remaining bytes.
                        total = bytes_so_far + body_size
                    else:
                        total = body_size

                file_mode = "ab" if bytes_so_far > 0 else "wb"
                with open(dest, file_mode) as f:
                    while True:
                        elapsed = time.monotonic() - overall_t0
                        if elapsed > total_timeout:
                            raise AssertionError(
                                f"download exceeded {total_timeout}s "
                                f"({total_timeout / 60:.0f} min) total budget; "
                                f"got {bytes_so_far / 1e6:.1f} MB so far."
                            )
                        buf = r.read(chunk_size)
                        if not buf:
                            break
                        f.write(buf)
                        bytes_so_far += len(buf)
                        if total:
                            pct = bytes_so_far / total * 100
                            # Throttle progress prints so we don't spam logs
                            # for fast connections — only update on whole-percent
                            # boundaries.
                            if pct - last_progress_pct >= 1.0 or pct >= 100.0:
                                print(
                                    f"\r          {bytes_so_far / 1e6:6.1f} / "
                                    f"{total / 1e6:6.1f} MB ({pct:5.1f}%)",
                                    end="",
                                    flush=True,
                                )
                                last_progress_pct = pct

            print()  # newline after the \r progress line
            return

        except AssertionError:
            # Hard timeout — don't retry, just propagate. The half-written
            # file is left intact so a future `--resume` style run could
            # in theory continue, but for now we leave it for the user.
            raise

        # `socket.timeout` is an alias for `TimeoutError` since 3.10, so
        # listing both is redundant — the builtin covers all socket-level
        # read timeouts plus our own AssertionError-bypass below.
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print()  # newline after any \r progress
            print(f"[download] attempt {attempt}/{max_retries} failed at "
                  f"{bytes_so_far / 1e6:.1f} MB: {type(e).__name__}: {e}")
            if attempt >= max_retries:
                if dest.exists() and bytes_so_far == 0:
                    # Nothing useful saved — clean up so a re-run starts fresh.
                    dest.unlink()
                raise RuntimeError(
                    f"download failed after {max_retries} attempts: {url}\n"
                    f"  Got {bytes_so_far / 1e6:.1f} MB before giving up.\n"
                    f"  Check internet connectivity, or download {dest.name} "
                    f"manually from {LOGHUB_ZENODO_BASE} and place it at {dest}."
                ) from e
            backoff = 2 ** attempt  # 2 s, 4 s, 8 s
            print(f"[download] retrying in {backoff}s with Range: bytes={bytes_so_far}-")
            time.sleep(backoff)


def _set_response_timeout(response, timeout_s: float) -> None:
    """Best-effort tighten the underlying socket's recv timeout on an
    already-opened HTTPResponse. urllib doesn't expose this directly, so
    we reach into `.fp` (BufferedReader → SocketIO → socket). If the
    structure changes in some future Python, we silently fall back to
    the handshake-level timeout that was set at urlopen.
    """
    try:
        sock = response.fp.raw._sock  # type: ignore[attr-defined]
        sock.settimeout(timeout_s)
    except AttributeError:
        pass


def extract_tar_gz(archive: Path, target_dir: Path) -> None:
    """Extract `.tar.gz` into `target_dir`. Idempotent: skips if target has any files."""
    if any(target_dir.glob("*")):
        print(f"[skip] already extracted: {target_dir}")
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[extract] {archive.name} -> {target_dir}")
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
        f"[done] {line_no:,} lines -> {len(miner.drain.clusters)} templates "
        f"-> saved {drain3_state_out}"
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
    # Windows cmd defaults to cp1252; reconfigure to UTF-8 so unicode
    # progress/log lines don't crash on a non-utf8 console or pipe.
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream.encoding != "utf-8":
                _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

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
