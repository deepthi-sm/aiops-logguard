"""
Per-cell eval diagnostic — verification companion to run_proper_eval.

Replays the Phase-4 eval grid against the cached embeddings + labels +
trained models, but logs the underlying score distributions so we can
see WHY a given F1 lands where it does. Key questions answered:

  - n_pos / n_neg per test set (catches label-collapse → F1 mechanically 0)
  - mean_score on positives vs negatives (catches model failure)
  - what fraction passes the anomaly_threshold gate alone
  - what fraction passes the confidence_threshold gate alone
  - what fraction passes BOTH (= what predicted_labels returns live)
  - F1 if we kept ONLY the ensemble gate, dropped the confidence gate
  - F1 at the per-cell-optimal threshold (sweep)
  - mean confidence on TP / TN / FP / FN — verification that the
    confidence MLP is directionally correct (TP > FN, TN > FP)

Run after `run_proper_eval.py` to confirm the numbers behind RESULTS.md.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    try:
        if _stream.encoding != "utf-8":
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import torch  # noqa: E402

from ml.detector import Detector  # noqa: E402
from ml.ensemble import combine, normalise_ae_error  # noqa: E402
from training.eval_holdout_openstack import (  # noqa: E402
    _auc_score,
    compute_confidence,
)

ROOT = Path("artifacts_proper")


def score_set(detector: Detector, embeddings: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (transformer_scores, ae_norm, ensemble, confidence) for `embeddings`."""
    n = embeddings.shape[0]
    t_scores = np.empty(n, dtype=np.float32)
    ae_errs = np.empty(n, dtype=np.float32)
    batch = 256
    with torch.no_grad():
        x_all = torch.from_numpy(embeddings).float()
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
    th = detector.thresholds
    ae_norm = normalise_ae_error(ae_errs, p10=th.ae_error_p10, p90=th.ae_error_p90)
    ensemble = combine(t_scores, ae_errs, thresholds=th)
    conf = compute_confidence(detector._confidence, t_scores, ae_norm)  # noqa: SLF001
    return t_scores, ae_norm, ensemble, conf


def _f1(y: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return f1, p, r


def sweep_best_threshold(ensemble: np.ndarray, y: np.ndarray) -> tuple[float, float, float, float]:
    """Find the threshold that maximises F1 on this test slice.
    Returns (best_thresh, f1, precision, recall)."""
    if y.sum() == 0 or y.sum() == len(y):
        return float("nan"), 0.0, 0.0, 0.0
    candidates = np.linspace(0.0, 1.0, 201)
    best = (0.5, 0.0, 0.0, 0.0)
    for t in candidates:
        pred = (ensemble >= t).astype(np.int64)
        f1, p, r = _f1(y, pred)
        if f1 > best[1]:
            best = (float(t), f1, p, r)
    return best


def diagnose_cell(
    *,
    label: str,
    detector: Detector,
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> None:
    th = detector.thresholds
    t_scores, ae_norm, ensemble, conf = score_set(detector, embeddings)
    y = labels.astype(np.int64)

    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    mean_pos = float(ensemble[y == 1].mean()) if n_pos else float("nan")
    mean_neg = float(ensemble[y == 0].mean()) if n_neg else float("nan")
    conf_mean_pos = float(conf[y == 1].mean()) if n_pos else float("nan")
    conf_mean_neg = float(conf[y == 0].mean()) if n_neg else float("nan")

    gate_e = ensemble >= th.anomaly_threshold
    gate_c = conf >= th.confidence_threshold
    both = gate_e & gate_c

    f1_both, p_both, r_both = _f1(y, both.astype(np.int64))
    f1_eonly, p_eonly, r_eonly = _f1(y, gate_e.astype(np.int64))

    auc = _auc_score(y, ensemble)

    sweep_t, sweep_f1, sweep_p, sweep_r = sweep_best_threshold(ensemble, y)

    print(f"=== {label} ===")
    print(f"  n_total={len(y):,}  n_pos={n_pos:,}  n_neg={n_neg:,}  pos_rate={n_pos/max(len(y),1)*100:.2f}%")
    print(f"  thresholds: anomaly={th.anomaly_threshold:.3f}  confidence={th.confidence_threshold:.3f}")
    print(f"  ensemble  : mean_pos={mean_pos:.4f}  mean_neg={mean_neg:.4f}")
    print(f"  confidence: mean_pos={conf_mean_pos:.4f}  mean_neg={conf_mean_neg:.4f}")
    print(f"  gate ensemble alone : passed={int(gate_e.sum()):,} ({gate_e.mean()*100:.1f}%)  F1={f1_eonly:.3f}  P={p_eonly:.3f}  R={r_eonly:.3f}")
    print(f"  gate confidence alone: passed={int(gate_c.sum()):,} ({gate_c.mean()*100:.1f}%)")
    print(f"  gate BOTH (live)    : passed={int(both.sum()):,} ({both.mean()*100:.1f}%)  F1={f1_both:.3f}  P={p_both:.3f}  R={r_both:.3f}")
    print(f"  AUC = {auc:.4f}")
    print(f"  best threshold by sweep on this slice: t={sweep_t:.3f}  F1={sweep_f1:.3f}  P={sweep_p:.3f}  R={sweep_r:.3f}")

    # -- Verification: mean confidence by ensemble-gate confusion bucket -----
    # The directional-target fix (calibrate.py) should produce
    #   mean_conf(TP) > mean_conf(FN)     # confident on real positives
    #   mean_conf(TN) > mean_conf(FP)     # confident on real negatives
    # If TP confidence is below the live confidence_threshold, the live
    # AND-gate will silently suppress real alerts → that's the failure
    # mode the previous run hit (mean_conf TP=0.024 vs gate=0.30).
    pred = (ensemble >= th.anomaly_threshold).astype(np.int64)
    tp_mask = (pred == 1) & (y == 1)
    fp_mask = (pred == 1) & (y == 0)
    tn_mask = (pred == 0) & (y == 0)
    fn_mask = (pred == 0) & (y == 1)

    def _mean(mask: np.ndarray) -> float:
        return float(conf[mask].mean()) if int(mask.sum()) else float("nan")

    mc_tp = _mean(tp_mask)
    mc_fp = _mean(fp_mask)
    mc_tn = _mean(tn_mask)
    mc_fn = _mean(fn_mask)
    n_tp = int(tp_mask.sum())
    n_fp = int(fp_mask.sum())
    n_tn = int(tn_mask.sum())
    n_fn = int(fn_mask.sum())
    print(
        f"  VERIFY mean_conf  TP={mc_tp:.4f} (n={n_tp:,})  "
        f"TN={mc_tn:.4f} (n={n_tn:,})  "
        f"FP={mc_fp:.4f} (n={n_fp:,})  "
        f"FN={mc_fn:.4f} (n={n_fn:,})"
    )
    sane_pos = mc_tp > mc_fn if (n_tp and n_fn) else None
    sane_neg = mc_tn > mc_fp if (n_tn and n_fp) else None
    print(
        f"  VERIFY directional sanity: "
        f"TP>FN={'OK' if sane_pos else ('FAIL' if sane_pos is False else 'n/a')}  "
        f"TN>FP={'OK' if sane_neg else ('FAIL' if sane_neg is False else 'n/a')}"
    )
    print()


def main() -> int:
    # Cached preprocessed data
    os_emb = np.load(ROOT / "_inputs/openstack/embeddings.npy", mmap_mode="r")
    os_lab = np.load(ROOT / "_inputs/openstack/labels.npy")
    os_test_idx = np.load(ROOT / "_inputs/openstack/test_idx.npy")
    print(f"OpenStack: total={os_emb.shape[0]:,}  pos_total={int(os_lab.sum()):,}  test_n={len(os_test_idx):,}  test_pos={int(os_lab[os_test_idx].sum()):,}")

    hdfs_emb = np.load(ROOT / "_inputs/hdfs/embeddings.npy", mmap_mode="r")
    hdfs_lab = np.load(ROOT / "_inputs/hdfs/labels.npy")
    hdfs_test_idx = np.load(ROOT / "_inputs/hdfs/test_idx.npy")
    print(f"HDFS:      total={hdfs_emb.shape[0]:,}  pos_total={int(hdfs_lab.sum()):,}  test_n={len(hdfs_test_idx):,}  test_pos={int(hdfs_lab[hdfs_test_idx].sum()):,}")

    apache_emb = np.load(ROOT / "_inputs/embeddings_apache.npy", mmap_mode="r")
    print(f"Apache:    total={apache_emb.shape[0]:,}  (labels computed live in eval_apache via level fallback)")
    print()

    # Load both detectors
    det_a = Detector.from_artifacts(ROOT / "openstack_only")
    det_b = Detector.from_artifacts(ROOT / "combined")

    # Six holdout cells (Apache deferred — labels live only in eval_apache)
    diagnose_cell(
        label="openstack_only x openstack_test",
        detector=det_a,
        embeddings=np.asarray(os_emb[os_test_idx]),
        labels=os_lab[os_test_idx],
    )
    diagnose_cell(
        label="openstack_only x hdfs_test",
        detector=det_a,
        embeddings=np.asarray(hdfs_emb[hdfs_test_idx]),
        labels=hdfs_lab[hdfs_test_idx],
    )
    diagnose_cell(
        label="combined x openstack_test",
        detector=det_b,
        embeddings=np.asarray(os_emb[os_test_idx]),
        labels=os_lab[os_test_idx],
    )
    diagnose_cell(
        label="combined x hdfs_test",
        detector=det_b,
        embeddings=np.asarray(hdfs_emb[hdfs_test_idx]),
        labels=hdfs_lab[hdfs_test_idx],
    )

    # Apache cells need the Apache labels — replay how eval_apache builds them.
    print("=== APACHE — checking how labels were built ===")
    from training.eval_cross_dataset import label_windows as cross_label_windows
    from training.eval_cross_dataset import make_level_labeler, parse_apache
    from training.sequence_builder import build_windows
    apache_log = Path("training/data/apache/Apache.log")
    drain3_state = ROOT / "_inputs/apache_eval_drain3.bin"
    print(f"  parsing Apache.log via {drain3_state} ...")
    events = parse_apache(apache_log, drain3_state_out=drain3_state, sample=None)
    windows = build_windows(events, label_fn=lambda chunk: "normal")
    labeller = make_level_labeler()
    truth = cross_label_windows(windows, label_fn=labeller).astype(np.int64)
    print(f"  apache windows={len(truth):,}  positive={int(truth.sum()):,}  pos_rate={truth.mean()*100:.2f}%")
    print()

    diagnose_cell(
        label="openstack_only x apache",
        detector=det_a,
        embeddings=np.asarray(apache_emb),
        labels=truth,
    )
    diagnose_cell(
        label="combined x apache",
        detector=det_b,
        embeddings=np.asarray(apache_emb),
        labels=truth,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
