"""
Proper-evaluation orchestrator (Scope C).

Trains two models with a proper 70/15/15 split for genuine held-out
testing, evaluates both against three test sets, and writes
paper-grade results files. NEVER overwrites `artifacts/` — everything
lands under `artifacts_proper/`. Promotion is the user's call.

Layout produced (all under `artifacts_proper/`):

  _inputs/
    openstack/  — embeddings.npy, labels.npy, windows.jsonl,
                  drain3_state.bin, test_idx.npy
    hdfs/       — same, plus the union-of-OS+HDFS Drain3 state lives at
                  combined/drain3_state.bin instead.
  openstack_only/  — Model A artifacts (transformer.pt, autoencoder.pt,
                     confidence_scorer.pt, thresholds.json, …)
  combined/        — Model B artifacts (same set, trained on OS+HDFS).
  RESULTS_OPENSTACK_TEST.md — both models on OS held-out test
  RESULTS_HDFS_TEST.md      — both models on HDFS held-out test
  RESULTS_APACHE.md         — both models on full Apache (never seen)
  RESULTS_SUMMARY.md        — one paper-ready table comparing both
                              models on all three test sets

Stop conditions
  * If any held-out F1 < 0.7 the run stops with a clear failure
    summary — that's a 'something is broken' signal, not bad
    regularization. The user can rerun after fixing or override the
    floor with `--f1-floor 0.0` to accept whatever falls out.

Dataset coverage warning
  * Full HDFS_1 corpus is ~11M lines. SBERT embedding + transformer
    training together take roughly 60-90 min on a CPU laptop. The
    `--hdfs-sample N` flag downsamples HDFS for fast iteration; pass
    `--hdfs-full` (default) for paper-grade numbers.

CLI:
    python -m training.run_proper_eval                       # full corpora
    python -m training.run_proper_eval --hdfs-sample 200000  # match OS scale
    python -m training.run_proper_eval --f1-floor 0.0        # disable floor
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch

from ml.detector import (
    Detector,
)
from training.data_prep import (
    DATASETS,
    LOGHUB_ZENODO_BASE,
    download,
    extract_tar_gz,
    parse_log_file,
)
from training.embed import embed_or_load
from training.eval_cross_dataset import (
    confusion as cross_confusion,
)
from training.eval_cross_dataset import (
    label_windows as cross_label_windows,
)
from training.eval_cross_dataset import (
    make_level_labeler,
    parse_apache,
    predict_anomalies,
)
from training.eval_holdout_openstack import (
    SplitMetrics,
    _auc_score,
    compute_confidence,
    metrics_for_split,
)
from training.labels import (
    load_hdfs_labels,
    load_openstack_labels,
    make_window_labeler,
)

# Reuse the existing pipeline step helpers — they handle the model →
# TorchScript save + metrics-json side effects so we don't re-implement
# them here.
from training.run_full_pipeline import (
    step_calibrate as _step_calibrate,
)
from training.run_full_pipeline import (
    step_component_scores as _step_component_scores,
)
from training.run_full_pipeline import (
    step_train_autoencoder as _step_train_ae,
)
from training.run_full_pipeline import (
    step_train_transformer as _step_train_transformer,
)
from training.sequence_builder import build_windows

log = logging.getLogger(__name__)

# Test split — 15 % held out from training AND calibration. The
# remaining 85 % goes through the existing transformer-trainer's
# internal 80/20 split, giving us roughly 70/15/15 overall.
TEST_FRACTION = 0.15
TEST_SEED = 99  # different seed than training (42) for an independent split

# Defaults
DEFAULT_OUTPUT_DIR = Path("artifacts_proper")
DEFAULT_F1_FLOOR = 0.7
DEFAULT_DATA_DIR = Path("training/data")

# Smoke-test constants. The smoke run validates that every phase of the
# pipeline executes end-to-end, NOT that the resulting models are good.
# The hard time cap raises an AssertionError if exceeded so a regression
# can't quietly bloat the smoke runtime.
#
# Budget reality: SBERT on CPU is ~1.2 s per batch of 128 strings.
# 200 lines per OS file × 3 files plus 200 HDFS lines = ~12k strings,
# ≈95 batches ≈ 2 min just for embedding. Plus training/eval overhead,
# 8-min ceiling is realistic on a laptop CPU. The previous 2-min cap
# was based on an over-optimistic estimate.
SMOKE_OUTPUT_DIR = Path("artifacts_smoke")
SMOKE_SAMPLE = 200          # lines per OS / HDFS file (≈580 windows total each)
SMOKE_EPOCHS = 2            # transformer + AE
SMOKE_TIMEOUT_S = 480.0     # 8 min hard cap, asserted at each phase boundary


# -- preprocessed-dataset wrapper ------------------------------------------


@dataclass
class PreparedDataset:
    """All the per-dataset arrays + indices the orchestrator passes
    around. Shapes:
        embeddings   (N, WINDOW_SIZE, 384)
        labels       (N,)  — int64, 0/1
        test_idx     (k,)  — int indices into the (N,) arrays
        train_idx    (N-k,)
    """
    name: str
    embeddings: np.ndarray
    labels: np.ndarray
    test_idx: np.ndarray
    train_idx: np.ndarray

    def slice(self, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return self.embeddings[indices], self.labels[indices]


# -- data preparation ------------------------------------------------------


def _ensure_downloaded(dataset_key: str, data_dir: Path) -> Path:
    """Download + extract the LogHub archive for a dataset. Returns the
    extracted directory."""
    spec = DATASETS[dataset_key]
    extracted = data_dir / spec["extract_to"]
    archive = data_dir / spec["archive"]
    if not extracted.exists() or not any(extracted.iterdir()):
        download(f"{LOGHUB_ZENODO_BASE}/{spec['archive']}", archive)
        extract_tar_gz(archive, extracted)
    return extracted


def _parse_dataset_lines(
    dataset_key: str,
    data_dir: Path,
    drain3_state_out: Path,
    *,
    sample: int | None,
    per_file_source: bool = False,
):
    """Parse the dataset through Drain3 (writes drain3_state_out).
    For HDFS we apply a sampler at parse time so we don't carry
    11M lines in memory if the user passed --hdfs-sample.

    `per_file_source=True` parses each log file separately with
    `source_label=p.stem` (e.g. `openstack_normal1`,
    `openstack_abnormal`) so the file-based OpenStack labeller can tell
    abnormal events from normal ones. Used in smoke mode where the
    instance-id-based labels in `anomaly_labels.txt` are unlikely to
    match the first 200 lines of each file. Default `False` keeps
    backward-compat with the original instance-id labelling.
    """
    spec = DATASETS[dataset_key]
    extracted = _ensure_downloaded(dataset_key, data_dir)
    log_paths = [extracted / f for f in spec["log_files"]]
    missing = [p for p in log_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"missing {dataset_key} log files: {missing}"
        )

    if sample is not None:
        # Materialise a sampled file so parse_log_file doesn't have to
        # support sub-sampling itself.
        sampled_paths: list[Path] = []
        for p in log_paths:
            sp = p.with_suffix(f".sample-{sample}.log")
            if not sp.exists():
                _materialise_sample(p, sp, sample)
            sampled_paths.append(sp)
        log_paths = sampled_paths

    if per_file_source:
        # Mirrors `run_full_pipeline.step_data_prep` behaviour: each
        # file is parsed individually with `source_label=stem`, so the
        # `_label_by_source` labeller can tag windows by which file
        # (normal vs abnormal) the events came from.
        all_events = []
        line_offset = 0
        for log_path in log_paths:
            evs = parse_log_file(
                [log_path],
                drain3_state_out=drain3_state_out,
                source_label=log_path.stem,
            )
            for ev in evs:
                ev.line_no += line_offset
            all_events.extend(evs)
            line_offset += len(evs)
        return all_events

    return parse_log_file(
        log_paths,
        drain3_state_out=drain3_state_out,
        source_label=dataset_key,
    )


def _materialise_sample(src: Path, dst: Path, n: int) -> None:
    with src.open("r", encoding="utf-8", errors="replace") as r, \
            dst.open("w", encoding="utf-8") as w:
        for i, line in enumerate(r):
            if i >= n:
                break
            w.write(line)


def _label_by_source_filename(chunk):
    """File-based OpenStack labeller — matches `run_full_pipeline.py`.

    A window is "anomaly" if any event in it came from a file whose
    name contains "abnormal" (LogHub's OpenStack release uses file
    layout: `openstack_normal1.log`, `openstack_normal2.log`,
    `openstack_abnormal.log`).

    Cheaper than instance-id matching and works on any sample size
    (the instance-id labeller breaks when the sample doesn't include
    flagged instance_ids).
    """
    return "anomaly" if any("abnormal" in ev.source.lower() for ev in chunk) else "normal"


def _label_windows_for(dataset_key: str, data_dir: Path, *, file_based_openstack: bool = False):
    """Build the label_fn appropriate to this dataset.

    OpenStack: anomaly_labels.txt (instance_id 0/1 records) by default.
               When `file_based_openstack=True`, fall back to
               file-name-based labels (matches `run_full_pipeline.py`).
               This is the smoke-mode path — small samples don't
               include enough instance IDs to make the labels match.
    HDFS:      anomaly_label.csv (BlockId, Normal/Anomaly).
    """
    spec = DATASETS[dataset_key]
    if spec["label_file"] is None:
        # Apache — caller uses level-fallback labelling.
        return make_level_labeler()
    if dataset_key == "openstack" and file_based_openstack:
        log.info("[openstack] using FILE-BASED labelling (matches run_full_pipeline)")
        return _label_by_source_filename
    label_path = data_dir / spec["extract_to"] / spec["label_file"]
    if not label_path.exists():
        raise FileNotFoundError(f"label file missing: {label_path}")
    if dataset_key == "openstack":
        flagged = load_openstack_labels(label_path)
    elif dataset_key == "hdfs":
        flagged = load_hdfs_labels(label_path)
    else:
        raise ValueError(f"no labeller for dataset {dataset_key!r}")
    log.info("[%s] %d flagged ids", dataset_key, len(flagged))
    return make_window_labeler(flagged)


def prepare_dataset(
    dataset_key: str,
    *,
    data_dir: Path,
    output_dir: Path,
    sample: int | None,
    rebuild: bool = False,
    resume: bool = False,
    file_based_openstack: bool = False,
) -> PreparedDataset:
    """Phase-1 worker: data_prep + windows + SBERT embed + 15% test split.

    Caches `embeddings.npy`, `labels.npy`, `test_idx.npy`,
    `drain3_state.bin` under `output_dir / dataset_key /`. Reruns are
    fast unless `rebuild=True`.
    """
    cache_dir = output_dir / "_inputs" / dataset_key
    cache_dir.mkdir(parents=True, exist_ok=True)
    embeddings_path = cache_dir / "embeddings.npy"
    labels_path = cache_dir / "labels.npy"
    test_idx_path = cache_dir / "test_idx.npy"
    drain3_state_path = cache_dir / "drain3_state.bin"

    if (
        not rebuild
        and embeddings_path.exists()
        and labels_path.exists()
        and test_idx_path.exists()
    ):
        log.info("[%s] using cached preprocessed data at %s", dataset_key, cache_dir)
        embeddings = np.load(embeddings_path)
        labels = np.load(labels_path)
        test_idx = np.load(test_idx_path)
    else:
        # 1. Parse -> ParsedLog list. With `file_based_openstack=True`
        # we need per-file source labels so the labeller can tell
        # abnormal files from normal ones.
        log.info("[%s] parsing through Drain3 (sample=%s)", dataset_key, sample)
        parsed = _parse_dataset_lines(
            dataset_key, data_dir, drain3_state_path, sample=sample,
            per_file_source=file_based_openstack and dataset_key == "openstack",
        )

        # 2. Build windows + apply per-dataset labeller
        labeller = _label_windows_for(
            dataset_key, data_dir,
            file_based_openstack=file_based_openstack,
        )
        windows = build_windows(parsed, label_fn=labeller)
        n_anom = sum(1 for w in windows if w.label == "anomaly")
        log.info(
            "[%s] %d windows | %d anomaly (%.1f%%)",
            dataset_key, len(windows), n_anom, n_anom / max(len(windows), 1) * 100,
        )

        # 3. SBERT embed (cached). Chunked + memmap'd in `embed.py` so
        # progress is logged per chunk and a kill is recoverable via
        # `--resume`.
        log.info("[%s] SBERT embedding (this is the slow step)", dataset_key)
        from sentence_transformers import SentenceTransformer
        sbert = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        embeddings = embed_or_load(
            windows, model=sbert, cache_path=embeddings_path,  # type: ignore[arg-type]
            resume=resume,
        )

        # 4. Persist labels
        labels = np.array(
            [1 if w.label == "anomaly" else 0 for w in windows], dtype=np.int64,
        )
        np.save(labels_path, labels)
        log.info("[%s] saved labels (%d positive / %d total)",
                 dataset_key, int(labels.sum()), labels.shape[0])

        # 5. 15% test split (TEST_SEED, independent of TRAINING_SEED=42)
        rng = np.random.default_rng(TEST_SEED)
        perm = rng.permutation(embeddings.shape[0])
        n_test = max(1, int(embeddings.shape[0] * TEST_FRACTION))
        test_idx = np.sort(perm[:n_test])
        np.save(test_idx_path, test_idx)
        log.info("[%s] test split: %d windows (seed=%d, fraction=%.2f)",
                 dataset_key, len(test_idx), TEST_SEED, TEST_FRACTION)

    # 6. Compute train_idx as the complement
    all_idx = np.arange(embeddings.shape[0])
    train_idx = np.setdiff1d(all_idx, test_idx, assume_unique=True)
    return PreparedDataset(
        name=dataset_key,
        embeddings=embeddings,
        labels=labels,
        test_idx=test_idx,
        train_idx=train_idx,
    )


# -- training a single model ------------------------------------------------


def train_one_model(
    name: str,
    *,
    train_embeddings: np.ndarray,
    train_labels: np.ndarray,
    output_dir: Path,
    drain3_state_src: Path,
    device: str = "cpu",
    sample_mode: bool = False,
    epochs_override: int | None = None,
    rebuild: bool = False,
) -> None:
    """Run transformer + AE + scoring + calibration end-to-end on the
    given (train+val) data. Writes every artifact under `output_dir`.

    Reuses the existing `run_full_pipeline.step_*` helpers so the
    saved-on-disk format (TorchScript bundles, metrics JSON files,
    cached score arrays) is byte-identical to what the original
    pipeline produced. The only difference is the input data — we
    pass the (train + val) slice rather than the full corpus."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("=" * 70)
    log.info("Training '%s' on %d windows (%.1f%% positive)",
             name, train_embeddings.shape[0], train_labels.mean() * 100)
    log.info("=" * 70)

    # Sanity check: AE needs enough normal data.
    n_normal = int((train_labels == 0).sum())
    if n_normal < 100:
        raise RuntimeError(
            f"[{name}] only {n_normal} normal windows in train+val — "
            "AE needs at least ~100. Did the labeller misfire?"
        )

    # 1. Transformer (writes transformer.pt + transformer_metrics.json).
    #    `rebuild=False` lets the underlying step_* helpers skip when a
    #    fresh artifact already exists on disk — important for resume
    #    after a kill, so we don't redo the 30-45 min training step
    #    when transformer.pt is already there.
    _step_train_transformer(
        train_embeddings.astype(np.float32),
        train_labels.astype(np.float32),
        artifact_dir=output_dir,
        device=device,
        rebuild=rebuild,
        sample_mode=sample_mode,
        epochs_override=epochs_override,
    )

    # 2. AutoEncoder (writes autoencoder.pt + autoencoder_metrics.json).
    #    train_autoencoder.train() filters internally to label==0 windows,
    #    so we pass the FULL labels — not pre-filtered.
    _step_train_ae(
        train_embeddings.astype(np.float32),
        train_labels.astype(np.float32),
        artifact_dir=output_dir,
        device=device,
        rebuild=rebuild,
        sample_mode=sample_mode,
        epochs_override=epochs_override,
    )

    # 3. Component scores on the train+val set (writes transformer_scores.npy
    #    + ae_errors.npy). These drive calibration.
    transformer_scores, ae_errors = _step_component_scores(
        train_embeddings.astype(np.float32),
        artifact_dir=output_dir,
        device=device,
        rebuild=rebuild,
    )

    # 4. Calibrate (writes thresholds.json + confidence_scorer.pt).
    #    Calibration uses the (train+val) corpus only — the held-out test
    #    set is excluded by construction since we never put those rows into
    #    train_embeddings.
    _step_calibrate(
        transformer_scores,
        ae_errors,
        train_labels.astype(np.float32),
        artifact_dir=output_dir,
        device=device,
    )

    # 5. Copy the corresponding Drain3 state file so the live runner can
    #    boot from this artifact dir without needing the _inputs/ tree.
    drain3_target = output_dir / "drain3_state.bin"
    if drain3_state_src.resolve() != drain3_target.resolve():
        shutil.copy2(drain3_state_src, drain3_target)
    log.info("[%s] artifacts written to %s", name, output_dir)


# -- evaluation -------------------------------------------------------------


@dataclass
class EvalCell:
    """One cell of the eval matrix — a model's score on a test set."""
    model_name: str
    test_set: str
    metrics: SplitMetrics


def eval_holdout(
    *,
    model_name: str,
    test_set: str,
    artifact_dir: Path,
    embeddings: np.ndarray,
    labels: np.ndarray,
    test_idx: np.ndarray,
) -> EvalCell:
    """Evaluate a single model on a held-out subset of an in-distribution
    dataset (OpenStack test or HDFS test)."""
    detector = Detector.from_artifacts(artifact_dir)
    thresholds = detector.thresholds

    # Score the test subset.
    e_test = embeddings[test_idx]
    y_test = labels[test_idx]
    n = e_test.shape[0]
    t_scores = np.empty(n, dtype=np.float32)
    ae_errs = np.empty(n, dtype=np.float32)
    batch = 256
    with torch.no_grad():
        x_all = torch.from_numpy(e_test).float()
        for start in range(0, n, batch):
            end = min(start + batch, n)
            x = x_all[start:end]
            t_out = detector._transformer(x)  # noqa: SLF001
            t_scores[start:end] = (
                torch.sigmoid(t_out["anomaly_logit"].squeeze(-1)).cpu().numpy()
            )
            pooled = x.mean(dim=1)
            recon = detector._autoencoder(pooled)  # noqa: SLF001
            ae_errs[start:end] = ((recon - pooled) ** 2).mean(dim=1).cpu().numpy()

    from ml.ensemble import combine, normalise_ae_error
    ae_norm = normalise_ae_error(
        ae_errs, p10=thresholds.ae_error_p10, p90=thresholds.ae_error_p90,
    )
    ensemble = combine(t_scores, ae_errs, thresholds=thresholds)

    confidence_scorer = detector._confidence  # noqa: SLF001
    confidences = compute_confidence(confidence_scorer, t_scores, ae_norm)

    metrics = metrics_for_split(
        test_set,
        indices=np.arange(n),  # already-sliced
        ensemble_scores=ensemble,
        confidences=confidences,
        labels=y_test.astype(np.int64),
        thresholds=thresholds,
    )
    return EvalCell(model_name=model_name, test_set=test_set, metrics=metrics)


def eval_apache(
    *,
    model_name: str,
    artifact_dir: Path,
    apache_log: Path,
    drain3_eval_state: Path,
    sample: int | None,
) -> EvalCell:
    """Score a single model on the full Apache corpus. Apache is never
    seen by training OR calibration of either model — the harshest
    cross-dataset test we have."""
    parsed = parse_apache(
        apache_log, drain3_state_out=drain3_eval_state, sample=sample,
    )
    windows = build_windows(parsed, label_fn=make_level_labeler())
    if not windows:
        raise RuntimeError("not enough Apache events to form a single window")
    truth = cross_label_windows(windows)

    # Embed Apache via SBERT — cached separately from training to avoid
    # contamination of the train embeddings file. `resume=True` is
    # always-on here: Apache embedding is an evaluation step, not a
    # source of truth, so it's always safe to pick up a partial cache
    # rather than restarting from scratch on every interrupted run.
    apache_emb_cache = drain3_eval_state.parent / "embeddings_apache.npy"
    from sentence_transformers import SentenceTransformer
    sbert = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    embeddings = embed_or_load(
        windows, model=sbert, cache_path=apache_emb_cache,  # type: ignore[arg-type]
        resume=True,
    )

    detector = Detector.from_artifacts(artifact_dir)
    pred = predict_anomalies(detector, embeddings)
    rep = cross_confusion(pred, truth)

    # Also compute AUC on the continuous ensemble score for symmetry.
    n = embeddings.shape[0]
    t_scores = np.empty(n, dtype=np.float32)
    ae_errs = np.empty(n, dtype=np.float32)
    with torch.no_grad():
        x_all = torch.from_numpy(embeddings).float()
        for start in range(0, n, 256):
            end = min(start + 256, n)
            x = x_all[start:end]
            t_out = detector._transformer(x)  # noqa: SLF001
            t_scores[start:end] = (
                torch.sigmoid(t_out["anomaly_logit"].squeeze(-1)).cpu().numpy()
            )
            pooled = x.mean(dim=1)
            recon = detector._autoencoder(pooled)  # noqa: SLF001
            ae_errs[start:end] = ((recon - pooled) ** 2).mean(dim=1).cpu().numpy()
    from ml.ensemble import combine
    ensemble = combine(t_scores, ae_errs, thresholds=detector.thresholds)
    auc = _auc_score(truth.astype(np.int64), ensemble)

    metrics = SplitMetrics(
        name="apache",
        n=rep.n_total_windows,
        n_positive=rep.n_positive_windows,
        n_negative=rep.n_negative_windows,
        f1=rep.f1, precision=rep.precision, recall=rep.recall, auc=auc,
        tp=rep.tp, fp=rep.fp, tn=rep.tn, fn=rep.fn,
    )
    return EvalCell(model_name=model_name, test_set="apache", metrics=metrics)


# -- writing the four results files ----------------------------------------


def _md_metrics_row(model_label: str, m: SplitMetrics) -> str:
    return (
        f"| {model_label} | {m.n:,} | {m.n_positive:,} ({m.positive_rate:.1%}) "
        f"| {m.f1:.3f} | {m.precision:.3f} | {m.recall:.3f} | {m.auc:.3f} |"
    )


def _md_confusion(label: str, m: SplitMetrics) -> str:
    return (
        f"### {label}\n\n"
        f"| | Predicted anomaly | Predicted normal |\n"
        f"|---|---:|---:|\n"
        f"| **Truly anomaly** | {m.tp:,} (TP) | {m.fn:,} (FN) |\n"
        f"| **Truly normal** | {m.fp:,} (FP) | {m.tn:,} (TN) |\n"
    )


def write_results_holdout(
    title: str,
    description: str,
    cell_a: EvalCell,
    cell_b: EvalCell,
    *,
    out_path: Path,
) -> None:
    """RESULTS_OPENSTACK_TEST.md and RESULTS_HDFS_TEST.md share this layout."""
    body = f"""# {title}

Auto-generated by `training/run_proper_eval.py`.

{description}

## Headline numbers

| Model | n | n positive | F1 | Precision | Recall | AUC |
|---|---:|---:|---:|---:|---:|---:|
{_md_metrics_row("OpenStack-only (Model A)", cell_a.metrics)}
{_md_metrics_row("Combined OpenStack+HDFS (Model B)", cell_b.metrics)}

## Confusion matrices

{_md_confusion("OpenStack-only (Model A)", cell_a.metrics)}
{_md_confusion("Combined OpenStack+HDFS (Model B)", cell_b.metrics)}

## Notes

- **Held-out test set** — this slice was excluded from BOTH gradient
  updates and threshold calibration (TEST_FRACTION = {TEST_FRACTION},
  TEST_SEED = {TEST_SEED}). Numbers above are an honest deploy-time
  estimate.
- **AUC** is threshold-independent: if AUC ≈ F1, the calibrated
  threshold isn't doing inflation work. If AUC < F1, the threshold
  is gating an underlying ranking that's worse than F1 suggests.
"""
    out_path.write_text(body, encoding="utf-8")
    log.info("[results] wrote %s", out_path)


def write_results_apache(
    cell_a: EvalCell, cell_b: EvalCell, *, out_path: Path,
) -> None:
    body = f"""# Cross-Dataset Evaluation — Apache (never seen)

Auto-generated by `training/run_proper_eval.py`.

Apache logs are excluded from BOTH models' training and calibration
data. This is the strongest generalisation claim — different
distribution, different vocabulary, different format. Labels are
log-level fallback (`[error] / [warn] / [fatal]` → anomaly), since
LogHub doesn't ship Apache anomaly labels.

## Headline numbers

| Model | n | n positive | F1 | Precision | Recall | AUC |
|---|---:|---:|---:|---:|---:|---:|
{_md_metrics_row("OpenStack-only (Model A)", cell_a.metrics)}
{_md_metrics_row("Combined OpenStack+HDFS (Model B)", cell_b.metrics)}

## Confusion matrices

{_md_confusion("OpenStack-only (Model A)", cell_a.metrics)}
{_md_confusion("Combined OpenStack+HDFS (Model B)", cell_b.metrics)}

## How to read this

The interesting question for the paper isn't "is F1 high" — Apache's
class balance is heavy on errors so accuracy/F1 is mechanical. It's
**whether Model B (which saw HDFS during training) generalises any
better to Apache than Model A (OpenStack-only) does**. Both models
are tested on the same Apache windows under identical conditions.
"""
    out_path.write_text(body, encoding="utf-8")
    log.info("[results] wrote %s", out_path)


def write_summary(cells: list[EvalCell], *, out_path: Path) -> None:
    """RESULTS_SUMMARY.md — the table the paper uses."""
    by_key: dict[tuple[str, str], EvalCell] = {
        (c.model_name, c.test_set): c for c in cells
    }

    def fmt(model: str, test: str, attr: str) -> str:
        cell = by_key.get((model, test))
        if cell is None:
            return "—"
        return f"{getattr(cell.metrics, attr):.3f}"

    body = f"""# Evaluation Summary

Auto-generated by `training/run_proper_eval.py`.

Both models trained with a proper 70 / 15 / 15 train / val / test
split (`TEST_FRACTION = {TEST_FRACTION}`, `TEST_SEED = {TEST_SEED}`).
Test slices for OpenStack and HDFS were excluded from training and
calibration; Apache was never seen by either model.

## F1 — head-to-head (paper table)

| | OpenStack test | HDFS test | Apache (never seen) |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | {fmt("openstack_only", "openstack_test", "f1")} | {fmt("openstack_only", "hdfs_test", "f1")} | {fmt("openstack_only", "apache", "f1")} |
| **Model B — Combined OS+HDFS** | {fmt("combined", "openstack_test", "f1")} | {fmt("combined", "hdfs_test", "f1")} | {fmt("combined", "apache", "f1")} |

## AUC — threshold-independent ranking quality

| | OpenStack test | HDFS test | Apache (never seen) |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | {fmt("openstack_only", "openstack_test", "auc")} | {fmt("openstack_only", "hdfs_test", "auc")} | {fmt("openstack_only", "apache", "auc")} |
| **Model B — Combined OS+HDFS** | {fmt("combined", "openstack_test", "auc")} | {fmt("combined", "hdfs_test", "auc")} | {fmt("combined", "apache", "auc")} |

## Precision / Recall

| | Test set | Precision | Recall |
|---|---|---:|---:|
| Model A — OpenStack-only | OpenStack | {fmt("openstack_only", "openstack_test", "precision")} | {fmt("openstack_only", "openstack_test", "recall")} |
| Model A — OpenStack-only | HDFS | {fmt("openstack_only", "hdfs_test", "precision")} | {fmt("openstack_only", "hdfs_test", "recall")} |
| Model A — OpenStack-only | Apache | {fmt("openstack_only", "apache", "precision")} | {fmt("openstack_only", "apache", "recall")} |
| Model B — Combined OS+HDFS | OpenStack | {fmt("combined", "openstack_test", "precision")} | {fmt("combined", "openstack_test", "recall")} |
| Model B — Combined OS+HDFS | HDFS | {fmt("combined", "hdfs_test", "precision")} | {fmt("combined", "hdfs_test", "recall")} |
| Model B — Combined OS+HDFS | Apache | {fmt("combined", "apache", "precision")} | {fmt("combined", "apache", "recall")} |

## Reading guide

- **OpenStack test** is the in-distribution headline number for each model.
- **HDFS test** measures generalisation for Model A (HDFS unseen) and
  in-distribution performance for Model B (HDFS in training).
- **Apache** is the cross-dataset robustness check for both models —
  Apache was never in either training corpus.
- Look for `Combined ≥ OpenStack-only` on every cell. If Model B is
  worse on OpenStack-test (negative transfer), retrain B with a
  bigger model or more epochs. If Model B is much better on Apache,
  the multi-dataset training generalises and the paper claim is
  real.
"""
    out_path.write_text(body, encoding="utf-8")
    log.info("[results] wrote %s", out_path)


# -- F1 floor check --------------------------------------------------------


def check_f1_floor(cells: list[EvalCell], floor: float) -> list[str]:
    """Return a list of failure descriptions, empty if all pass."""
    failures = []
    for c in cells:
        if c.metrics.f1 < floor:
            failures.append(
                f"  {c.model_name} on {c.test_set}: F1 = {c.metrics.f1:.3f} < {floor:.2f}"
            )
    return failures


# -- smoke-test helpers ----------------------------------------------------


def _hdfs_data_present(data_dir: Path) -> bool:
    """Cheap probe: is the HDFS dataset downloaded on this machine?

    We accept either an extracted log file or a downloadable archive
    (the latter would auto-extract on first use). Used by smoke mode to
    decide whether to run the full OS+HDFS pipeline or fall back to
    OS-only when HDFS hasn't been fetched yet — smoke is a pipeline
    smoke test, not a data-acquisition test.
    """
    spec = DATASETS["hdfs"]
    extracted = data_dir / spec["extract_to"]
    if extracted.exists() and any(
        (extracted / f).exists() for f in spec["log_files"]
    ):
        return True
    archive = data_dir / spec["archive"]
    return archive.exists() and archive.stat().st_size > 0


def _smoke_check(t0: float, phase: str) -> None:
    """Smoke-mode time-budget gate. Called after every major phase so a
    regression that makes the pipeline 5x slower is loud, not silent.

    Raises AssertionError if elapsed exceeds SMOKE_TIMEOUT_S — the
    blast-radius is small (we lose a smoke run, never a real one) and
    the assertion message tells the user where the budget blew up.
    """
    elapsed = time.monotonic() - t0
    assert elapsed < SMOKE_TIMEOUT_S, (
        f"smoke test exceeded {SMOKE_TIMEOUT_S:.0f}s budget at end of "
        f"phase '{phase}' (elapsed {elapsed:.1f}s). investigate "
        f"before running the full pipeline."
    )


# -- main orchestrator -----------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Proper evaluation: 70/15/15 split, two trainings, three test sets.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--openstack-sample", type=int, default=None,
        help="Use only the first N OpenStack lines (fast iteration).",
    )
    parser.add_argument(
        "--hdfs-sample", type=int, default=None,
        help="Use only the first N HDFS lines (fast iteration).",
    )
    parser.add_argument(
        "--apache-sample", type=int, default=None,
        help="Use only the first N Apache lines (fast iteration).",
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="Force re-preprocessing (ignore cached embeddings).",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help=(
            "Resume embedding from the last completed chunk if a "
            "previous run was killed. Reads the `.progress` sidecar "
            "next to each cached embeddings.npy."
        ),
    )
    parser.add_argument(
        "--f1-floor", type=float, default=DEFAULT_F1_FLOOR,
        help=("Stop and report if any held-out F1 falls below this. "
              "Pass 0.0 to accept whatever falls out."),
    )
    parser.add_argument(
        "--device", choices=["cpu", "cuda"], default="cpu",
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help=(
            "Smoke-test mode: tiny samples, 2 epochs, skip Apache, "
            f"output to {SMOKE_OUTPUT_DIR}/, hard {SMOKE_TIMEOUT_S:.0f}s "
            "timeout. Validates the whole pipeline end-to-end in 2-4 min "
            "on a CPU laptop; models trained this way are NOT useful, "
            "only diagnostic."
        ),
    )
    parser.add_argument(
        "--instance-id-labels", action="store_true",
        help=(
            "Use OpenStack's instance-id labels from anomaly_labels.txt "
            "instead of the file-based default. CURRENTLY BROKEN: produces "
            "0 anomaly windows on the full 207k corpus (likely a UUID "
            "regex / format mismatch). Kept as an opt-in for when the "
            "labeller bug is fixed. Ignored in --smoke mode (smoke always "
            "uses file-based labels)."
        ),
    )
    args = parser.parse_args(argv)

    # Windows cmd defaults to cp1252 which can't encode the unicode
    # arrows we use in log messages. Force the std streams to UTF-8 so
    # `python -m training.run_proper_eval` works from a vanilla cmd
    # window OR a piped/captured stdout. errors="replace" ensures even
    # surprise glyphs degrade gracefully instead of crashing the run.
    for _stream in (sys.stdout, sys.stderr):
        try:
            if _stream.encoding != "utf-8":
                _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    # Smoke mode reshapes the rest of the args before they're consumed.
    # Anything the user passed on the CLI that smoke would override is
    # silently replaced — this is intentional, smoke is meant to be a
    # one-flag short-circuit to "validate that the pipeline runs".
    if args.smoke:
        args.output_dir = SMOKE_OUTPUT_DIR
        args.openstack_sample = SMOKE_SAMPLE
        args.hdfs_sample = SMOKE_SAMPLE
        args.apache_sample = SMOKE_SAMPLE  # not used (Apache is skipped)
        args.f1_floor = 0.0  # smoke models are diagnostic only
        args.rebuild = True  # always start from clean memmaps

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    output_dir: Path = args.output_dir.resolve()
    data_dir: Path = args.data_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("output → %s", output_dir)
    log.info("data   → %s", data_dir)

    t0 = time.monotonic()
    epochs_override = SMOKE_EPOCHS if args.smoke else None

    # Smoke mode: if HDFS isn't downloaded on this machine, fall back
    # to OS-only smoke. Real (non-smoke) runs still trigger the auto-
    # download — those have a 60-min budget and nobody's expecting them
    # to finish in 90 seconds.
    skip_hdfs = False
    if args.smoke and not _hdfs_data_present(data_dir):
        skip_hdfs = True
        log.warning(
            "[smoke] HDFS not downloaded — running OS-only smoke. "
            "Combined model code path will not be exercised. To get "
            "full smoke coverage, fetch HDFS first via "
            "`python -m training.data_prep --dataset hdfs --download`."
        )

    # OpenStack labelling: file-based by default.
    #
    # The LogHub OpenStack release ships with three log files —
    # `openstack_normal1.log`, `openstack_normal2.log`,
    # `openstack_abnormal.log` — and the LogHub convention is that
    # every event from `*_abnormal.log` belongs to the anomaly class.
    # The same convention is used by `run_full_pipeline.py`, which
    # produced the committed F1=1.000 baseline in `training/RESULTS.md`.
    #
    # The alternative — instance-id matching against the UUIDs listed
    # in `anomaly_labels.txt` — is currently BROKEN: a label-overlap
    # diagnostic on the full 207k-event corpus shows it produces zero
    # positive windows (likely a UUID-extraction format mismatch
    # between `_UUID_RE` and the actual OpenStack log format). Pass
    # `--instance-id-labels` to opt back in once that bug is fixed.
    #
    # Smoke always forces file-based regardless of the flag — its
    # 200-line samples can't possibly contain matching instance IDs
    # so instance-id labelling would just produce a useless 0-positive
    # corpus and crash calibration.
    file_based_os = args.smoke or not args.instance_id_labels

    # ---- Phase 1: prepare both labelled datasets -------------------------
    log.info("PHASE 1 — preparing OpenStack")
    os_data = prepare_dataset(
        "openstack",
        data_dir=data_dir,
        output_dir=output_dir,
        sample=args.openstack_sample,
        rebuild=args.rebuild,
        resume=args.resume,
        file_based_openstack=file_based_os,
    )
    if args.smoke:
        _smoke_check(t0, "phase 1 OpenStack")

    hdfs_data: PreparedDataset | None = None
    if not skip_hdfs:
        log.info("PHASE 1 — preparing HDFS")
        hdfs_data = prepare_dataset(
            "hdfs",
            data_dir=data_dir,
            output_dir=output_dir,
            sample=args.hdfs_sample,
            rebuild=args.rebuild,
            resume=args.resume,
        )
        if args.smoke:
            _smoke_check(t0, "phase 1 HDFS")

    # ---- Phase 2: Model A (OpenStack-only) -------------------------------
    log.info("PHASE 2 — training Model A (OpenStack-only)")
    os_train_emb, os_train_lab = os_data.slice(os_data.train_idx)
    train_one_model(
        "openstack_only",
        train_embeddings=os_train_emb,
        train_labels=os_train_lab,
        output_dir=output_dir / "openstack_only",
        drain3_state_src=output_dir / "_inputs" / "openstack" / "drain3_state.bin",
        device=args.device,
        epochs_override=epochs_override,
        rebuild=args.rebuild,
    )
    if args.smoke:
        _smoke_check(t0, "phase 2")

    # ---- Phase 3: Model B (Combined OS+HDFS) -----------------------------
    if hdfs_data is None:
        log.info("PHASE 3 — skipped (HDFS not available, OS-only smoke)")
    else:
        _phase3_combined(
            os_train_emb=os_train_emb,
            os_train_lab=os_train_lab,
            hdfs_data=hdfs_data,
            output_dir=output_dir,
            data_dir=data_dir,
            args=args,
            epochs_override=epochs_override,
        )
    if args.smoke:
        _smoke_check(t0, "phase 3")

    # ---- Phase 4: evaluate both models on three test sets ---------------
    log.info("PHASE 4 — evaluating both models on test sets")
    cells: list[EvalCell] = []
    model_names = ("openstack_only",) if hdfs_data is None else ("openstack_only", "combined")
    for model_name in model_names:
        artifact_dir = output_dir / model_name
        # OpenStack held-out
        cells.append(eval_holdout(
            model_name=model_name, test_set="openstack_test",
            artifact_dir=artifact_dir,
            embeddings=os_data.embeddings, labels=os_data.labels,
            test_idx=os_data.test_idx,
        ))
        # HDFS held-out — only when we actually have HDFS data
        if hdfs_data is not None:
            cells.append(eval_holdout(
                model_name=model_name, test_set="hdfs_test",
                artifact_dir=artifact_dir,
                embeddings=hdfs_data.embeddings, labels=hdfs_data.labels,
                test_idx=hdfs_data.test_idx,
            ))
        # Apache (full) — skipped in smoke mode (saves ~30 s, doesn't
        # validate any code path that the OS / HDFS holdout doesn't).
        if not args.smoke:
            apache_log = data_dir / "apache" / "Apache.log"
            cells.append(eval_apache(
                model_name=model_name, artifact_dir=artifact_dir,
                apache_log=apache_log,
                drain3_eval_state=output_dir / "_inputs" / "apache_eval_drain3.bin",
                sample=args.apache_sample,
            ))
    if args.smoke:
        _smoke_check(t0, "phase 4")

    for c in cells:
        log.info(
            "[eval] %s × %s: F1=%.3f P=%.3f R=%.3f AUC=%.3f",
            c.model_name, c.test_set, c.metrics.f1, c.metrics.precision,
            c.metrics.recall, c.metrics.auc,
        )

    # ---- Phase 5: F1 floor check ---------------------------------------
    failures = check_f1_floor(cells, args.f1_floor)
    if failures:
        log.error("=" * 70)
        log.error("F1 FLOOR FAILURE (--f1-floor %.2f)", args.f1_floor)
        for f in failures:
            log.error("%s", f)
        log.error("Stopping before writing summary — investigate the merge logic.")
        log.error("Pass --f1-floor 0.0 to suppress this and write results anyway.")
        log.error("=" * 70)
        # Still write the per-test-set files so the user can see what happened.
        _write_all_results(cells, output_dir)
        return 2

    # ---- Phase 6: write all four results files -------------------------
    _write_all_results(cells, output_dir)

    elapsed = time.monotonic() - t0
    log.info("=" * 70)
    log.info("DONE in %.1f min — see %s/RESULTS_SUMMARY.md", elapsed / 60, output_dir)
    log.info("=" * 70)
    return 0


def _phase3_combined(
    *,
    os_train_emb: np.ndarray,
    os_train_lab: np.ndarray,
    hdfs_data: PreparedDataset,
    output_dir: Path,
    data_dir: Path,
    args: argparse.Namespace,
    epochs_override: int | None,
) -> None:
    """Phase 3 body extracted so smoke mode can skip it cleanly when
    HDFS data isn't present. No behaviour change vs the original
    inline block."""
    log.info("PHASE 3 — training Model B (Combined)")
    hd_train_emb, hd_train_lab = hdfs_data.slice(hdfs_data.train_idx)
    combined_emb = np.concatenate([os_train_emb, hd_train_emb], axis=0)
    combined_lab = np.concatenate([os_train_lab, hd_train_lab], axis=0)
    log.info("[combined] %d windows total (OS=%d, HDFS=%d), %.1f%% positive",
             combined_emb.shape[0], os_train_emb.shape[0], hd_train_emb.shape[0],
             combined_lab.mean() * 100)

    # The combined Drain3 state is the union — extend the OS state with
    # the HDFS templates by re-running parse_log_file on HDFS into a copy
    # of the OS state file. This costs one extra Drain3 pass but avoids
    # diverging from the runtime behaviour the production runner sees.
    combined_drain3 = output_dir / "combined" / "drain3_state.bin"
    combined_drain3.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        output_dir / "_inputs" / "openstack" / "drain3_state.bin",
        combined_drain3,
    )
    log.info("[combined] extending Drain3 state with HDFS templates")
    spec = DATASETS["hdfs"]
    hdfs_log_paths = [data_dir / spec["extract_to"] / f for f in spec["log_files"]]
    if args.hdfs_sample is not None:
        hdfs_log_paths = [
            p.with_suffix(f".sample-{args.hdfs_sample}.log") for p in hdfs_log_paths
        ]
    parse_log_file(hdfs_log_paths, drain3_state_out=combined_drain3, source_label="hdfs")

    train_one_model(
        "combined",
        train_embeddings=combined_emb,
        train_labels=combined_lab,
        output_dir=output_dir / "combined",
        drain3_state_src=combined_drain3,
        device=args.device,
        epochs_override=epochs_override,
        rebuild=args.rebuild,
    )


def _write_all_results(cells: list[EvalCell], output_dir: Path) -> None:
    by_key = {(c.model_name, c.test_set): c for c in cells}

    write_results_holdout(
        "Held-Out OpenStack Test",
        "Both models scored on the 15 % OpenStack slice that was "
        "EXCLUDED from training AND calibration. This is the legitimate "
        "in-distribution generalisation number for both models.",
        cell_a=by_key[("openstack_only", "openstack_test")],
        cell_b=by_key[("combined", "openstack_test")],
        out_path=output_dir / "RESULTS_OPENSTACK_TEST.md",
    )
    write_results_holdout(
        "Held-Out HDFS Test",
        "Both models scored on the 15 % HDFS slice that was EXCLUDED "
        "from training AND calibration. For Model A (OpenStack-only) this "
        "is fully cross-dataset since HDFS was never in its training set.",
        cell_a=by_key[("openstack_only", "hdfs_test")],
        cell_b=by_key[("combined", "hdfs_test")],
        out_path=output_dir / "RESULTS_HDFS_TEST.md",
    )
    # Apache eval is skipped in smoke mode, so the cells may not exist.
    # Don't fail the smoke run just because there's no Apache result.
    if ("openstack_only", "apache") in by_key and ("combined", "apache") in by_key:
        write_results_apache(
            cell_a=by_key[("openstack_only", "apache")],
            cell_b=by_key[("combined", "apache")],
            out_path=output_dir / "RESULTS_APACHE.md",
        )
    write_summary(cells, out_path=output_dir / "RESULTS_SUMMARY.md")

    # Persist the raw numbers as JSON too — handy for re-rendering tables
    # without re-running the eval.
    snapshot = {
        f"{c.model_name}|{c.test_set}": {
            "n": c.metrics.n,
            "n_positive": c.metrics.n_positive,
            "f1": c.metrics.f1, "precision": c.metrics.precision,
            "recall": c.metrics.recall, "auc": c.metrics.auc,
            "tp": c.metrics.tp, "fp": c.metrics.fp,
            "tn": c.metrics.tn, "fn": c.metrics.fn,
        }
        for c in cells
    }
    (output_dir / "results_snapshot.json").write_text(
        json.dumps(snapshot, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
