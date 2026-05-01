"""
Tests for `training.run_proper_eval` — the proper-eval orchestrator.

Strategy: cover the pure-function pieces (split semantics, F1 floor
check, results-md formatting, sample materialisation) without spinning
up Drain3 / SBERT / torch. The end-to-end run is exercised by actually
running the orchestrator on real corpora — no test simulates that.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from training.eval_holdout_openstack import SplitMetrics
from training.run_proper_eval import (
    DEFAULT_F1_FLOOR,
    TEST_FRACTION,
    TEST_SEED,
    EvalCell,
    PreparedDataset,
    _materialise_sample,
    check_f1_floor,
    write_summary,
)

# -- PreparedDataset --------------------------------------------------------


class TestPreparedDataset:
    def test_slice_returns_paired_subarrays(self):
        ds = PreparedDataset(
            name="test",
            embeddings=np.arange(60).reshape(20, 3, 1).astype(np.float32),
            labels=np.zeros(20, dtype=np.int64),
            test_idx=np.array([0, 1, 2]),
            train_idx=np.arange(3, 20),
        )
        emb, lab = ds.slice(ds.test_idx)
        assert emb.shape == (3, 3, 1)
        assert lab.shape == (3,)

    def test_train_test_partition_is_complete(self):
        n = 100
        rng = np.random.default_rng(TEST_SEED)
        perm = rng.permutation(n)
        n_test = max(1, int(n * TEST_FRACTION))
        test_idx = np.sort(perm[:n_test])
        train_idx = np.setdiff1d(np.arange(n), test_idx, assume_unique=True)
        # No overlap.
        assert len(np.intersect1d(test_idx, train_idx)) == 0
        # Every index covered.
        assert sorted(np.concatenate([test_idx, train_idx]).tolist()) == list(range(n))


# -- F1 floor check --------------------------------------------------------


class TestF1Floor:
    def test_no_failures_when_all_above_floor(self):
        cells = [
            EvalCell("openstack_only", "openstack_test", _metrics(f1=0.92)),
            EvalCell("combined", "hdfs_test", _metrics(f1=0.81)),
        ]
        assert check_f1_floor(cells, DEFAULT_F1_FLOOR) == []

    def test_reports_each_failing_cell(self):
        cells = [
            EvalCell("openstack_only", "openstack_test", _metrics(f1=0.92)),
            EvalCell("combined", "hdfs_test", _metrics(f1=0.42)),
            EvalCell("combined", "apache", _metrics(f1=0.55)),
        ]
        failures = check_f1_floor(cells, floor=0.7)
        assert len(failures) == 2
        assert any("hdfs_test" in f for f in failures)
        assert any("apache" in f for f in failures)

    def test_floor_zero_disables_check(self):
        cells = [
            EvalCell("combined", "openstack_test", _metrics(f1=0.0)),
        ]
        assert check_f1_floor(cells, floor=0.0) == []

    def test_default_floor_is_seven_tenths(self):
        # User spec: "If F1 drops below 0.7 on any held-out test, stop
        # and report." Pin the default so a future config drift trips
        # this test.
        assert DEFAULT_F1_FLOOR == 0.7


# -- _materialise_sample ---------------------------------------------------


class TestMaterialiseSample:
    def test_writes_first_n_lines_only(self, tmp_path: Path):
        src = tmp_path / "big.log"
        src.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")
        dst = tmp_path / "small.log"
        _materialise_sample(src, dst, 5)
        assert dst.read_text(encoding="utf-8").splitlines() == [
            "line 0", "line 1", "line 2", "line 3", "line 4",
        ]

    def test_n_larger_than_file_writes_everything(self, tmp_path: Path):
        src = tmp_path / "src.log"
        src.write_text("only\nthree\nlines\n", encoding="utf-8")
        dst = tmp_path / "dst.log"
        _materialise_sample(src, dst, 999)
        assert dst.read_text(encoding="utf-8") == "only\nthree\nlines\n"


# -- summary md generation -------------------------------------------------


def test_write_summary_contains_every_cell(tmp_path: Path):
    """The paper-table file must surface F1 / AUC for every cell — no
    silent N/A's when the eval ran fully."""
    cells = [
        EvalCell("openstack_only", "openstack_test", _metrics(f1=0.91, auc=0.95)),
        EvalCell("openstack_only", "hdfs_test", _metrics(f1=0.85, auc=0.92)),
        EvalCell("openstack_only", "apache", _metrics(f1=0.70, auc=0.80)),
        EvalCell("combined", "openstack_test", _metrics(f1=0.93, auc=0.96)),
        EvalCell("combined", "hdfs_test", _metrics(f1=0.94, auc=0.97)),
        EvalCell("combined", "apache", _metrics(f1=0.78, auc=0.86)),
    ]
    out = tmp_path / "summary.md"
    write_summary(cells, out_path=out)
    body = out.read_text(encoding="utf-8")

    # Every F1 number renders.
    for c in cells:
        assert f"{c.metrics.f1:.3f}" in body
    # Headline section labels both models and all three test sets.
    for label in ("OpenStack-only", "Combined", "OpenStack test", "HDFS test", "Apache"):
        assert label in body


def test_write_summary_handles_missing_cell_gracefully(tmp_path: Path):
    """If only one model ran, the summary table should still render
    (with em-dashes for the missing cells) — no KeyError."""
    cells = [
        EvalCell("openstack_only", "openstack_test", _metrics(f1=0.91)),
    ]
    out = tmp_path / "summary.md"
    write_summary(cells, out_path=out)
    body = out.read_text(encoding="utf-8")
    assert "—" in body  # placeholder for the missing cells


# -- helpers ---------------------------------------------------------------


def _metrics(*, f1: float = 0.9, auc: float = 0.95) -> SplitMetrics:
    return SplitMetrics(
        name="x",
        n=100, n_positive=20, n_negative=80,
        f1=f1, precision=f1, recall=f1, auc=auc,
        tp=18, fp=2, tn=78, fn=2,
    )
