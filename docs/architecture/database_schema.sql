-- AIOps-LogGuard — Postgres schema
-- Run as a migration on first boot

CREATE TABLE IF NOT EXISTS anomalies (
    id TEXT PRIMARY KEY,                            -- format: anom_<iso8601>_<4hex>
    detected_at TIMESTAMPTZ NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'warning', 'info')),
    source TEXT NOT NULL,                           -- hostname / service identifier (display)
    origin TEXT NOT NULL DEFAULT 'live-stream'      -- 'live-stream' | 'user-upload' (filter tag)
        CHECK (origin IN ('live-stream', 'user-upload')),
    ensemble_score REAL,                            -- 0..1
    confidence REAL,                                -- 0..1, from confidence MLP
    failure_probability REAL,                       -- 0..1, from Transformer failure head
    predicted_failure_window_min INT,               -- minutes until predicted failure (nullable)
    log_template TEXT,                              -- Drain3 template
    sequence_preview JSONB,                         -- list of 20 log lines in the window
    top_contributing_lines JSONB,                   -- [{line, attention}, ...] from Transformer attention
    cluster_id TEXT,                                -- dedup cluster
    cluster_size INT DEFAULT 1,                     -- how many anomalies in this cluster
    explanation_status TEXT DEFAULT 'pending'       -- 'pending' | 'ready' | 'failed'
        CHECK (explanation_status IN ('pending', 'ready', 'failed')),
    root_cause TEXT,                                -- filled by RAG worker
    recommended_fix TEXT,                           -- filled by RAG worker
    similar_incidents JSONB,                        -- list of incident IDs from FAISS
    feedback TEXT                                   -- 'true_positive' | 'false_positive' | NULL
        CHECK (feedback IS NULL OR feedback IN ('true_positive', 'false_positive'))
);

CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at ON anomalies (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies (severity);
CREATE INDEX IF NOT EXISTS idx_anomalies_cluster ON anomalies (cluster_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_explanation_status ON anomalies (explanation_status);

-- Idempotent migration for existing DBs that pre-date the origin column.
-- MUST run BEFORE the idx_anomalies_origin index below — for a fresh DB
-- the column already exists from CREATE TABLE; for an upgraded DB this
-- ADDs it. Postgres 11+ ADD COLUMN with a default doesn't rewrite the
-- table; the CHECK constraint on origin lives only on CREATE TABLE
-- because adding it post-hoc would scan every existing row. The model
-- layer enforces the literal at write time, so functionally same guarantee.
ALTER TABLE anomalies
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'live-stream';

CREATE INDEX IF NOT EXISTS idx_anomalies_origin ON anomalies (origin);

-- For metrics/timeline endpoint efficiency
CREATE INDEX IF NOT EXISTS idx_anomalies_detected_severity
    ON anomalies (detected_at DESC, severity);

-- Drift events log (for audit trail of when retrains were triggered)
CREATE TABLE IF NOT EXISTS drift_events (
    id SERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    psi_score REAL NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('drift_high', 'drift_critical')),
    triggered_retrain BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_drift_detected_at ON drift_events (detected_at DESC);

-- Optional: training run audit log
CREATE TABLE IF NOT EXISTS training_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    dataset TEXT NOT NULL,                          -- 'hdfs' | 'bgl' | 'feedback_augmented'
    f1_score REAL,
    precision_score REAL,
    recall_score REAL,
    artifacts_path TEXT,                            -- where the .pt files were saved
    notes TEXT
);
