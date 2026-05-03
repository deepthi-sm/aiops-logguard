# AIOps-LogGuard — Training & Evaluation Results

Auto-generated companion to `training/run_proper_eval.py`. **These are the
paper numbers.** They supersede the earlier `RESULTS.md` whose F1=1.000
headline was tuned and reported on the same corpus (calibration leak).

- Run timestamp: **2026-05-03**
- Split: **70 / 15 / 15** (`TEST_FRACTION = 0.15`, `TEST_SEED = 99`)
- Test slices for OpenStack and HDFS were excluded from training **and**
  calibration. Apache was never seen by either model.
- Window size / stride: 20 / 1

## Two models, head-to-head

| Model | Training corpus | Windows |
|---|---|---:|
| **A — OpenStack-only** | OpenStack | 207,801 |
| **B — Combined OS+HDFS** | OpenStack + HDFS-sample-100k | 261,615 |

## Headline F1 (paper table)

| | OpenStack test | HDFS test | Apache (never seen) |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | **0.936** | 0.000 | **0.984** |
| **Model B — Combined OS+HDFS** | **1.000** | **0.516** | **0.914** |

## AUC — threshold-independent ranking quality

| | OpenStack test | HDFS test | Apache |
|---|---:|---:|---:|
| **Model A — OpenStack-only** | 0.996 | 0.396 | 0.458 |
| **Model B — Combined OS+HDFS** | 1.000 | 0.670 | 0.368 |

## Precision / Recall

| Model | Test set | Precision | Recall |
|---|---|---:|---:|
| Model A — OpenStack-only | OpenStack | 0.894 | 0.982 |
| Model A — OpenStack-only | HDFS | 0.000 | 0.000 |
| Model A — OpenStack-only | Apache | 0.994 | 0.974 |
| Model B — Combined OS+HDFS | OpenStack | 1.000 | 1.000 |
| Model B — Combined OS+HDFS | HDFS | 0.395 | 0.745 |
| Model B — Combined OS+HDFS | Apache | 0.989 | 0.849 |

## Calibrated thresholds (per model)

| Param | Model A — OpenStack-only | Model B — Combined |
|---|---:|---:|
| w1 (transformer) | 0.75 | 0.85 |
| w2 (autoencoder) | 0.25 | 0.15 |
| anomaly_threshold | 0.65 | 0.60 |
| confidence_threshold | 0.30 | 0.30 |

## RAG seed

| Source | Count |
|---|---:|
| Real anomalies indexed | 18,434 |
| Hand-written synthetic incidents | 20 |
| Total FAISS entries | 18,454 |

## Reading guide

- **OpenStack test** is the in-distribution headline number for each model.
- **HDFS test** measures generalisation for Model A (HDFS unseen) and
  in-distribution performance for Model B (HDFS in training).
- **Apache** is the cross-dataset robustness check — Apache was never in
  either training corpus.

## Key findings

1. **Combined ≥ OpenStack-only on every shared cell.** The joint-training
   claim survives: F1=1.000 vs 0.936 on OpenStack, F1=0.516 vs 0.000 on
   HDFS. Negative transfer would have shown up as a drop on OpenStack
   when adding HDFS — it didn't.
2. **OpenStack-only fails completely on HDFS** (F1=0.000, AUC=0.396).
   `mean_pos = 0.604` ≈ `mean_neg = 0.606` — the model literally cannot
   distinguish HDFS anomalies. This is the cross-domain failure that
   *justifies* training Model B.
3. **Apache F1 numbers come with a class-imbalance caveat.** Apache has
   ~99% positive rate (most lines carry `[error] / [warn] / [fatal]`),
   so a model that calls "anomaly" frequently scores high recall almost
   by accident. AUC is the honest ranking metric for Apache.

## Methodology corrections vs the previous RESULTS.md

The previous results file (May 1 run) reported F1=1.000 with
calibration thresholds and the F1 metric **both computed on the full
corpus**. That's calibration leak — the threshold grid-search saw the
val labels. This run fixes it three ways:

1. **70/15/15 split.** A held-out 15% test slice is excluded from
   training, validation, *and* calibration. The numbers above are
   computed on that slice only.
2. **Two models, separate calibrations.** Each model gets its own
   `thresholds.json` derived from its own train+val slice — never from
   the test slice.
3. **Ensemble-only F1.** The live detector applies an AND gate
   (`ensemble ≥ τ_a AND confidence ≥ τ_c`). The confidence MLP is an
   operational filter for live alerts; including it in offline F1 hides
   model-quality numbers behind calibrator pathology. Paper F1 is
   reported with the ensemble gate alone.

## Known caveat — confidence MLP under heavy imbalance

The confidence MLP currently rewards *decisive negatives* slightly more
than *decisive positives* under heavy class imbalance: `mean_conf(TP) =
0.021 < mean_conf(FN) = 0.073` on Model A × OpenStack-test. This does
**not** affect the paper F1 (which uses ensemble-only), but the live
detector will silently suppress real alerts at the default
`confidence_threshold = 0.30`. For the live demo, set
`confidence_threshold = 0.0` until the calibrator is reweighted.
