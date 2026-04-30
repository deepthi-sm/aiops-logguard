"""
Tests for training/train_autoencoder.py.

Like test_train_transformer.py, runs a tiny number of epochs on synthetic
data — exercises loop structure + loss + validation + early-stop + save/load,
not "does it actually learn."
"""
from pathlib import Path

import numpy as np
import pytest
import torch

from ml.autoencoder import SBERT_DIM, LogAutoEncoder
from ml.transformer import WINDOW_LEN
from training.train_autoencoder import (
    TrainConfig,
    save_torchscript,
    train,
)


def _synth_data(n_normal: int = 80, n_anomaly: int = 20, seed: int = 11):
    rng = np.random.default_rng(seed)
    normal = rng.standard_normal((n_normal, WINDOW_LEN, SBERT_DIM)).astype(np.float32) * 0.3
    anomaly = rng.standard_normal((n_anomaly, WINDOW_LEN, SBERT_DIM)).astype(np.float32) * 1.5
    embeddings = np.concatenate([normal, anomaly], axis=0)
    labels = np.concatenate([
        np.zeros(n_normal, dtype=np.float32),
        np.ones(n_anomaly, dtype=np.float32),
    ])
    perm = rng.permutation(len(embeddings))
    return embeddings[perm], labels[perm]


@pytest.fixture
def fast_config() -> TrainConfig:
    return TrainConfig(
        epochs=3,
        batch_size=16,
        lr=1e-3,
        early_stop_patience=20,
        val_split=0.25,
        seed=11,
    )


# -- Train function --------------------------------------------------------

class TestTrain:
    def test_returns_model_and_metrics(self, fast_config):
        emb, lbl = _synth_data()
        model, metrics = train(emb, lbl, config=fast_config, verbose=False)
        assert isinstance(model, LogAutoEncoder)
        assert "best_epoch" in metrics
        assert "best_val_loss" in metrics
        assert "history" in metrics
        assert "n_normal_windows" in metrics
        assert "n_total_windows" in metrics

    def test_filters_to_normal_only(self, fast_config):
        emb, lbl = _synth_data(n_normal=80, n_anomaly=20)
        _, metrics = train(emb, lbl, config=fast_config, verbose=False)
        assert metrics["n_normal_windows"] == 80
        assert metrics["n_total_windows"] == 100

    def test_loss_decreases_over_epochs(self, fast_config):
        emb, lbl = _synth_data()
        _, metrics = train(emb, lbl, config=fast_config, verbose=False)
        first = metrics["history"][0]["train_loss"]
        last = metrics["history"][-1]["train_loss"]
        assert last < first, f"loss did not decrease: {first:.5f} → {last:.5f}"

    def test_anomalies_reconstruct_worse_than_normals(self, fast_config):
        """Trained-on-normal AE should reconstruct anomalies with higher
        error than normals. This is the very signal the ensemble exploits."""
        emb, lbl = _synth_data(n_normal=200, n_anomaly=50)
        # Slightly more epochs so the AE learns the normal manifold
        config = TrainConfig(
            epochs=10, batch_size=16, lr=1e-3,
            early_stop_patience=20, val_split=0.2, seed=11,
        )
        model, _ = train(emb, lbl, config=config, verbose=False)
        from ml.autoencoder import pool_window, reconstruction_error
        x = pool_window(torch.from_numpy(emb).float())
        err = reconstruction_error(model, x).numpy()
        normal_err = err[lbl == 0].mean()
        anomaly_err = err[lbl == 1].mean()
        assert anomaly_err > normal_err, (
            f"anomalies should reconstruct worse: normal {normal_err:.4f} vs "
            f"anomaly {anomaly_err:.4f}"
        )

    def test_rejects_no_normal_data(self, fast_config):
        """If every label is 1, there's nothing to train on."""
        emb = np.random.randn(20, WINDOW_LEN, SBERT_DIM).astype(np.float32)
        lbl = np.ones(20, dtype=np.float32)
        with pytest.raises(ValueError, match=r"normal-labelled"):
            train(emb, lbl, config=fast_config, verbose=False)

    def test_rejects_mismatched_shapes(self, fast_config):
        with pytest.raises(ValueError, match=r"embeddings"):
            train(np.zeros((10, SBERT_DIM)), np.zeros(10), config=fast_config, verbose=False)
        with pytest.raises(ValueError, match=r"labels"):
            train(
                np.zeros((10, WINDOW_LEN, SBERT_DIM)),
                np.zeros(9),
                config=fast_config, verbose=False,
            )


# -- TorchScript save/load -------------------------------------------------

class TestSaveTorchScript:
    def test_save_creates_file(self, tmp_path: Path, fast_config: TrainConfig):
        emb, lbl = _synth_data()
        model, _ = train(emb, lbl, config=fast_config, verbose=False)
        dest = tmp_path / "autoencoder.pt"
        save_torchscript(model, dest)
        assert dest.exists()
        assert dest.stat().st_size > 0

    def test_torchscript_round_trip_matches_eager(
        self, tmp_path: Path, fast_config: TrainConfig,
    ):
        emb, lbl = _synth_data()
        model, _ = train(emb, lbl, config=fast_config, verbose=False)
        dest = tmp_path / "autoencoder.pt"
        save_torchscript(model, dest)

        loaded = torch.jit.load(str(dest))
        x = torch.randn(3, SBERT_DIM)
        model.eval()
        with torch.no_grad():
            eager = model(x)
            scripted = loaded(x)
        assert torch.allclose(eager, scripted, atol=1e-5)
