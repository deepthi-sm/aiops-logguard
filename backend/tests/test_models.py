"""
Architecture tests for ml/transformer.py and ml/autoencoder.py.

Tests pin the input/output shapes the live detector and training scripts
rely on, plus the contract that the failure path raises (rather than silently
mis-shaped inference). No actual training — the calibration tests in PR 6
exercise the loss curves.
"""
import pytest
import torch

from ml.autoencoder import (
    D_BOTTLENECK,
    LogAutoEncoder,
    pool_window,
    reconstruction_error,
)
from ml.transformer import (
    D_MODEL,
    N_HEADS,
    N_LAYERS,
    SBERT_DIM,
    WINDOW_LEN,
    LogTransformer,
)

# -- LogTransformer ---------------------------------------------------------

class TestLogTransformer:
    def test_canonical_hyperparameters_match_doc(self):
        """If you change WINDOW_LEN here, you must change WINDOW_SIZE in
        sequence_builder and retrain everything. This guards the link."""
        from training.sequence_builder import WINDOW_SIZE
        assert WINDOW_LEN == WINDOW_SIZE
        assert SBERT_DIM == 384
        assert D_MODEL == 256
        assert N_HEADS == 8
        assert N_LAYERS == 4

    def test_forward_returns_three_keys(self):
        m = LogTransformer()
        x = torch.randn(3, WINDOW_LEN, SBERT_DIM)
        out = m(x)
        assert set(out.keys()) == {"anomaly_logit", "failure_minutes", "attention"}

    def test_anomaly_logit_shape(self):
        m = LogTransformer()
        x = torch.randn(7, WINDOW_LEN, SBERT_DIM)
        assert m(x)["anomaly_logit"].shape == (7, 1)

    def test_failure_minutes_shape(self):
        m = LogTransformer()
        x = torch.randn(5, WINDOW_LEN, SBERT_DIM)
        assert m(x)["failure_minutes"].shape == (5, 1)

    def test_attention_shape_matches_window_len(self):
        m = LogTransformer()
        x = torch.randn(4, WINDOW_LEN, SBERT_DIM)
        attn = m(x)["attention"]
        assert attn.shape == (4, WINDOW_LEN)

    def test_attention_sums_to_one_per_window(self):
        """Per-event saliency should be a normalised distribution so the
        frontend can render it as a heatmap row that sums to 1."""
        m = LogTransformer()
        x = torch.randn(4, WINDOW_LEN, SBERT_DIM)
        sums = m(x)["attention"].sum(dim=-1)
        assert torch.allclose(sums, torch.ones(4), atol=1e-5)

    def test_rejects_wrong_input_rank(self):
        m = LogTransformer()
        with pytest.raises(ValueError, match=r"expected"):
            m(torch.randn(WINDOW_LEN, SBERT_DIM))   # missing batch dim

    def test_rejects_wrong_window_len(self):
        m = LogTransformer()
        with pytest.raises(ValueError, match=r"expected"):
            m(torch.randn(2, WINDOW_LEN + 1, SBERT_DIM))

    def test_rejects_wrong_input_dim(self):
        m = LogTransformer()
        with pytest.raises(ValueError, match=r"expected"):
            m(torch.randn(2, WINDOW_LEN, SBERT_DIM - 1))

    def test_torchscript_scriptable(self):
        """Live detector loads via torch.jit.load, so the model must script.
        This catches sneaky non-JIT-able patterns at PR review time."""
        m = LogTransformer().eval()  # eval() so dropout is deterministic
        scripted = torch.jit.script(m)
        x = torch.randn(2, WINDOW_LEN, SBERT_DIM)
        with torch.no_grad():
            out_eager = m(x)
            out_scripted = scripted(x)
        for k in out_eager:
            assert torch.allclose(out_eager[k], out_scripted[k], atol=1e-5)


# -- LogAutoEncoder ---------------------------------------------------------

class TestLogAutoEncoder:
    def test_default_dims(self):
        ae = LogAutoEncoder()
        assert ae.d_input == SBERT_DIM
        assert ae.d_bottleneck == D_BOTTLENECK

    def test_forward_preserves_shape(self):
        ae = LogAutoEncoder()
        x = torch.randn(5, SBERT_DIM)
        out = ae(x)
        assert out.shape == x.shape

    def test_rejects_wrong_input_dim(self):
        ae = LogAutoEncoder()
        with pytest.raises(ValueError, match=r"expected"):
            ae(torch.randn(5, SBERT_DIM - 1))

    def test_rejects_wrong_input_rank(self):
        ae = LogAutoEncoder()
        with pytest.raises(ValueError, match=r"expected"):
            ae(torch.randn(SBERT_DIM))   # missing batch dim

    def test_bottleneck_compresses(self):
        """Encoder output dim is the bottleneck — quick architecture sanity check."""
        ae = LogAutoEncoder()
        x = torch.randn(3, SBERT_DIM)
        z = ae.encoder(x)
        assert z.shape == (3, D_BOTTLENECK)

    def test_reconstruction_error_returns_per_window(self):
        ae = LogAutoEncoder()
        x = torch.randn(6, SBERT_DIM)
        err = reconstruction_error(ae, x)
        assert err.shape == (6,)
        assert (err >= 0).all()

    def test_torchscript_scriptable(self):
        ae = LogAutoEncoder().eval()
        scripted = torch.jit.script(ae)
        x = torch.randn(2, SBERT_DIM)
        with torch.no_grad():
            assert torch.allclose(ae(x), scripted(x), atol=1e-5)


# -- pool_window helper -----------------------------------------------------

class TestPoolWindow:
    def test_mean_pools_across_window_axis(self):
        x = torch.randn(4, WINDOW_LEN, SBERT_DIM)
        pooled = pool_window(x)
        assert pooled.shape == (4, SBERT_DIM)
        assert torch.allclose(pooled, x.mean(dim=1))

    def test_rejects_non_3d_input(self):
        with pytest.raises(ValueError, match=r"expected"):
            pool_window(torch.randn(SBERT_DIM))
