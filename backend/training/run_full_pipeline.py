"""
Single-command orchestrator for the offline training pipeline (Step 3).

    python -m training.run_full_pipeline --dataset openstack [--full | --sample N]

What it does, in order. Each step skips itself if its output is already
fresh on disk — re-runs are cheap. Pass `--rebuild <step>` to force any
step regardless.

  1. data_prep    → `artifacts/drain3_state.bin` + parsed events list
  2. windows      → sliding windows + per-window labels (in-memory)
  3. embed        → `artifacts/embeddings_<dataset>.npy`
                  → `artifacts/labels_<dataset>.npy`
                  → `artifacts/windows_<dataset>.jsonl` (per-window manifest)
  4. transformer  → `artifacts/transformer.pt`
                  → `artifacts/transformer_metrics.json`
  5. autoencoder  → `artifacts/autoencoder.pt`
                  → `artifacts/autoencoder_metrics.json`
  6. component scores  → `artifacts/transformer_scores.npy`
                       → `artifacts/ae_errors.npy`
  7. calibrate    → `artifacts/thresholds.json`
                  → `artifacts/confidence_scorer.pt`
  8. faiss        → `artifacts/faiss.index`
                  → `artifacts/incidents.jsonl`
  9. RESULTS.md   → top-line table populated with the run's numbers

CPU laptop time on full OpenStack: ~3 hours, dominated by SBERT embedding
and Transformer training. Run once overnight; subsequent re-runs use the
cached embeddings and finish in minutes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from training.calibrate import calibrate
from training.data_prep import DATASETS, parse_log_file
from training.embed import embed_or_load
from training.sequence_builder import ParsedLog, Window, build_windows
from training.train_autoencoder import (
    TrainConfig as AETrainConfig,
)
from training.train_autoencoder import (
    save_torchscript as save_ae_torchscript,
)
from training.train_autoencoder import (
    train as train_autoencoder,
)
from training.train_transformer import (
    TrainConfig as TransformerTrainConfig,
)
from training.train_transformer import (
    save_torchscript as save_transformer_torchscript,
)
from training.train_transformer import (
    train as train_transformer,
)

# -- Helpers ---------------------------------------------------------------

def _stamp(msg: str) -> None:
    print(f"\n{'=' * 60}\n  {msg}\n{'=' * 60}")


def _exists_and_fresh(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _save_window_manifest(windows: list[Window], dest: Path) -> None:
    """Persist a per-window manifest used by build_faiss to recover template
    text for training-anomaly index records."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for w in windows:
            f.write(json.dumps({
                "window_id": w.window_id,
                "label": w.label,
                "template_preview": w.templates[len(w.templates) // 2],
                "source": w.source,
                "line_range": list(w.line_range),
            }) + "\n")


def _load_window_manifest(src: Path) -> list[dict]:
    out: list[dict] = []
    with src.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line:
                out.append(json.loads(line))
    return out


# -- Pipeline steps --------------------------------------------------------

def step_data_prep(
    *, dataset: str, data_dir: Path, artifact_dir: Path, sample: int | None,
    rebuild: bool,
) -> list[ParsedLog]:
    """Drain3-parse every line in the dataset's log files. Returns the
    flattened ParsedLog stream."""
    _stamp(f"STEP 1 — data prep ({dataset})")
    spec = DATASETS[dataset]
    drain3_state = artifact_dir / "drain3_state.bin"

    log_paths = [data_dir / dataset / lf for lf in spec["log_files"]]
    missing = [p for p in log_paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Raw log files not found:\n  "
            + "\n  ".join(str(m) for m in missing)
            + f"\nDownload first: python -m training.data_prep --dataset {dataset} --download"
        )

    if rebuild and drain3_state.exists():
        drain3_state.unlink()

    if sample is not None:
        # Take only the first `sample` lines from each file by streaming a temp
        # file. Cheap for fast-iteration mode. We KEEP the original filename
        # in the temp name (`_sample_<basename>`) so the per-file source tag
        # below still carries the "abnormal" / "normal" hint.
        sampled_paths: list[Path] = []
        for p in log_paths:
            tmp = artifact_dir / f"_sample_{p.name}"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with p.open("r", encoding="utf-8", errors="replace") as src, \
                 tmp.open("w", encoding="utf-8") as dst:
                for i, line in enumerate(src):
                    if i >= sample:
                        break
                    dst.write(line)
            sampled_paths.append(tmp)
        log_paths = sampled_paths

    # Process each file separately so each ParsedLog gets a source tag of the
    # filename. LogHub's OpenStack release uses FILE-based labels (lines from
    # `openstack_abnormal.log` are anomalies; the two `openstack_normal*.log`
    # files are normal) — there's no separate `anomaly_labels.txt`. The
    # labeller in step_windows looks for "abnormal" in `ev.source` to decide
    # the window label. Drain3 state accumulates across files via FilePersistence.
    all_events: list[ParsedLog] = []
    line_offset = 0
    for log_path in log_paths:
        # `Path.stem` strips the .log so source becomes e.g. "openstack_abnormal"
        # or "_sample_openstack_abnormal" in sample mode.
        events = parse_log_file(
            [log_path],
            drain3_state_out=drain3_state,
            source_label=log_path.stem,
        )
        # Re-number line_no globally so windows have unique line ranges.
        for ev in events:
            ev.line_no += line_offset
        all_events.extend(events)
        line_offset += len(events)
    return all_events


def step_windows(
    events: list[ParsedLog], *,
    dataset: str, data_dir: Path,
) -> list[Window]:
    """Apply the dataset-specific labeller and emit sliding windows.

    Two labelling strategies, picked by dataset:

    * **OpenStack** uses file-based labels (LogHub's standard layout):
      events whose source filename contains "abnormal" are anomalies, the
      rest are normal. A window is "anomaly" if ANY of its 20 events came
      from an abnormal file — boundary windows that straddle the
      normal→abnormal transition are correctly flagged.

    * **Apache** has no separate label file in LogHub. Fall back to a
      log-level heuristic (lines containing ERROR/WARN/FATAL → positive).
    """
    _stamp(f"STEP 2 — windowing ({dataset})")
    if dataset == "openstack":
        def _label_by_source(chunk: list[ParsedLog]):
            return "anomaly" if any(
                "abnormal" in ev.source.lower() for ev in chunk
            ) else "normal"
        labeller = _label_by_source
        print("[labels] OpenStack: anomaly = any event sourced from *_abnormal.log")
    else:
        # Apache: log-level fallback — lines containing ERROR/WARN/FATAL are
        # treated as positive class.
        def _label_by_log_level(chunk: list[ParsedLog]):
            return "anomaly" if any(
                lvl in ev.raw for ev in chunk for lvl in (" ERROR ", " WARN ", " FATAL ")
            ) else "normal"
        labeller = _label_by_log_level
        print(f"[labels] {dataset}: log-level heuristic (ERROR/WARN/FATAL → anomaly)")

    windows = build_windows(events, label_fn=labeller)
    n_anom = sum(1 for w in windows if w.label == "anomaly")
    print(
        f"[windows] {len(windows):,} total | {n_anom:,} anomaly "
        f"({n_anom / max(len(windows), 1) * 100:.1f}%)"
    )
    return windows


def step_embed_and_label(
    windows: list[Window], *,
    dataset: str, artifact_dir: Path, rebuild: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Run SBERT (cached) and persist labels + window manifest."""
    _stamp(f"STEP 3 — embedding ({dataset})")
    embeddings_path = artifact_dir / f"embeddings_{dataset}.npy"
    labels_path = artifact_dir / f"labels_{dataset}.npy"
    manifest_path = artifact_dir / f"windows_{dataset}.jsonl"

    if rebuild:
        for p in (embeddings_path, labels_path, manifest_path):
            if p.exists():
                p.unlink()

    # Lazy import — only this step needs SBERT, and importing it is slow.
    from sentence_transformers import SentenceTransformer
    print("[embed] loading all-MiniLM-L6-v2 (downloads ~80 MB on first use)…")
    sbert = SentenceTransformer("all-MiniLM-L6-v2")
    # mypy: SentenceTransformer.encode has many more overload params than our
    # SBertLike protocol; the runtime call is fine but the type check is too strict.
    embeddings = embed_or_load(windows, model=sbert, cache_path=embeddings_path)  # type: ignore[arg-type]

    labels = np.array(
        [1 if w.label == "anomaly" else 0 for w in windows], dtype=np.int64,
    )
    np.save(labels_path, labels)
    _save_window_manifest(windows, manifest_path)
    print(f"[embed] saved labels {labels_path.name} | manifest {manifest_path.name}")
    return embeddings, labels


def step_train_transformer(
    embeddings: np.ndarray, labels: np.ndarray, *,
    artifact_dir: Path, device: str, rebuild: bool, sample_mode: bool,
    epochs_override: int | None = None,
) -> dict:
    """Train + save the transformer head.

    `epochs_override` lets a caller force a specific epoch budget — used
    by the smoke test in `run_proper_eval.py` (epochs=2, finishes in
    seconds). If unset, defaults to 5 in sample_mode and 30 otherwise.
    """
    _stamp("STEP 4 — train transformer")
    out = artifact_dir / "transformer.pt"
    metrics_out = artifact_dir / "transformer_metrics.json"

    if not rebuild and _exists_and_fresh(out) and _exists_and_fresh(metrics_out):
        print(f"[skip] {out} fresh — pass --rebuild transformer to retrain")
        with metrics_out.open("r", encoding="utf-8") as f:
            return json.load(f)

    if epochs_override is not None:
        epochs = epochs_override
    elif sample_mode:
        epochs = 5
    else:
        epochs = 30
    config = TransformerTrainConfig(
        epochs=epochs,
        batch_size=64,
    )
    model, metrics = train_transformer(
        embeddings.astype(np.float32),
        labels.astype(np.float32),
        config=config,
        device=device,
    )
    save_transformer_torchscript(model, out)
    with metrics_out.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def step_train_autoencoder(
    embeddings: np.ndarray, labels: np.ndarray, *,
    artifact_dir: Path, device: str, rebuild: bool, sample_mode: bool,
    epochs_override: int | None = None,
) -> dict:
    """Train + save the AE. `epochs_override` mirrors the transformer
    helper for smoke runs."""
    _stamp("STEP 5 — train autoencoder")
    out = artifact_dir / "autoencoder.pt"
    metrics_out = artifact_dir / "autoencoder_metrics.json"

    if not rebuild and _exists_and_fresh(out) and _exists_and_fresh(metrics_out):
        print(f"[skip] {out} fresh")
        with metrics_out.open("r", encoding="utf-8") as f:
            return json.load(f)

    if epochs_override is not None:
        epochs = epochs_override
    elif sample_mode:
        epochs = 10
    else:
        epochs = 50
    config = AETrainConfig(
        epochs=epochs,
        batch_size=256,
    )
    model, metrics = train_autoencoder(
        embeddings.astype(np.float32),
        labels.astype(np.float32),
        config=config,
        device=device,
    )
    save_ae_torchscript(model, out)
    with metrics_out.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return metrics


def step_component_scores(
    embeddings: np.ndarray, *,
    artifact_dir: Path, device: str, rebuild: bool,
) -> tuple[np.ndarray, np.ndarray]:
    """Run both trained models over all embeddings and cache the per-window
    component scores so calibration's grid search is fast."""
    _stamp("STEP 6 — compute component scores")
    transformer_scores_path = artifact_dir / "transformer_scores.npy"
    ae_errors_path = artifact_dir / "ae_errors.npy"

    if (
        not rebuild
        and _exists_and_fresh(transformer_scores_path)
        and _exists_and_fresh(ae_errors_path)
    ):
        print("[skip] component scores cached")
        return np.load(transformer_scores_path), np.load(ae_errors_path)

    transformer = torch.jit.load(str(artifact_dir / "transformer.pt"), map_location=device).eval()
    autoencoder = torch.jit.load(str(artifact_dir / "autoencoder.pt"), map_location=device).eval()

    n = embeddings.shape[0]
    t_scores = np.empty(n, dtype=np.float32)
    ae_errs = np.empty(n, dtype=np.float32)
    batch = 256
    x_all = torch.from_numpy(embeddings).float()
    with torch.no_grad():
        for start in range(0, n, batch):
            end = min(start + batch, n)
            x = x_all[start:end].to(device)
            t_out = transformer(x)
            t_scores[start:end] = (
                torch.sigmoid(t_out["anomaly_logit"].squeeze(-1)).cpu().numpy()
            )
            pooled = x.mean(dim=1)
            recon = autoencoder(pooled)
            ae_errs[start:end] = ((recon - pooled) ** 2).mean(dim=1).cpu().numpy()
    np.save(transformer_scores_path, t_scores)
    np.save(ae_errors_path, ae_errs)
    print(f"[scores] saved {transformer_scores_path.name} {ae_errors_path.name}")
    return t_scores, ae_errs


def step_calibrate(
    transformer_scores: np.ndarray, ae_errors: np.ndarray, labels: np.ndarray, *,
    artifact_dir: Path, device: str,
) -> dict:
    _stamp("STEP 7 — calibrate ensemble")
    metrics = calibrate(
        transformer_scores, ae_errors, labels.astype(np.float32),
        thresholds_out=artifact_dir / "thresholds.json",
        confidence_out=artifact_dir / "confidence_scorer.pt",
        device=device,
    )
    return metrics


def step_build_faiss(
    embeddings: np.ndarray, labels: np.ndarray, *,
    dataset: str, artifact_dir: Path, project_root: Path,
) -> dict:
    _stamp("STEP 8 — build FAISS index")
    from training.build_faiss import (
        build_full_index,
        build_index_from_synthetic,
        build_index_from_training_anomalies,
        load_synthetic_incidents,
        save_index,
        save_records,
    )
    manifest = _load_window_manifest(artifact_dir / f"windows_{dataset}.jsonl")
    train_vec, train_rec = build_index_from_training_anomalies(embeddings, labels, manifest)

    synthetic_path = project_root / "training" / "synthetic_incidents.jsonl"
    synthetic = load_synthetic_incidents(synthetic_path)

    from sentence_transformers import SentenceTransformer
    sbert = SentenceTransformer("all-MiniLM-L6-v2")
    syn_vec, syn_rec = build_index_from_synthetic(synthetic, embedder=sbert)  # type: ignore[arg-type]

    index, records = build_full_index(
        training_vectors=train_vec, training_records=train_rec,
        synthetic_vectors=syn_vec, synthetic_records=syn_rec,
    )
    save_index(index, artifact_dir / "faiss.index")
    save_records(records, artifact_dir / "incidents.jsonl")
    print(f"[faiss] {index.ntotal:,} entries indexed "
          f"({len(train_rec)} training + {len(syn_rec)} synthetic)")
    return {
        "n_training": len(train_rec),
        "n_synthetic": len(syn_rec),
        "n_total": index.ntotal,
    }


def step_write_results(
    *, dataset: str, sample: int | None,
    artifact_dir: Path, project_root: Path,
    transformer_metrics: dict,
    autoencoder_metrics: dict,
    calibration_metrics: dict,
    faiss_metrics: dict,
) -> None:
    _stamp("STEP 9 — write RESULTS.md")
    results_path = project_root / "training" / "RESULTS.md"
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sample_label = f"{sample:,} lines per file" if sample else "full"

    e = calibration_metrics["ensemble"]
    c = calibration_metrics["confidence"]
    body = f"""# AIOps-LogGuard — Training Results

Auto-generated by `training/run_full_pipeline.py`.

- Dataset: **{dataset}**
- Run timestamp: {ts}
- Sample size: {sample_label}
- Window size / stride: 20 / 1

## Transformer (anomaly classifier head)

| Metric | Value |
|---|---|
| Best validation F1 | {transformer_metrics.get('best_val_f1', 0):.3f} |
| Best validation precision | {transformer_metrics.get('best_val_precision', 0):.3f} |
| Best validation recall | {transformer_metrics.get('best_val_recall', 0):.3f} |
| Epochs run | {transformer_metrics.get('epochs_run', '—')} / {transformer_metrics.get('config', {}).get('epochs', '—')} |

## AutoEncoder (reconstruction)

| Metric | Value |
|---|---|
| Best validation MSE | {autoencoder_metrics.get('best_val_loss', 0):.5f} |
| Epochs run | {autoencoder_metrics.get('epochs_run', '—')} / {autoencoder_metrics.get('config', {}).get('epochs', '—')} |
| Trained on | {autoencoder_metrics.get('n_normal_windows', 0):,} normal windows / {autoencoder_metrics.get('n_total_windows', 0):,} total |

## Ensemble (calibrated)

| Param | Value |
|---|---|
| w1 (transformer) | {e['w1']:.3f} |
| w2 (autoencoder) | {e['w2']:.3f} |
| Anomaly threshold | {e['anomaly_threshold']:.3f} |
| Confidence threshold | {c['threshold']:.3f} |
| Validation F1 | {e['f1']:.3f} |
| Validation precision | {e['precision']:.3f} |
| Validation recall | {e['recall']:.3f} |

## RAG seed

| Source | Count |
|---|---|
| Real anomalies indexed | {faiss_metrics['n_training']:,} |
| Hand-written synthetic incidents | {faiss_metrics['n_synthetic']} |
| Total FAISS entries | {faiss_metrics['n_total']:,} |
"""
    results_path.write_text(body, encoding="utf-8")
    print(f"[results] {results_path}")


# -- CLI -------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full offline training pipeline end-to-end.",
    )
    parser.add_argument(
        "--dataset", choices=sorted(DATASETS), required=True,
        help="Primary dataset (openstack=train+eval, apache=cross-dataset only).",
    )
    parser.add_argument(
        "--sample", type=int, default=None,
        help="Use only the first N lines of each log file (fast iteration mode).",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Use the full dataset. Implied if --sample is not given.",
    )
    parser.add_argument(
        "--rebuild",
        choices=["all", "embed", "transformer", "autoencoder", "scores", "calibrate", "faiss"],
        default=None,
        help="Force a step to re-run even if its artifact is fresh.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("training/data"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parent.parent
    data_dir = (project_root / args.data_dir).resolve() if not args.data_dir.is_absolute() else args.data_dir.resolve()
    artifact_dir = (project_root / args.artifact_dir).resolve() if not args.artifact_dir.is_absolute() else args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    sample_mode = args.sample is not None
    rebuild_all = args.rebuild == "all"

    # Steps 1-3: parse → window → embed
    events = step_data_prep(
        dataset=args.dataset, data_dir=data_dir,
        artifact_dir=artifact_dir, sample=args.sample,
        rebuild=rebuild_all,
    )
    windows = step_windows(events, dataset=args.dataset, data_dir=data_dir)
    embeddings, labels = step_embed_and_label(
        windows, dataset=args.dataset, artifact_dir=artifact_dir,
        rebuild=rebuild_all or args.rebuild == "embed",
    )

    # Steps 4-5: train both models
    transformer_metrics = step_train_transformer(
        embeddings, labels,
        artifact_dir=artifact_dir, device=args.device,
        rebuild=rebuild_all or args.rebuild == "transformer",
        sample_mode=sample_mode,
    )
    autoencoder_metrics = step_train_autoencoder(
        embeddings, labels,
        artifact_dir=artifact_dir, device=args.device,
        rebuild=rebuild_all or args.rebuild == "autoencoder",
        sample_mode=sample_mode,
    )

    # Steps 6-7: score + calibrate
    transformer_scores, ae_errors = step_component_scores(
        embeddings, artifact_dir=artifact_dir, device=args.device,
        rebuild=rebuild_all or args.rebuild == "scores",
    )
    calibration_metrics = step_calibrate(
        transformer_scores, ae_errors, labels,
        artifact_dir=artifact_dir, device=args.device,
    )

    # Step 8: FAISS
    faiss_metrics = step_build_faiss(
        embeddings, labels,
        dataset=args.dataset, artifact_dir=artifact_dir,
        project_root=project_root,
    )

    # Step 9: RESULTS.md
    step_write_results(
        dataset=args.dataset, sample=args.sample,
        artifact_dir=artifact_dir, project_root=project_root,
        transformer_metrics=transformer_metrics,
        autoencoder_metrics=autoencoder_metrics,
        calibration_metrics=calibration_metrics,
        faiss_metrics=faiss_metrics,
    )

    print(f"\n✓ Pipeline complete. See {project_root / 'training' / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
