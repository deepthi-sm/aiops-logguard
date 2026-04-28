# Training Pipeline (Pipeline 2) — Detailed Reference

This is everything needed to produce all artifacts in `backend/artifacts/`. Run `python -m training.run_full_pipeline --dataset hdfs` and you should get a working set of models.

## Inputs

- **HDFS dataset** from LogHub — primary. URL: https://github.com/logpai/loghub
- **BGL dataset** from LogHub — secondary, used to claim cross-dataset robustness in the paper

Place raw datasets in `backend/training/data/` (gitignored).

## Outputs (all under `backend/artifacts/`)

| File | What it is | Used by |
|---|---|---|
| `drain3_state.bin` | Persisted Drain3 template tree | Both training and live ingestion |
| `embeddings_hdfs.npy` | Cached SBERT vectors for HDFS windows | Training (avoid recompute) |
| `tfidf.npz` | TF-IDF baseline vectors | Paper baseline only |
| `transformer.pt` | TorchScript model | Live detector |
| `autoencoder.pt` | TorchScript model | Live detector |
| `thresholds.json` | `w1, w2, anomaly_threshold, confidence_threshold` | Live detector + ensemble |
| `confidence_scorer.pt` | TorchScript MLP for confidence | Live detector |
| `faiss.index` | FAISS index of past incidents | RAG worker |
| `incidents.jsonl` | Metadata for FAISS-indexed incidents | RAG worker |
| `RESULTS.md` | F1, precision, recall, ablation results | Person C's paper |

## Step 1 — Data prep (`backend/training/data_prep.py`)

```python
# Pseudocode
download_hdfs_to("training/data/hdfs/")
parse_with_drain3(
    input="training/data/hdfs/HDFS.log",
    drain3_state_out="artifacts/drain3_state.bin"
)
normalise(
    strip=["ips", "block_ids", "uuids", "hex_addresses", "timestamps", "emails"]
)
```

**Drain3 config:** start with default settings. The trained Drain3 state is what makes templates stable across training/inference, so it MUST be persisted.

**Normalisation patterns:**
```python
PATTERNS = {
    "ip": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    "block_id": r"blk_-?\d+",
    "uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "hex": r"0x[0-9a-fA-F]+",
    "timestamp": r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",
    "email": r"[\w.-]+@[\w.-]+",
}
```

## Step 2 — Sequence builder (`backend/training/sequence_builder.py`)

**Shared module — used by both training and ingestion.**

```python
def build_windows(events: list[ParsedLog], size=20, stride=1) -> list[Window]:
    """
    Slide a window of `size` events across the parsed log stream.
    Returns Window objects with the 20 templates concatenated and metadata.
    """
```

**HDFS labelling rule:** a window is `anomaly` if any block ID inside its raw lines appears in HDFS's labelled anomaly set (`anomaly_label.csv` from LogHub).

**Output format:**
```python
@dataclass
class Window:
    window_id: str          # uuid
    templates: list[str]    # 20 Drain3 templates
    raw_lines: list[str]    # 20 original lines (kept for top_contributing_lines)
    label: Literal["normal", "anomaly"]
    source_file: str
    line_range: tuple[int, int]
```

Save the manifest as a CSV alongside the embeddings: `(window_id, label, source_file, line_range)`.

## Step 3 — Embedding (`backend/training/embed.py`)

**Primary: SBERT**
```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")  # 384-d, fast

def embed_window(window: Window) -> np.ndarray:
    text = " [SEP] ".join(window.templates)
    return model.encode(text, normalize_embeddings=True)

embeddings = np.stack([embed_window(w) for w in windows])
np.save("artifacts/embeddings_hdfs.npy", embeddings)
```

**Performance note:** batch the encoding. `model.encode(list_of_texts, batch_size=64)` is 10–50x faster than one at a time. On a CPU, ~10M sequences takes hours; on a GPU, minutes. **Cache aggressively.**

**Baseline: TF-IDF**
```python
from sklearn.feature_extraction.text import TfidfVectorizer
import scipy.sparse

vectorizer = TfidfVectorizer(max_features=5000, ngram_range=(1, 2))
texts = [" ".join(w.templates) for w in windows]
tfidf_matrix = vectorizer.fit_transform(texts)
scipy.sparse.save_npz("artifacts/tfidf.npz", tfidf_matrix)
```

## Step 4 — Transformer training (`backend/training/train_transformer.py`)

**Architecture:**
```python
class LogTransformer(nn.Module):
    def __init__(self, d_input=384, d_model=256, n_heads=8, n_layers=4, dropout=0.1):
        super().__init__()
        self.input_proj = nn.Linear(d_input, d_model)
        self.encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=n_heads,
                dim_feedforward=4 * d_model,
                dropout=dropout,
                batch_first=True,
            ),
            num_layers=n_layers,
        )
        self.anomaly_head = nn.Linear(d_model, 1)            # binary
        self.failure_head = nn.Linear(d_model, 1)            # regression: minutes to failure

    def forward(self, x):
        h = self.input_proj(x)
        h = self.encoder(h)
        pooled = h.mean(dim=1)  # mean-pool over sequence
        return {
            "anomaly_logit": self.anomaly_head(pooled),
            "failure_minutes": self.failure_head(pooled),
            "attention": self._last_layer_attention(h),  # save for explainability
        }
```

**Training loop:**
- Optimiser: AdamW
- Learning rate: 2e-4
- Schedule: cosine annealing
- Batch size: 64
- Epochs: 30
- Early stopping: patience 5 on validation F1
- Loss: BCE for anomaly head + MSE (only for known-failure windows) for failure head, summed

**Save:**
```python
scripted = torch.jit.script(model)
scripted.save("artifacts/transformer.pt")
```

TorchScript means the live detector doesn't need to import the model class — it just loads the file.

## Step 5 — AutoEncoder training (`backend/training/train_autoencoder.py`)

**Architecture:**
```python
class LogAutoEncoder(nn.Module):
    def __init__(self, d_input=384, d_bottleneck=64):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(d_input, 256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.ReLU(),
            nn.Linear(128, d_bottleneck),
        )
        self.decoder = nn.Sequential(
            nn.Linear(d_bottleneck, 128),
            nn.ReLU(),
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, d_input),
        )

    def forward(self, x):
        z = self.encoder(x)
        return self.decoder(z)
```

**Critical:** train on **normal sequences only**. The whole point is that anomalous sequences produce high reconstruction error.

**Training:**
- Optimiser: Adam, lr=1e-3
- Batch size: 256
- Epochs: 50
- Loss: MSE
- Early stop: patience 10 on validation reconstruction loss

The reconstruction error on a new window:
```python
error = torch.mean((model(x) - x) ** 2, dim=-1)
```

## Step 6 — Calibration (`backend/training/calibrate.py`)

This step decides the live detector's behaviour. Get it right.

### Grid search on (w1, w2, threshold)

```python
best_f1 = 0
for w1 in np.linspace(0.3, 0.9, 13):
    w2 = 1.0 - w1
    for thresh in np.linspace(0.3, 0.9, 13):
        scores = w1 * transformer_scores + w2 * normalize(autoencoder_errors)
        preds = (scores > thresh).astype(int)
        f1 = f1_score(val_labels, preds)
        if f1 > best_f1:
            best_f1 = f1
            best_params = {"w1": w1, "w2": w2, "anomaly_threshold": thresh}
```

### Confidence scorer MLP

A small MLP predicts whether a given anomaly prediction is correct, given the raw model outputs:

```python
class ConfidenceScorer(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(4, 32),  # transformer_score, ae_error, seq_len, time_of_day
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        return self.net(x)
```

Train on a held-out set with labels = `1 if (predicted_label == true_label) else 0`. Output is the confidence in [0,1].

Pick `confidence_threshold` to maximise F1 on a separate validation slice.

### Save thresholds

```json
{
  "w1": 0.62,
  "w2": 0.38,
  "anomaly_threshold": 0.71,
  "confidence_threshold": 0.65
}
```

Save confidence scorer as `artifacts/confidence_scorer.pt`.

## Step 7 — FAISS index (`backend/training/build_faiss.py`)

```python
import faiss

dim = 384
index = faiss.IndexFlatIP(dim)  # inner product = cosine on normalised vectors

# 1. Add labelled HDFS anomalies
anomaly_embeddings = embeddings[hdfs_anomaly_mask]
index.add(anomaly_embeddings)

# 2. Add 20-30 hand-written incidents
hand_written = load_synthetic_incidents("training/synthetic_incidents.jsonl")
synthetic_embeddings = sbert.encode([inc["template"] for inc in hand_written])
index.add(synthetic_embeddings)

# 3. Save
faiss.write_index(index, "artifacts/faiss.index")

# 4. Save metadata in same order as index
with open("artifacts/incidents.jsonl", "w") as f:
    for inc in all_incidents:
        f.write(json.dumps(inc) + "\n")
```

**Hand-written incidents format (`training/synthetic_incidents.jsonl`):**
```json
{"incident_id": "syn_001", "template": "ERROR connection pool exhausted *", "root_cause_text": "Database connection pool reached its configured maximum and is rejecting new connections.", "recommended_fix": "1. Increase pool size in db config\n2. Investigate slow queries holding connections\n3. Add connection timeout monitoring", "resolved_at": null}
```

Cover at least these patterns in the 20–30 hand-written set:
- Connection pool exhaustion
- Out of memory / OOMKilled
- Disk full
- Network partition / timeout
- DNS resolution failure
- Certificate / TLS expiry
- Authentication failure cascade
- Slow query / database lock
- Service crash loop
- Configuration error after deploy
- Cache stampede
- Rate limit hit

These are what makes LLaMA's output usable from day one.

## Step 8 — Run all (`backend/training/run_full_pipeline.py`)

Single command:
```bash
python -m training.run_full_pipeline --dataset hdfs
```

It calls each step in order and writes `RESULTS.md` at the end:

```markdown
# Training Results

Dataset: HDFS
Trained: 2026-04-28T12:34:56Z

## Transformer
- F1: 0.94
- Precision: 0.92
- Recall: 0.96

## AutoEncoder
- F1: 0.87 (using ensemble)
- Reconstruction error gap (normal vs anomaly): 4.2x

## Ensemble
- F1: 0.96
- w1=0.62, w2=0.38
- anomaly_threshold=0.71, confidence_threshold=0.65

## Confidence scorer
- AUC: 0.89

## Baselines
- TF-IDF + Isolation Forest: F1 0.81
- DeepLog (reproduced): F1 0.89

## Ablations
- No AE: F1 0.91 (-5%)
- No confidence scorer: F1 0.93, but FP rate 3x higher
- No RAG (anomaly only): same F1, no qualitative explanation
```

Person C lifts these numbers directly into the paper.
