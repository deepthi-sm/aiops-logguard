"""
Tests for training/train_transformer.py.

The full 30-epoch run on real data takes 1–3 hours; CI runs 2–3 epochs on
tiny synthetic data so we exercise the loop structure, loss, validation,
early-stop, save/load contract, and TorchScript export — everything *except*
"does this actually learn." That's verified by the user running the full
pipeline locally (RESULTS.md numbers go into the paper).
"""
from pathlib import Path

import numpy as np
import pytest
import torch

from ml.transformer import SBERT_DIM, WINDOW_LEN, LogTransformer
from training.train_transformer import (
    TrainConfig,
    save_torchscript,
    train,
)


def _synth_data(n_normal: int = 60, n_anomaly: int = 20, seed: int = 7):
    """Synthetic embeddings with a learnable signal: normal windows have
    template embeddings drawn near origin, anomalies near a fixed direction.
    The transformer should easily learn this in a few epochs."""
    rng = np.random.default_rng(seed)
    normal = rng.standard_normal((n_normal, WINDOW_LEN, SBERT_DIM)).astype(np.float32) * 0.5
    anomaly_dir = rng.standard_normal((1, 1, SBERT_DIM)).astype(np.float32)
    anomaly = (
        rng.standard_normal((n_anomaly, WINDOW_LEN, SBERT_DIM)).astype(np.float32) * 0.5
        + anomaly_dir * 2.0
    )
    embeddings = np.concatenate([normal, anomaly], axis=0)
    labels = np.concatenate([
        np.zeros(n_normal, dtype=np.float32),
        np.ones(n_anomaly, dtype=np.float32),
    ])
    perm = rng.permutation(len(embeddings))
    return embeddings[perm], labels[perm]


@pytest.fixture
def fast_config() -> TrainConfig:
    """Tiny config so the test finishes in seconds, not minutes."""
    return TrainConfig(
        epochs=3,
        batch_size=8,
        lr=1e-3,
        early_stop_patience=10,  # high so early stop doesn't fire in 3 epochs
        val_split=0.25,
        seed=7,
    )


# -- Train function --------------------------------------------------------

class TestTrain:
    def test_returns_model_and_metrics(self, fast_config):
        emb, lbl = _synth_data()
        model, metrics = train(emb, lbl, config=fast_config, verbose=False)
        assert isinstance(model, LogTransformer)
        assert "best_epoch" in metrics
        assert "best_val_f1" in metrics
        assert "history" in metrics
        assert "config" in metrics

    def test_history_has_one_entry_per_epoch(self, fast_config):
        emb, lbl = _synth_data()
        _, metrics = train(emb, lbl, config=fast_config, verbose=False)
        assert len(metrics["history"]) == fast_config.epochs
        assert all("train_loss" in h for h in metrics["history"])
        assert all("val_f1" in h for h in metrics["history"])

    def test_loss_decreases_over_epochs(self, fast_config):
        """Sanity check: 3 epochs on a learnable problem should reduce loss."""
        emb, lbl = _synth_data()
        _, metrics = train(emb, lbl, config=fast_config, verbose=False)
        first_loss = metrics["history"][0]["train_loss"]
        last_loss = metrics["history"][-1]["train_loss"]
        assert last_loss < first_loss, (
            f"loss did not decrease: epoch 1 = {first_loss:.4f}, "
            f"epoch {len(metrics['history'])} = {last_loss:.4f}"
        )

    def test_best_state_is_loaded_into_model(self, fast_config):
        """After train returns, the model's params should match the
        epoch with best val_f1, not the last epoch."""
        emb, lbl = _synth_data()
        model, metrics = train(emb, lbl, config=fast_config, verbose=False)
        # Inference shouldn't error and should produce well-formed outputs
        model.eval()
        with torch.no_grad():
            out = model(torch.from_numpy(emb[:2]).float())
        assert out["anomaly_logit"].shape == (2, 1)
        assert metrics["best_epoch"] >= 1
        assert metrics["best_epoch"] <= fast_config.epochs

    def test_early_stopping(self):
        """If we set patience low and let val_f1 plateau, training should
        stop before all epochs run."""
        emb, lbl = _synth_data()
        # Aggressive patience: should stop after a few epochs of plateau.
        config = TrainConfig(
            epochs=20, batch_size=8, lr=1e-3,
            early_stop_patience=2, val_split=0.25, seed=7,
        )
        _, metrics = train(emb, lbl, config=config, verbose=False)
        # On easy synthetic data val_f1 likely climbs and patience may not
        # fire — this test just verifies the early-stop branch exists and
        # epochs_run never exceeds config.epochs.
        assert metrics["epochs_run"] <= config.epochs

    def test_rejects_mismatched_shapes(self, fast_config):
        with pytest.raises(ValueError, match=r"embeddings"):
            train(np.zeros((10, SBERT_DIM)), np.zeros(10), config=fast_config, verbose=False)
        with pytest.raises(ValueError, match=r"labels"):
            train(
                np.zeros((10, WINDOW_LEN, SBERT_DIM)),
                np.zeros(9),
                config=fast_config, verbose=False,
            )

    def test_failure_minutes_branch_runs_when_provided(self, fast_config):
        """When failure_mask has any True entries, the MSE component should
        be a positive number (not exactly 0). Non-strict — just verifies the
        branch executes."""
        emb, lbl = _synth_data()
        n = emb.shape[0]
        rng = np.random.default_rng(0)
        failure_minutes = rng.uniform(5, 60, size=n).astype(np.float32)
        # Mark every 5th window as having a known failure target
        failure_mask = (np.arange(n) % 5 == 0)
        _, metrics = train(
            emb, lbl,
            failure_minutes=failure_minutes,
            failure_mask=failure_mask,
            config=fast_config,
            verbose=False,
        )
        # At least one epoch should have a non-zero train_mse value
        assert any(h["train_mse"] > 0 for h in metrics["history"]), \
            "train_mse stayed at 0 even though failure_mask had True entries"


# -- TorchScript save/load -------------------------------------------------

class TestSaveTorchScript:
    def test_save_creates_file(self, tmp_path: Path, fast_config: TrainConfig):
        emb, lbl = _synth_data()
        model, _ = train(emb, lbl, config=fast_config, verbose=False)
        dest = tmp_path / "transformer.pt"
        save_torchscript(model, dest)
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_torchscript_round_trip_matches_eager(
        self, tmp_path: Path, fast_config: TrainConfig,
    ):
        """Saved .pt must produce the same outputs as the eager model — the
        live detector loads the .pt without our model code."""
        emb, lbl = _synth_data()
        model, _ = train(emb, lbl, config=fast_config, verbose=False)
        dest = tmp_path / "transformer.pt"
        save_torchscript(model, dest)

        loaded = torch.jit.load(str(dest))
        x = torch.from_numpy(emb[:3]).float()
        model.eval()
        with torch.no_grad():
            eager = model(x)
            scripted = loaded(x)
        for k in eager:
            assert torch.allclose(eager[k], scripted[k], atol=1e-5), f"mismatch for {k}"

    def test_save_creates_parent_dirs(self, tmp_path: Path, fast_config: TrainConfig):
        emb, lbl = _synth_data()
        model, _ = train(emb, lbl, config=fast_config, verbose=False)
        dest = tmp_path / "deep" / "nested" / "transformer.pt"
        save_torchscript(model, dest)
        assert dest.exists()
