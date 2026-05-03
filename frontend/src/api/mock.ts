/**
 * Hardcoded mock fixtures — 15 web-application anomalies covering all
 * severities, all explanation states (pending / ready / failed), varied
 * sources, varied cluster sizes, and a mix of timestamps so the live feed
 * looks realistic.
 *
 * The fixtures are computed RELATIVE TO `Date.now()` so every page load
 * gives fresh "X min ago" timestamps — the demo always looks live.
 *
 * All shapes here MUST match `src/types.ts`. TypeScript will catch any drift.
 */
import type {
  Anomaly,
  DriftStatus,
  Explanation,
  MetricsSummary,
  TimelineBucket,
  TimelineResponse,
  TimelineWindow,
} from "../types";

// -- helpers --------------------------------------------------------------

function isoMinutesAgo(min: number): string {
  // ISO 8601 UTC with 'Z' suffix (no fractional seconds), per the contract.
  return new Date(Date.now() - min * 60_000)
    .toISOString()
    .replace(/\.\d+Z$/, "Z");
}

// -- anomaly fixtures ------------------------------------------------------

export const MOCK_ANOMALIES: Anomaly[] = [
  // 1 — critical, recent, ready
  {
    id: "anom_a1b2c3d4",
    detected_at: isoMinutesAgo(2),
    severity: "critical",
    source: "nova-api-prod-3",
    origin: "live-stream",
    ensemble_score: 0.94,
    confidence: 0.91,
    failure_probability: 0.82,
    predicted_failure_window_min: 8,
    log_template:
      "ERROR keystone-api Failed to authenticate user <*> from <IP>",
    sequence_preview: [
      "INFO keystone-api auth request user=alice from 192.168.1.42",
      "INFO keystone-api auth request user=bob from 192.168.1.43",
      "WARN keystone-api elevated auth-fail rate from /24",
      "ERROR keystone-api Failed to authenticate user 'alice' from 192.168.1.42",
      "ERROR keystone-api Failed to authenticate user 'bob' from 192.168.1.43",
      "ERROR keystone-api Failed to authenticate user 'eve' from 192.168.1.44",
    ],
    top_contributing_lines: [
      {
        line: "ERROR keystone-api Failed to authenticate user 'alice' from 192.168.1.42",
        attention: 0.31,
      },
      {
        line: "ERROR keystone-api Failed to authenticate user 'bob' from 192.168.1.43",
        attention: 0.27,
      },
      {
        line: "WARN keystone-api elevated auth-fail rate from 192.168.1.0/24",
        attention: 0.18,
      },
      {
        line: "ERROR keystone-api token refresh denied for session sess_a1b2",
        attention: 0.11,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_auth_burst_a1",
    cluster_size: 14,
  },

  // 2 — critical, RAG still pending (shows the loading state)
  {
    id: "anom_b2c3d4e5",
    detected_at: isoMinutesAgo(3),
    severity: "critical",
    source: "neutron-server-1",
    origin: "live-stream",
    ensemble_score: 0.91,
    confidence: 0.86,
    failure_probability: 0.75,
    predicted_failure_window_min: 12,
    log_template: "ERROR connection pool exhausted reached max <*>",
    sequence_preview: [
      "INFO neutron-server pool size=98/100 utilisation=98%",
      "WARN neutron-server pool wait time elevated p99=420ms",
      "ERROR neutron-server connection pool exhausted reached max 100",
      "ERROR neutron-server connection pool exhausted reached max 100",
      "WARN neutron-server queueing requests, depth=42",
    ],
    top_contributing_lines: [
      {
        line: "ERROR neutron-server connection pool exhausted reached max 100",
        attention: 0.34,
      },
      {
        line: "WARN neutron-server pool wait time elevated p99=420ms",
        attention: 0.22,
      },
      {
        line: "WARN neutron-server queueing requests, depth=42",
        attention: 0.16,
      },
    ],
    explanation_status: "pending",
    cluster_id: "clu_pool_b2",
    cluster_size: 7,
  },

  // 3 — critical, ready
  {
    id: "anom_c3d4e5f6",
    detected_at: isoMinutesAgo(7),
    severity: "critical",
    source: "glance-api-2",
    origin: "live-stream",
    ensemble_score: 0.89,
    confidence: 0.83,
    failure_probability: 0.71,
    predicted_failure_window_min: 5,
    log_template: "ERROR upstream 5xx burst service <*> count <*>",
    sequence_preview: [
      "INFO glance-api proxy request to image-store ok",
      "WARN glance-api upstream 5xx from image-store count=3",
      "WARN glance-api upstream 5xx from image-store count=7",
      "ERROR glance-api upstream 5xx burst service image-store count=23",
      "ERROR glance-api retry budget exhausted",
    ],
    top_contributing_lines: [
      {
        line: "ERROR glance-api upstream 5xx burst service image-store count=23",
        attention: 0.29,
      },
      {
        line: "ERROR glance-api retry budget exhausted",
        attention: 0.21,
      },
      {
        line: "WARN glance-api upstream 5xx from image-store count=7",
        attention: 0.14,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_upstream_c3",
    cluster_size: 23,
  },

  // 4 — critical, OOM
  {
    id: "anom_d4e5f6a7",
    detected_at: isoMinutesAgo(18),
    severity: "critical",
    source: "nova-api-prod-7",
    origin: "live-stream",
    ensemble_score: 0.87,
    confidence: 0.79,
    failure_probability: 0.68,
    predicted_failure_window_min: 15,
    log_template: "ERROR OOMKilled container terminated <*>",
    sequence_preview: [
      "INFO nova-api memory rss=4.2GiB",
      "WARN nova-api memory rss=5.8GiB pressure detected",
      "ERROR OOMKilled container terminated nova-api-prod-7",
      "INFO kubelet restarting pod nova-api-prod-7",
    ],
    top_contributing_lines: [
      {
        line: "ERROR OOMKilled container terminated nova-api-prod-7",
        attention: 0.37,
      },
      {
        line: "WARN nova-api memory rss=5.8GiB pressure detected",
        attention: 0.21,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_oom_d4",
    cluster_size: 1,
  },

  // 5 — warning, slow query
  {
    id: "anom_e5f6a7b8",
    detected_at: isoMinutesAgo(11),
    severity: "warning",
    source: "neutron-server-3",
    origin: "live-stream",
    ensemble_score: 0.74,
    confidence: 0.71,
    failure_probability: 0.42,
    predicted_failure_window_min: null,
    log_template: "WARN slow_query duration=<*>ms threshold=<*>",
    sequence_preview: [
      "INFO neutron-server query SELECT * FROM ports WHERE network_id=...",
      "WARN neutron-server slow_query duration=1832ms threshold=1000ms",
      "WARN neutron-server slow_query duration=2104ms threshold=1000ms",
    ],
    top_contributing_lines: [
      {
        line: "WARN neutron-server slow_query duration=2104ms threshold=1000ms",
        attention: 0.27,
      },
      {
        line: "WARN neutron-server slow_query duration=1832ms threshold=1000ms",
        attention: 0.22,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_slow_e5",
    cluster_size: 3,
  },

  // 6 — warning, heartbeat lost
  {
    id: "anom_f6a7b8c9",
    detected_at: isoMinutesAgo(23),
    severity: "warning",
    source: "namenode-prod-1",
    origin: "live-stream",
    ensemble_score: 0.68,
    confidence: 0.62,
    failure_probability: 0.38,
    predicted_failure_window_min: null,
    log_template: "WARN heartbeat lost from <*>",
    sequence_preview: [
      "INFO namenode heartbeat from datanode-7 ok",
      "INFO namenode heartbeat from datanode-7 ok",
      "WARN namenode heartbeat lost from datanode-7",
      "WARN namenode heartbeat lost from datanode-7",
    ],
    top_contributing_lines: [
      {
        line: "WARN namenode heartbeat lost from datanode-7",
        attention: 0.19,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_heartbeat_f6",
    cluster_size: 4,
  },

  // 7 — warning, rate limit
  {
    id: "anom_a7b8c9d0",
    detected_at: isoMinutesAgo(31),
    severity: "warning",
    source: "nova-api-prod-2",
    origin: "live-stream",
    ensemble_score: 0.71,
    confidence: 0.66,
    failure_probability: 0.35,
    predicted_failure_window_min: null,
    log_template: "WARN rate limit exceeded client <*> limit <*>",
    sequence_preview: [
      "INFO nova-api request_id=req-abc client=10.0.1.50 ok",
      "WARN nova-api rate limit exceeded client 10.0.1.50 limit 100/s",
      "WARN nova-api rate limit exceeded client 10.0.1.50 limit 100/s",
    ],
    top_contributing_lines: [
      {
        line: "WARN nova-api rate limit exceeded client 10.0.1.50 limit 100/s",
        attention: 0.24,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_ratelimit_a7",
    cluster_size: 5,
  },

  // 8 — warning, cache stampede
  {
    id: "anom_b8c9d0e1",
    detected_at: isoMinutesAgo(38),
    severity: "warning",
    source: "redis-cache-master",
    origin: "live-stream",
    ensemble_score: 0.66,
    confidence: 0.61,
    failure_probability: 0.31,
    predicted_failure_window_min: null,
    log_template: "WARN cache stampede repeated misses key <*>",
    sequence_preview: [
      "INFO redis cache miss key=user:profile:12345",
      "WARN redis repeated misses key=user:profile:12345 count=23",
      "WARN redis cache stampede repeated misses key=user:profile:12345",
    ],
    top_contributing_lines: [
      {
        line: "WARN redis cache stampede repeated misses key=user:profile:12345",
        attention: 0.21,
      },
      {
        line: "WARN redis repeated misses key=user:profile:12345 count=23",
        attention: 0.15,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_cache_b8",
    cluster_size: 8,
  },

  // 9 — warning, RAG failed (rare path)
  {
    id: "anom_c9d0e1f2",
    detected_at: isoMinutesAgo(44),
    severity: "warning",
    source: "postgres-replica-1",
    origin: "live-stream",
    ensemble_score: 0.69,
    confidence: 0.64,
    failure_probability: 0.34,
    predicted_failure_window_min: null,
    log_template: "WARN replication lag <*>s threshold <*>s",
    sequence_preview: [
      "INFO postgres replication lag 2s",
      "WARN postgres replication lag 18s threshold 10s",
      "WARN postgres replication lag 24s threshold 10s",
    ],
    top_contributing_lines: [
      {
        line: "WARN postgres replication lag 24s threshold 10s",
        attention: 0.23,
      },
    ],
    explanation_status: "failed",
    cluster_id: "clu_repl_c9",
    cluster_size: 2,
  },

  // 10 — info, packet responder
  {
    id: "anom_d0e1f2a3",
    detected_at: isoMinutesAgo(52),
    severity: "info",
    source: "datanode-prod-2",
    origin: "live-stream",
    ensemble_score: 0.41,
    confidence: 0.55,
    failure_probability: 0.12,
    predicted_failure_window_min: null,
    log_template: "INFO PacketResponder <*> for block <*> terminating",
    sequence_preview: [
      "INFO PacketResponder 1 for block blk_3 terminating",
      "INFO PacketResponder 2 for block blk_4 terminating",
    ],
    top_contributing_lines: [
      {
        line: "INFO PacketResponder 1 for block blk_3 terminating",
        attention: 0.08,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_packet_d0",
    cluster_size: 27,
  },

  // 11 — info, normal request
  {
    id: "anom_e1f2a3b4",
    detected_at: isoMinutesAgo(64),
    severity: "info",
    source: "nova-api-prod-5",
    origin: "live-stream",
    ensemble_score: 0.36,
    confidence: 0.51,
    failure_probability: 0.08,
    predicted_failure_window_min: null,
    log_template: "INFO request completed status=200 duration=<*>",
    sequence_preview: [
      "INFO nova-api request completed status=200 duration=42ms",
      "INFO nova-api request completed status=200 duration=51ms",
    ],
    top_contributing_lines: [
      {
        line: "INFO nova-api request completed status=200 duration=42ms",
        attention: 0.05,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_request_e1",
    cluster_size: 102,
  },

  // 12 — info, successful auth
  {
    id: "anom_f2a3b4c5",
    detected_at: isoMinutesAgo(78),
    severity: "info",
    source: "keystone-api-2",
    origin: "live-stream",
    ensemble_score: 0.34,
    confidence: 0.49,
    failure_probability: 0.06,
    predicted_failure_window_min: null,
    log_template: "INFO Successful authentication for user <*>",
    sequence_preview: [
      "INFO keystone-api Successful authentication for user 'charlie'",
      "INFO keystone-api Successful authentication for user 'dave'",
    ],
    top_contributing_lines: [
      {
        line: "INFO keystone-api Successful authentication for user 'charlie'",
        attention: 0.04,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_auth_f2",
    cluster_size: 45,
  },

  // 13 — info, metrics scrape
  {
    id: "anom_a3b4c5d6",
    detected_at: isoMinutesAgo(95),
    severity: "info",
    source: "prometheus-collector",
    origin: "live-stream",
    ensemble_score: 0.32,
    confidence: 0.48,
    failure_probability: 0.05,
    predicted_failure_window_min: null,
    log_template: "INFO scrape completed targets=<*> duration=<*>ms",
    sequence_preview: [
      "INFO prometheus scrape completed targets=124 duration=312ms",
    ],
    top_contributing_lines: [
      {
        line: "INFO prometheus scrape completed targets=124 duration=312ms",
        attention: 0.04,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_scrape_a3",
    cluster_size: 18,
  },

  // 14 — info, verification ok
  {
    id: "anom_b4c5d6e7",
    detected_at: isoMinutesAgo(112),
    severity: "info",
    source: "datanode-prod-4",
    origin: "live-stream",
    ensemble_score: 0.31,
    confidence: 0.47,
    failure_probability: 0.04,
    predicted_failure_window_min: null,
    log_template: "INFO Verification succeeded for block <*>",
    sequence_preview: [
      "INFO Verification succeeded for block blk_8473100",
    ],
    top_contributing_lines: [
      {
        line: "INFO Verification succeeded for block blk_8473100",
        attention: 0.03,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_verify_b4",
    cluster_size: 14,
  },

  // 15 — warning, healthcheck flap
  {
    id: "anom_c5d6e7f8",
    detected_at: isoMinutesAgo(128),
    severity: "warning",
    source: "rabbitmq-1",
    origin: "live-stream",
    ensemble_score: 0.65,
    confidence: 0.59,
    failure_probability: 0.29,
    predicted_failure_window_min: null,
    log_template: "WARN healthcheck failed response code <*> path <*>",
    sequence_preview: [
      "INFO rabbitmq healthcheck ok status=200",
      "WARN rabbitmq healthcheck failed response code 503 path /healthz",
      "INFO rabbitmq healthcheck ok status=200",
      "WARN rabbitmq healthcheck failed response code 503 path /healthz",
    ],
    top_contributing_lines: [
      {
        line: "WARN rabbitmq healthcheck failed response code 503 path /healthz",
        attention: 0.18,
      },
    ],
    explanation_status: "ready",
    cluster_id: "clu_health_c5",
    cluster_size: 1,
  },
];

// -- explanations (one per anomaly with status="ready") --------------------

export const MOCK_EXPLANATIONS: Record<string, Explanation> = {
  anom_a1b2c3d4: {
    root_cause:
      "Concentrated burst of authentication failures from a small IP range against `keystone-api`. Pattern matches a credential-stuffing or brute-force attempt — low success ratio and very high failure rate from /24 source.",
    recommended_fix:
      "1. Identify the offending source: check `pf_stat_activity`-equivalent for the auth-fail IPs.\n2. Apply WAF / firewall rate-limit on `192.168.1.0/24` or block at the ingress for 1 hour.\n3. Force a credential rotation for any user accounts with multiple failed attempts.\n4. Verify MFA is enforced for all admin accounts.\n5. Open an incident ticket; capture the source IPs for post-mortem.",
    similar_incidents: [
      {
        incident_id: "syn_007",
        template: "ERROR authentication failed user <*> ip <*>",
        resolved_at: "2025-12-14T08:32:00Z",
        similarity_score: 0.91,
      },
      {
        incident_id: "inc_b3a1",
        template: "WARN auth burst from /24 source",
        resolved_at: "2025-09-22T13:15:00Z",
        similarity_score: 0.78,
      },
    ],
    attention_weights: [0.31, 0.27, 0.18, 0.11, 0.07, 0.05, 0.01],
  },
  anom_c3d4e5f6: {
    root_cause:
      "Downstream `image-store` service is returning 5xx at an elevated rate. `glance-api`'s retry budget is exhausted, which means subsequent client requests will fail fast. Cascading failure is likely if not contained.",
    recommended_fix:
      "1. Check `image-store`'s status page / on-call.\n2. Engage the circuit breaker — fail fast instead of cascading retries.\n3. Verify the retry budget setting isn't amplifying load on the downstream.\n4. Surface user-facing 503 with a clear error page.\n5. Reach out to the storage team on-call.",
    similar_incidents: [
      {
        incident_id: "syn_019",
        template: "ERROR upstream 5xx burst service <*> count <*>",
        resolved_at: "2026-01-15T14:32:00Z",
        similarity_score: 0.95,
      },
    ],
    attention_weights: [0.29, 0.21, 0.14, 0.09, 0.05],
  },
  anom_d4e5f6a7: {
    root_cause:
      "`nova-api-prod-7` was killed by the kernel OOM killer after exceeding its 6GiB cgroup limit. RSS climbed steadily for 30 minutes without a corresponding traffic increase — suggests a slow memory leak rather than a load spike.",
    recommended_fix:
      "1. `kubectl describe pod nova-api-prod-7` — confirm OOMKilled exit code.\n2. Check Grafana for memory growth pattern; correlate with deployment timeline.\n3. Take a heap snapshot from a peer pod and look for unbounded caches.\n4. As a stop-gap, raise the memory limit to 8GiB; schedule a fix for the leak.\n5. Add a memory-rate-of-growth alert at 200MB/hour.",
    similar_incidents: [
      {
        incident_id: "syn_002",
        template: "ERROR OOMKilled container terminated <*>",
        resolved_at: "2025-11-03T22:00:00Z",
        similarity_score: 0.97,
      },
      {
        incident_id: "syn_017",
        template: "WARN memory leak detected rss growth <*> mb per hour",
        resolved_at: "2025-08-09T11:00:00Z",
        similarity_score: 0.71,
      },
    ],
    attention_weights: [0.37, 0.21, 0.14, 0.09],
  },
  anom_e5f6a7b8: {
    root_cause:
      "`neutron-server-3` is hitting slow-query thresholds on `SELECT FROM ports`. Likely a missing index on `network_id`, or a stale planner statistic causing a sequential scan instead of an index lookup.",
    recommended_fix:
      "1. Pull the slow query and run `EXPLAIN ANALYZE`.\n2. Check for missing indexes on `network_id` or compound predicates.\n3. Refresh statistics: `ANALYZE ports`.\n4. Look at `pg_stat_activity` for blocking transactions.\n5. Add a query timeout so this doesn't tie up workers.",
    similar_incidents: [
      {
        incident_id: "syn_008",
        template: "WARN slow query took <*> ms threshold <*>",
        resolved_at: "2025-12-08T09:14:00Z",
        similarity_score: 0.88,
      },
    ],
    attention_weights: [0.27, 0.22, 0.13, 0.06],
  },
  anom_f6a7b8c9: {
    root_cause:
      "`namenode` lost heartbeat from `datanode-7` for ~30 seconds, then recovered. Likely a transient network partition, GC pause on the datanode, or kernel-level TCP issue. Datanode came back without intervention.",
    recommended_fix:
      "1. Check `datanode-7` system logs around the time window for GC pauses or kernel events.\n2. `mtr` from the namenode to confirm no packet loss right now.\n3. If recurring, raise the heartbeat timeout from 10s to 15s.\n4. Add an alert if a single datanode flaps more than 3 times per hour.",
    similar_incidents: [
      {
        incident_id: "syn_004",
        template: "ERROR connection timed out upstream <*>",
        resolved_at: "2025-10-12T18:22:00Z",
        similarity_score: 0.66,
      },
    ],
    attention_weights: [0.19, 0.12, 0.06, 0.04],
  },
  anom_a7b8c9d0: {
    root_cause:
      "Single client at `10.0.1.50` is being throttled at the API gateway after exceeding 100 requests/sec. Unclear if this is legitimate traffic growth or a buggy retry loop.",
    recommended_fix:
      "1. Identify the client owner — check the `X-Client-Id` header in upstream logs.\n2. Verify their retry logic uses exponential backoff.\n3. If genuine traffic, raise the rate-limit and notify the client.\n4. If abusive, contact the team and consider an IP-level block.\n5. Surface 429 responses cleanly so clients self-throttle.",
    similar_incidents: [
      {
        incident_id: "syn_012",
        template: "WARN rate limit exceeded client <*> limit <*>",
        resolved_at: "2025-09-02T16:40:00Z",
        similarity_score: 0.93,
      },
    ],
    attention_weights: [0.24, 0.18, 0.09, 0.04],
  },
  anom_b8c9d0e1: {
    root_cause:
      "Many concurrent requests for `user:profile:12345` are bypassing the cache and hitting the database — a thundering-herd cache stampede. The TTL just expired and there's no single-flight protection on the read path.",
    recommended_fix:
      "1. Add request coalescing (single-flight) around the cache fill for hot keys.\n2. Use stale-while-revalidate so one request refreshes while others get the stale value.\n3. Stagger TTLs by jitter so popular keys don't all expire at the same instant.\n4. Increase the TTL if the data tolerates it.\n5. Consider a write-through cache instead of write-around.",
    similar_incidents: [
      {
        incident_id: "syn_011",
        template: "WARN cache stampede repeated misses key <*>",
        resolved_at: "2025-11-18T10:08:00Z",
        similarity_score: 0.94,
      },
    ],
    attention_weights: [0.21, 0.15, 0.08, 0.04],
  },
  anom_d0e1f2a3: {
    root_cause:
      "Routine `PacketResponder` lifecycle event — slightly elevated frequency but within healthy operating envelope. No action required.",
    recommended_fix: "No action required. Continue monitoring.",
    similar_incidents: [],
    attention_weights: [0.08, 0.05, 0.04],
  },
  anom_e1f2a3b4: {
    root_cause: "Standard 200-response request. Informational only.",
    recommended_fix: "No action required.",
    similar_incidents: [],
    attention_weights: [0.05, 0.03],
  },
  anom_f2a3b4c5: {
    root_cause: "Successful authentication. Informational only.",
    recommended_fix: "No action required.",
    similar_incidents: [],
    attention_weights: [0.04, 0.03],
  },
  anom_a3b4c5d6: {
    root_cause: "Routine metrics scrape completed within SLO. Informational only.",
    recommended_fix: "No action required.",
    similar_incidents: [],
    attention_weights: [0.04, 0.03],
  },
  anom_b4c5d6e7: {
    root_cause: "Block verification succeeded. Informational only.",
    recommended_fix: "No action required.",
    similar_incidents: [],
    attention_weights: [0.03, 0.02],
  },
  anom_c5d6e7f8: {
    root_cause:
      "Healthcheck on `rabbitmq-1` is flapping between 200 and 503. Could be a transient backend issue or an overly strict healthcheck verifying a downstream dependency. Distinguish liveness (\"is the process alive\") from readiness (\"are deps healthy\") to avoid false LB removals.",
    recommended_fix:
      "1. `curl /healthz` manually — what does it actually return?\n2. Check whether the healthcheck verifies external deps (DB, Redis ping) and one is degraded.\n3. Loosen the healthcheck or split it; full-chain checks belong in monitoring, not the LB.\n4. Add jitter to the check interval to reduce simultaneous probes.",
    similar_incidents: [
      {
        incident_id: "syn_016",
        template: "ERROR healthcheck failed response code <*> path <*>",
        resolved_at: "2026-02-09T07:40:00Z",
        similarity_score: 0.86,
      },
    ],
    attention_weights: [0.18, 0.11, 0.06, 0.03],
  },
};

// -- metrics summary -------------------------------------------------------

export const MOCK_METRICS_SUMMARY: MetricsSummary = {
  total_24h: 142,
  critical_24h: MOCK_ANOMALIES.filter((a) => a.severity === "critical").length,
  warning_24h: MOCK_ANOMALIES.filter((a) => a.severity === "warning").length,
  info_24h: MOCK_ANOMALIES.filter((a) => a.severity === "info").length,
  avg_confidence: 0.84,
  drift_score: 0.12,
  last_retrain: "2026-04-25T03:00:00Z",
};

// -- timeline (per window) -------------------------------------------------

function buildTimeline(window: TimelineWindow): TimelineBucket[] {
  const config: Record<TimelineWindow, { count: number; stepMs: number }> = {
    "1h": { count: 60, stepMs: 60_000 },
    "24h": { count: 96, stepMs: 15 * 60_000 },
    "7d": { count: 168, stepMs: 60 * 60_000 },
  };
  const { count, stepMs } = config[window];
  const now = Date.now();
  const buckets: TimelineBucket[] = [];
  for (let i = count - 1; i >= 0; i--) {
    const ts = new Date(now - i * stepMs).toISOString().replace(/\.\d+Z$/, "Z");
    // Synthetic counts so the chart has texture: critical sparse,
    // warning periodic, info common.
    buckets.push({
      ts,
      critical: i % 30 === 7 ? 1 : 0,
      warning: i % 5 === 0 ? 2 : 0,
      info: i % 2 === 0 ? 3 : 1,
    });
  }
  return buckets;
}

export function mockTimeline(window: TimelineWindow): TimelineResponse {
  return { window, buckets: buildTimeline(window) };
}

// -- drift -----------------------------------------------------------------

export const MOCK_DRIFT: DriftStatus = {
  drift_score: 0.12,
  last_retrain: "2026-04-25T03:00:00Z",
  status: "healthy",
  psi_score: 0.08,
};

// -- helpers for the client ------------------------------------------------

export function findMockAnomaly(id: string): Anomaly | undefined {
  return MOCK_ANOMALIES.find((a) => a.id === id);
}

export function findMockExplanation(id: string): Explanation | undefined {
  return MOCK_EXPLANATIONS[id];
}
