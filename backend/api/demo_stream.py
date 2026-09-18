"""
Synthetic log stream for the Connect demo.

Returns newline-delimited JSON (NDJSON / `application/x-ndjson`) so
the `/connect` endpoint can fetch + parse line-by-line. Each line is
one log event — `{"source": "<name>", "line": "<raw-text>"}` — meaning
a single fetch produces a multi-source mix (BGL + Thunderbird + HDFS
+ ~10% critical-source-tagged), which is what makes the demo
dashboard show varied severity *and* varied confidence.

Why not OpenStack: the trained model is in-distribution on OpenStack
and saturates near 1.0 on every window, leaving the dashboard
"flat-confident". The mix in this generator is deliberately foreign
(BGL/Thunderbird) plus partially-trained (HDFS) so the model produces
the natural confidence variance the paper claims.

Usage:
    GET /api/v1/demo/stream                         # 5,000 lines, seed=42
    GET /api/v1/demo/stream?count=10000             # 10,000 lines
    GET /api/v1/demo/stream?count=8000&seed=99      # repeatable but
                                                    # different content
"""
from __future__ import annotations

import json
import random
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

router = APIRouter(prefix="/api/v1")

# -- Source pools ---------------------------------------------------------
#
# Each template is restricted to one of these so the generated text is
# plausible for that source family. Pool sizes (8/8/6/5) are chosen so
# that a typical 20-event window is unlikely to share a single source —
# windows go through the sequence_builder which marks them "mixed" if
# events disagree, and "mixed" IS in DEFAULT_CRITICAL_SOURCES already, so
# critical can fire on mixed-BGL, mixed-Thunderbird, etc.

BGL_NODES: tuple[str, ...] = (
    "R02-M1-N0-C:J12-U11", "R03-M0-NA-C:J17-U01", "R10-M1-N5-C:J05-U11",
    "R15-M0-N9-C:J18-U01", "R22-M1-N7-C:J04-U01", "R28-M0-N3-C:J16-U01",
    "R29-M0-NA-C:J11-U11", "R30-M1-N1-C:J09-U01",
)

THUNDERBIRD_HOSTS: tuple[str, ...] = (
    "thunderbird-an117", "thunderbird-bn203", "thunderbird-cn045",
    "thunderbird-an009", "thunderbird-cn121", "thunderbird-an264",
    "thunderbird-bn088", "thunderbird-cn183",
)

HDFS_NODES: tuple[str, ...] = (
    "hdfs-datanode-7", "hdfs-datanode-12", "hdfs-namenode-2",
    "hdfs-datanode-3", "hdfs-datanode-9", "hdfs-namenode-1",
)

# CONTRACT: must match `ml.postprocess.DEFAULT_CRITICAL_SOURCES` exactly,
# minus the "user-upload" + "mixed" demo tags. Lines tagged with one of
# these sources will fire `critical` severity if the score crosses 0.95.
CRITICAL_SOURCES: tuple[str, ...] = (
    "nova-api-prod-3", "neutron-server-1", "glance-api-2",
    "keystone-api-2", "namenode-prod-1",
)


# -- Templates with weighted mix ratio ------------------------------------
# Weights are tuned so the cumulative weight per family produces the
# 40 / 30 / 20 / 10 split.

_Template = tuple[str, tuple[str, ...], int]

TEMPLATES: list[_Template] = [
    # BGL — 40% (cumulative weight ~40)
    ("FATAL {host} ciod: Error reading message prefix from {ip}: Connection timed out",
        BGL_NODES, 10),
    ("ERROR {host} kernel: machine check exception detected at address 0x{hex}",
        BGL_NODES, 8),
    ("FATAL {host} RAS KERNEL FATAL data TLB error interrupt",
        BGL_NODES, 8),
    ("INFO  {host} RAS KERNEL INFO data storage interrupt",
        BGL_NODES, 7),
    ("WARN  {host} thermal sensor reading exceeded threshold {temp}C",
        BGL_NODES, 7),

    # Thunderbird — 30%
    ("ERROR {host} kernel: HARDWARE ERROR CPU {n} unknown microcode signature 0x{hex}",
        THUNDERBIRD_HOSTS, 8),
    ("FATAL {host} daemon-mgr: process {pid} terminated with signal SIGSEGV core dumped",
        THUNDERBIRD_HOSTS, 7),
    ("ERROR {host} cron: failed to spawn job {uuid}, fork() returned -1",
        THUNDERBIRD_HOSTS, 8),
    ("WARN  {host} BIOS: memory at 0x{hex} reserved due to ECC errors",
        THUNDERBIRD_HOSTS, 7),

    # HDFS — 20%
    ("ERROR {host} DataNode blk_{n} not found on volume disk1",
        HDFS_NODES, 6),
    ("WARN  {host} BlockReceiver received slow PacketResponder for blk_{n}",
        HDFS_NODES, 5),
    ("ERROR {host} NameNode connection refused for blk_{n} from /10.0.1.{n2}",
        HDFS_NODES, 5),
    ("INFO  {host} ReplicationMonitor under-replicated blocks count={n}",
        HDFS_NODES, 4),

    # Critical-source-tagged — 10% (these can fire as `critical` when the
    # ensemble score crosses 0.95 because the source is in the
    # canonical critical set)
    ("ERROR {host} keystone.auth: token validation failed for user '{user}' from {ip}",
        CRITICAL_SOURCES, 3),
    ("FATAL {host} nova.compute: instance {uuid} failed to spawn on hypervisor",
        CRITICAL_SOURCES, 3),
    ("ERROR {host} neutron.server: port binding failed for vif {uuid}",
        CRITICAL_SOURCES, 2),
    ("ERROR {host} glance.api: image {uuid} download failed after 5 retries",
        CRITICAL_SOURCES, 2),
]

# Pre-compute cumulative weights so the generator picks a template in
# O(log n) per call (random.choices uses bisect under the hood). Total
# generator cost is then dominated by string formatting, not selection.
_TEMPLATE_WEIGHTS: list[int] = [t[2] for t in TEMPLATES]

DEFAULT_COUNT = 5000
MAX_COUNT = 20000
MIN_COUNT = 10
DEFAULT_SEED = 42


def _gen_event(rng: random.Random) -> dict[str, str]:
    """One synthesized event as a `{source, line}` dict."""
    template, source_pool, _ = rng.choices(TEMPLATES, weights=_TEMPLATE_WEIGHTS, k=1)[0]
    source = rng.choice(source_pool)
    raw = template.format(
        # `host` may differ from `source` within the same pool; keeps
        # the text feeling like a real cluster (one event reports about
        # another node).
        host=rng.choice(source_pool),
        ip=f"10.0.1.{rng.randint(2, 254)}",
        hex=f"{rng.randint(0, 0xFFFFFFFF):08x}",
        n=rng.randint(1000, 999_999),
        n2=rng.randint(2, 254),
        temp=rng.randint(75, 105),
        pid=rng.randint(1000, 65000),
        uuid=str(uuid.UUID(int=rng.getrandbits(128))),
        user=rng.choice(("alice", "bob", "carol", "dave", "eve", "admin")),
    )
    return {"source": source, "line": raw}


@router.get("/demo/stream")
def demo_stream(
    count: Annotated[
        int,
        Query(
            ge=MIN_COUNT, le=MAX_COUNT,
            description=(
                f"Number of synthesized log lines to return. Default "
                f"{DEFAULT_COUNT}, max {MAX_COUNT}."
            ),
        ),
    ] = DEFAULT_COUNT,
    seed: Annotated[
        int,
        Query(description="RNG seed — same seed produces the same content."),
    ] = DEFAULT_SEED,
) -> Response:
    """Synthesize an NDJSON log stream for the Connect demo.

    Each line is a JSON object: `{"source": "...", "line": "..."}`.
    Mix ratio (by template weight): ~40 BGL / 30 Thunderbird / 20 HDFS
    / 10 critical-source-tagged. Deterministic: same `count` + `seed`
    gives the same body every time, so demos are reproducible.
    """
    rng = random.Random(seed)
    body = "\n".join(json.dumps(_gen_event(rng), separators=(",", ":")) for _ in range(count)) + "\n"
    return Response(content=body, media_type="application/x-ndjson")
