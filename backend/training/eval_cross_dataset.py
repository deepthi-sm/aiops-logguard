"""
Cross-dataset evaluation — Apache logs against the OpenStack-trained models.

The paper's robustness claim ("the system generalises beyond its training
distribution") needs a number behind it. This script produces that number by:

  1. Parsing Apache.log through Drain3 with a FRESH state file (so the
     production drain3_state.bin stays untouched — CLAUDE.md is strict
     about that). Apache templates the model has never seen during
     training are exactly what makes this a cross-dataset test.
  2. Building windows with the same size 20 / stride 1 the trained model
     expects.
  3. Labelling each window via log-level fallback: any line containing
     `[error]`, `[warn]`, or `[fatal]` (case-insensitive) marks the
     window as anomaly. LogHub doesn't ship Apache anomaly labels — the
     paper transparently uses level-as-proxy and we document that here.
  4. Embedding every window's 20 templates through SBERT (same model as
     training, normalize_embeddings=True, identical code path).
  5. Scoring each window through the OpenStack-trained
     `Detector.from_artifacts(...)` and applying both calibrated gates
     (ensemble + confidence). The model never sees the Apache labels.
  6. Computing F1 / precision / recall and writing
     `backend/training/RESULTS_APACHE.md` for the paper.

CLI:
    python -m training.eval_cross_dataset                      # full corpus
    python -m training.eval_cross_dataset --sample 10000       # fast iter
    python -m training.eval_cross_dataset --rebuild-embeddings # ignore cache

Caches embeddings to `artifacts/embeddings_apache.npy` so reruns are
quick. The cache is a function of the input corpus size — pass
`--rebuild-embeddings` after touching the source data.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ml.detector import DetectionResult, Detector
from training.data_prep import parse_log_file
from training.embed import embed_or_load
from training.sequence_builder import (
    WINDOW_SIZE,
    WINDOW_STRIDE,
    Label,
    ParsedLog,
    Window,
    build_windows,
)

# Apache log lines look like:
#   [Sat Jun 24 14:40:01 2005] [error] env.createBean2(): Factory error...
# We classify a window as "anomaly" if any of its 20 lines carries an
# error/warn/fatal level token. This is the standard log-level-as-proxy
# approach used in the LogHub baseline papers when ground-truth labels
# aren't shipped with a corpus.
LEVEL_RE = re.compile(r"\[(error|warn|fatal)\]", re.IGNORECASE)


def make_level_labeler():
    """Return a label_fn for `build_windows(label_fn=...)` that flags
    a window as anomaly iff any of its raw lines mentions a non-normal
    log level."""
    def _fn(chunk: list[ParsedLog]) -> Label:
        for ev in chunk:
            if LEVEL_RE.search(ev.raw):
                return "anomaly"
        return "normal"
    return _fn


@dataclass(frozen=True)
class EvalReport:
    """Summary numbers written to RESULTS_APACHE.md."""
    n_total_windows: int
    n_positive_windows: int  # ground-truth anomaly windows
    n_negative_windows: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    accuracy: float

    @property
    def positive_rate(self) -> float:
        return self.n_positive_windows / max(self.n_total_windows, 1)


def confusion(predicted_anomaly: np.ndarray, ground_truth_anomaly: np.ndarray) -> EvalReport:
    """Standard binary-classification metrics. Both arrays are bool / int (0|1)."""
    pred = predicted_anomaly.astype(bool)
    truth = ground_truth_anomaly.astype(bool)
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    tn = int(np.sum(~pred & ~truth))
    fn = int(np.sum(~pred & truth))

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    n_total = tp + fp + tn + fn
    accuracy = (tp + tn) / n_total if n_total else 0.0
    return EvalReport(
        n_total_windows=n_total,
        n_positive_windows=int(np.sum(truth)),
        n_negative_windows=int(np.sum(~truth)),
        tp=tp, fp=fp, tn=tn, fn=fn,
        precision=precision, recall=recall, f1=f1, accuracy=accuracy,
    )


def predict_anomalies(detector: Detector, embeddings: np.ndarray) -> np.ndarray:
    """Run the detector over every window, return a (N,) bool array.

    Iterates one window at a time — the trained models were exported
    via TorchScript with `(B, L, D)` shape but for a clean "treat each
    window independently" result we go one at a time. This is fine for
    a one-shot eval (~minutes); the live runner has its own batched
    path."""
    if embeddings.ndim != 3:
        raise ValueError(
            f"expected (N, window_len, sbert_dim), got shape {embeddings.shape}"
        )
    out = np.zeros(embeddings.shape[0], dtype=bool)
    for i in range(embeddings.shape[0]):
        result: DetectionResult = detector.score(embeddings[i])
        out[i] = detector.is_anomaly(result)
    return out


def parse_apache(
    log_path: Path,
    *,
    drain3_state_out: Path,
    sample: int | None,
) -> list[ParsedLog]:
    """Parse Apache.log via `training.data_prep.parse_log_file` with a
    SEPARATE drain3 state file so the production state stays byte-
    identical. Apache templates pollute their own state, not ours."""
    if sample is not None:
        # Materialise the first `sample` lines into a temp file so
        # parse_log_file can chew on a smaller corpus without changing
        # its file-iteration logic.
        sampled = log_path.with_suffix(f".sample-{sample}.log")
        with log_path.open("r", encoding="utf-8", errors="replace") as src, \
                sampled.open("w", encoding="utf-8") as dst:
            for i, line in enumerate(src):
                if i >= sample:
                    break
                dst.write(line)
        log_path = sampled

    return parse_log_file(
        [log_path],
        drain3_state_out=drain3_state_out,
        source_label="apache",
    )


def label_windows(windows: list[Window]) -> np.ndarray:
    """Materialise the bool ground-truth array (N,)."""
    return np.array([w.label == "anomaly" for w in windows], dtype=bool)


# -- writing the results doc -----------------------------------------------


def render_results_md(
    report: EvalReport,
    *,
    sample: int | None,
    out_path: Path,
) -> None:
    sample_line = f"first {sample:,} lines" if sample else "full corpus (56,481 lines)"
    body = f"""# Cross-Dataset Evaluation — Apache

Auto-generated by `training/eval_cross_dataset.py`.

The model was trained on **OpenStack** logs (see `RESULTS.md`). This
table is the score it gets on **Apache** logs from the same LogHub
release without any fine-tuning — every Apache template is novel to
the model. It's the test the paper's "generalises beyond its training
distribution" claim is built on.

- Sample: **{sample_line}**
- Window size / stride: {WINDOW_SIZE} / {WINDOW_STRIDE}
- Label source: log-level proxy (`[error] / [warn] / [fatal]` → anomaly)
  — LogHub doesn't ship Apache anomaly labels.

## Headline numbers

| Metric | Value |
|---|---|
| **F1** | **{report.f1:.3f}** |
| Precision | {report.precision:.3f} |
| Recall | {report.recall:.3f} |
| Accuracy | {report.accuracy:.3f} |

## Confusion matrix

| | Predicted anomaly | Predicted normal |
|---|---|---|
| **Truly anomaly** | {report.tp:,} (TP) | {report.fn:,} (FN) |
| **Truly normal** | {report.fp:,} (FP) | {report.tn:,} (TN) |

## Window distribution

| | Count | Share |
|---|---|---|
| Anomaly windows | {report.n_positive_windows:,} | {report.positive_rate:.1%} |
| Normal windows | {report.n_negative_windows:,} | {1 - report.positive_rate:.1%} |
| **Total** | {report.n_total_windows:,} | 100% |

## Methodology notes

- The Apache class balance is heavy on errors (~68% of raw lines are
  `[error]/[warn]/[fatal]`), which propagates into the window-level
  rate above. F1 is the right metric here; raw accuracy would be
  inflated by the class imbalance.
- Drain3 state for this evaluation was mined fresh from Apache and
  written to `artifacts/drain3_state_apache_eval.bin`. The production
  `artifacts/drain3_state.bin` (used by the live ingestion path) was
  not modified.
- SBERT model: `all-MiniLM-L6-v2` (same as training, no fine-tune).
- Anomaly threshold + confidence threshold: loaded from
  `artifacts/thresholds.json` (calibrated on OpenStack — *not* tuned
  on Apache, so the cross-dataset numbers reflect an honest deploy
  with no per-dataset re-tuning).
"""
    out_path.write_text(body, encoding="utf-8")
    print(f"[results] wrote {out_path}")


# -- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-dataset eval — Apache vs the OpenStack-trained models.",
    )
    parser.add_argument("--apache-log", type=Path, default=Path("training/data/apache/Apache.log"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--sample", type=int, default=None,
        help="Use only the first N lines (fast iteration). Default: full corpus.",
    )
    parser.add_argument(
        "--rebuild-embeddings", action="store_true",
        help="Force re-computing SBERT embeddings (ignore the cached .npy).",
    )
    parser.add_argument(
        "--results-out", type=Path, default=Path("training/RESULTS_APACHE.md"),
    )
    args = parser.parse_args(argv)

    log_path = args.apache_log.resolve()
    artifacts = args.artifacts_dir.resolve()
    if not log_path.exists():
        print(f"[error] {log_path} not found — run `python -m training.data_prep --dataset apache --download` first.", file=sys.stderr)
        return 1

    # 1. Parse Apache through Drain3 (separate state file).
    drain3_state_eval = artifacts / "drain3_state_apache_eval.bin"
    print(f"[parse] {log_path} → {drain3_state_eval}")
    parsed = parse_apache(log_path, drain3_state_out=drain3_state_eval, sample=args.sample)

    # 2. Build windows + ground-truth labels.
    windows = build_windows(parsed, label_fn=make_level_labeler())
    if not windows:
        print(f"[error] not enough Apache events to form a single window (need ≥{WINDOW_SIZE}).", file=sys.stderr)
        return 1
    print(f"[windows] {len(windows):,} windows × {WINDOW_SIZE} events")

    truth = label_windows(windows)
    print(f"[labels] anomaly={int(truth.sum()):,} / {len(truth):,} ({truth.mean():.1%})")

    # 3. Embed via SBERT (cached).
    cache_path = artifacts / "embeddings_apache.npy"
    print(f"[embed] cache={cache_path}")
    from sentence_transformers import SentenceTransformer
    sbert = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = embed_or_load(
        windows,
        model=sbert,
        cache_path=cache_path,
        rebuild=args.rebuild_embeddings,
    )

    # 4. Load OpenStack-trained detector + score every window.
    print(f"[detector] loading from {artifacts}")
    detector = Detector.from_artifacts(artifacts)
    print(f"[detector] anomaly_threshold={detector.thresholds.anomaly_threshold:.3f} "
          f"confidence_threshold={detector.thresholds.confidence_threshold:.3f}")

    print("[predict] scoring windows…")
    predicted = predict_anomalies(detector, embeddings)

    # 5. Confusion + report.
    report = confusion(predicted, truth)
    print(f"[result] F1={report.f1:.3f}  P={report.precision:.3f}  R={report.recall:.3f}")
    print(f"        TP={report.tp:,}  FP={report.fp:,}  TN={report.tn:,}  FN={report.fn:,}")

    render_results_md(report, sample=args.sample, out_path=args.results_out.resolve())
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
