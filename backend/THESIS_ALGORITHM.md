# Algorithm — Threshold and Weight Calibration via Grid Search

> Source: `backend/training/calibrate.py`. Companion artefact: `backend/artifacts/thresholds.json`.

This document specifies the calibration step of the LogGuard ensemble.
It is intended for direct inclusion in Chapter 4 (Implementation) and
is written so that the LaTeX `algorithm` / `algorithmic` environments
can render it with minimal formatting.

---

## Side information (for prose elsewhere in the chapter)

- **Calibration set.** The grid search is performed on the **train + validation slice** — that is, the 85 % of the corpus that remains after the 15 % held-out test slice is excluded (`TEST_FRACTION = 0.15`, `TEST_SEED = 99`, fixed in `training/run_proper_eval.py`). The held-out test slice is not used by `calibrate.py` and is reserved for the deploy-time numbers reported in `RESULTS_*.md`.
- **Grid ranges (from `calibrate.py:grid_search`).**
  - $w_1 \in \mathcal{W} = \{0.30, 0.35, 0.40, \ldots, 0.90\}$ — 13 values, step 0.05 (`np.linspace(0.30, 0.90, 13)`).
  - $\tau_a \in \mathcal{T} = \{0.30, 0.35, \ldots, 0.90\}$ — 13 values, step 0.05.
  - $w_2$ is not searched independently; the constraint $w_2 = 1 - w_1$ is enforced.
  - Total candidates evaluated: $|\mathcal{W}| \times |\mathcal{T}| = 169$.
- **Confidence-threshold candidates** (used by `pick_confidence_threshold`): $\tau_c \in \mathcal{C} = \{0.30, 0.35, \ldots, 0.90\}$ — same range as $\mathcal{T}$.
- **Final calibrated values (current Model B, `artifacts/thresholds.json`).**

| Field | Value |
|---|---|
| $w_1^{*}$ (Transformer weight) | $0.85$ |
| $w_2^{*}$ (AutoEncoder weight) | $0.15$ |
| $\tau_a^{*}$ (anomaly threshold) | $0.60$ |
| $\tau_c^{*}$ (confidence threshold) | $0.00$ |
| $p_{10}$ (AE-error 10th-percentile) | $1.40 \times 10^{-8}$ |
| $p_{90}$ (AE-error 90th-percentile) | $1.50 \times 10^{-7}$ |

The reported $\tau_c^{*} = 0$ is below the searched grid $\mathcal{C}$ and reflects a deliberate operational decision to disable the confidence gate in the live detector for this build (the AND-gate $c \ge \tau_a \land \sigma(C_\phi(\mathbf{x})) \ge \tau_c$ degenerates to $c \ge \tau_a$). The trained MLP itself is still produced and shipped as `confidence_scorer.pt`.

---

## Algorithm 1 — Threshold and Weight Calibration via Grid Search

**Input**

- $\mathcal{D}_{\text{cal}} = \{(\mathbf{w}_i, y_i)\}_{i=1}^{N}$, the calibration set of $N$ sliding windows with binary ground-truth labels $y_i \in \{0,1\}$ (anomaly / normal). $\mathcal{D}_{\text{cal}}$ excludes the held-out test slice.
- $s_T \in \mathbb{R}^{N}$, Transformer anomaly probabilities, where $s_T[i] = \sigma(\text{anomaly\_logit}(\mathbf{w}_i))$.
- $e_{\text{AE}} \in \mathbb{R}_{\ge 0}^{N}$, AutoEncoder reconstruction errors $\| \hat{\mathbf{w}}_i - \bar{\mathbf{w}}_i \|_2^2 / d$ where $\bar{\mathbf{w}}_i$ is the mean-pooled window embedding.
- Candidate sets $\mathcal{W}$, $\mathcal{T}$, $\mathcal{C}$ defined above.

**Output**

- Calibrated ensemble parameters $(w_1^{*}, w_2^{*}, \tau_a^{*})$.
- Trained Confidence MLP $C_\phi : \mathbb{R}^{4} \to \mathbb{R}$ producing logits, with paired threshold $\tau_c^{*}$.
- Normalisation percentiles $p_{10}$, $p_{90}$ for the AE error.

**Procedure**

1. **AE-error normalisation percentiles.** Compute $p_{10} \leftarrow \mathrm{Pct}_{10}(e_{\text{AE}})$ and $p_{90} \leftarrow \mathrm{Pct}_{90}(e_{\text{AE}})$.

2. **Normalise AE errors** by percentile clip-and-scale:
$$
\hat{e}_{\text{AE}}[i] \leftarrow \mathrm{clip}\!\left( \frac{e_{\text{AE}}[i] - p_{10}}{\max(p_{90} - p_{10},\, \varepsilon)},\; 0,\; 1 \right), \quad i = 1, \ldots, N
$$

3. **Initialise** the best-so-far record $F_1^{*} \leftarrow -1$; $(w_1^{*}, \tau_a^{*}) \leftarrow$ (any element of $\mathcal{W} \times \mathcal{T}$).

4. **Grid search.** For each $w_1 \in \mathcal{W}$:

    a. Set $w_2 \leftarrow 1 - w_1$.

    b. Compute the combined ensemble score $c[i] \leftarrow w_1 \cdot s_T[i] + w_2 \cdot \hat{e}_{\text{AE}}[i]$ for $i = 1, \ldots, N$.

    c. For each $\tau \in \mathcal{T}$:
        - Predict $\hat{y}[i] \leftarrow \mathbf{1}\{ c[i] \ge \tau \}$.
        - Compute $F_1 \leftarrow \mathrm{F1}(\hat{y}, y)$ via $\mathrm{TP}, \mathrm{FP}, \mathrm{FN}$.
        - If $F_1 > F_1^{*}$: update $(w_1^{*}, w_2^{*}, \tau_a^{*}, F_1^{*}) \leftarrow (w_1, w_2, \tau, F_1)$.

5. **Compute the directional confidence target.** Using the calibrated triplet, recompute $c^{*}[i] \leftarrow w_1^{*} \cdot s_T[i] + w_2^{*} \cdot \hat{e}_{\text{AE}}[i]$ and let $\hat{y}^{*}[i] \leftarrow \mathbf{1}\{ c^{*}[i] \ge \tau_a^{*} \}$. Define
$$
\mathrm{correct}[i] \leftarrow \mathbf{1}\{ \hat{y}^{*}[i] = y[i] \}, \qquad
m[i] \leftarrow \mathrm{clip}\!\left( \frac{|c^{*}[i] - \tau_a^{*}|}{\max(\tau_a^{*},\, 1 - \tau_a^{*})},\; 0,\; 1 \right)
$$
$$
t[i] \leftarrow \mathrm{correct}[i] \cdot m[i] \;\in [0, 1]
$$

    The target $t[i]$ rewards predictions that are both correct and decisively far from the decision boundary; it is zero for incorrect predictions regardless of margin.

6. **Build confidence features.** $\mathbf{x}[i] \leftarrow ( s_T[i],\; \hat{e}_{\text{AE}}[i],\; 0,\; 0 )$. The last two coordinates are reserved for sequence-length and time-of-day signals injectable by the live detector at inference.

7. **Train the Confidence MLP.** Define $C_\phi : \mathbb{R}^{4} \to \mathbb{R}$ as a feed-forward network with architecture $4 \to 32 \to 16 \to 1$, ReLU activations on the hidden layers, sigmoid applied at inference. Optimise the binary cross-entropy with logits loss
$$
\mathcal{L}(\phi) = -\frac{1}{|\mathcal{B}|} \sum_{i \in \mathcal{B}} \big[ t[i] \log \sigma(C_\phi(\mathbf{x}[i])) + (1 - t[i]) \log (1 - \sigma(C_\phi(\mathbf{x}[i]))) \big]
$$
using Adam (learning rate $10^{-3}$, batch size $64$) for $20$ epochs, with an internal $80/20$ split of $(\mathbf{x}, t)$ and best-val-loss early stopping.

8. **Select the confidence threshold.** Let $p[i] \leftarrow \sigma(C_\phi(\mathbf{x}[i]))$. For each $\tau_c \in \mathcal{C}$, compute
$$
F_1 \leftarrow \mathrm{F1}\!\left( \mathbf{1}\{ p \ge \tau_c \},\; \mathbf{1}\{ t \ge \tau_c \} \right)
$$
and choose $\tau_c^{*}$ as the threshold maximising this F1.

9. **Persist artefacts.** Write `thresholds.json` $\leftarrow \{ w_1^{*}, w_2^{*}, \tau_a^{*}, \tau_c^{*}, p_{10}, p_{90} \}$ and save $C_\phi$ as a TorchScript module to `confidence_scorer.pt`.

10. **Return** $(w_1^{*}, w_2^{*}, \tau_a^{*}, \tau_c^{*}, C_\phi, p_{10}, p_{90})$.

**Live decision rule.** At inference time, the detector flags a window $\mathbf{w}$ as an anomaly iff
$$
c(\mathbf{w}) \ge \tau_a^{*} \;\land\; \sigma\!\left( C_\phi(\mathbf{x}(\mathbf{w})) \right) \ge \tau_c^{*},
$$
where $c(\mathbf{w}) = w_1^{*} \cdot s_T(\mathbf{w}) + w_2^{*} \cdot \hat{e}_{\text{AE}}(\mathbf{w})$ and $\hat{e}_{\text{AE}}$ uses the same $(p_{10}, p_{90})$ stored in `thresholds.json`.

---

## Notes on translating to LaTeX

- The `\Input` / `\Output` macros from `algpseudocode` map cleanly onto the **Input** / **Output** sections above.
- Step 4 nests two `\For ... \EndFor` loops; Step 4(c) becomes the inner `\For` block.
- Math display lines (Steps 2, 5, 7, 8) belong inside `\State \(\ldots\)` if rendered with `algorithmic`, or inside `\STATE $\ldots$` with `algorithmicx`.
- The "Live decision rule" paragraph is best placed in the prose immediately following the algorithm float, not inside the `algorithm` environment itself.
