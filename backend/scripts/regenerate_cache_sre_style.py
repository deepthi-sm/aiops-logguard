"""
Rewrite all 108 entries in `precomputed_explanations.json` with
hand-crafted SRE-postmortem-style explanations.

Why not LLaMA: regenerating 108 entries through llama3.2:1b takes ~30
minutes on CPU even with tight prompts, and the output remains
boilerplate ("This is consistent with prior incidents in the knowledge
base..."). For demo reliability we need explanations that read like a
senior SRE wrote them — confident, technical, no exposed RAG/training
machinery. A regex classifier dispatching to ~25 hand-written
templates does that job in under a second, with full control over
tone and length.

Each rewritten entry carries:
  ROOT CAUSE: 1-2 sentences naming the failure mode in technical terms
  IMPACT: 1 sentence on what's at risk for users / dependent services
  RECOMMENDED FIX: 2-3 numbered, actionable steps

The schema (`root_cause`, `recommended_fix`) is unchanged. ROOT CAUSE
+ IMPACT are concatenated into `root_cause`; the numbered fix list
into `recommended_fix`. Frontend rendering is unaffected.

Also clears `similar_incidents` per entry — those previously surfaced
"train_001731"-style identifiers in the UI that exposed the training
data origin.

Run:
    python -m scripts.regenerate_cache_sre_style
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / "artifacts" / "precomputed_explanations.json"


# -------------------- specifics extraction --------------------

def host(line: str) -> str:
    """Best-effort host or rack identifier."""
    # BGL rack: R02-M1-N0-C:J12-U11
    m = re.search(r"R\d+-M\d+-N[\dA-FE][\w:-]*", line)
    if m:
        return m.group(0).rstrip(",.:;")
    # Thunderbird-style: dn228, an117, cn121
    m = re.search(r"\bthunderbird-(?:[a-z]{2})\d+", line)
    if m:
        return m.group(0)
    m = re.search(r"\b(?:dn|an|cn)\d+\b", line)
    if m:
        return m.group(0)
    # OpenStack hostnames
    m = re.search(r"\bnova-(?:compute|api)-?\w*", line)
    if m:
        return m.group(0)
    # generic foo-bar3
    m = re.search(r"\b[a-z][\w-]{2,20}\d+\b", line)
    if m:
        return m.group(0)
    return "the affected node"


def ip(line: str) -> str:
    m = re.search(r"(?:\d{1,3}\.){3}\d{1,3}", line)
    return m.group(0) if m else "the remote endpoint"


def block(line: str) -> str:
    m = re.search(r"blk_[-\w]+", line)
    return m.group(0) if m else "the block"


def uuid_short(line: str) -> str:
    m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", line)
    return (m.group(0)[:8] + "…") if m else "the workload"


def user(line: str) -> str:
    m = re.search(r"user '(\w+)'", line)
    return m.group(1) if m else "the requesting user"


def pid(line: str) -> str:
    m = re.search(r"process (\d+)|\bpid[: ]?(\d+)|\[(\d+)\]", line, re.I)
    if m:
        return next(g for g in m.groups() if g)
    return "the process"


def hexaddr(line: str) -> str:
    m = re.search(r"0x[0-9a-fA-F]{4,}", line)
    return m.group(0) if m else "an unknown address"


def temp(line: str) -> str:
    m = re.search(r"(\d{2,3})C\b|threshold (\d+)", line)
    if m:
        return (m.group(1) or m.group(2)) + "°C"
    return "the threshold"


# -------------------- generators (return (root_cause, fix)) --------------------
# Each generator returns the two strings ready for the schema fields.
# The root_cause string uses a "ROOT CAUSE: ...  IMPACT: ..." structure
# matching the postmortem format the frontend renders verbatim.


def fmt(rc_line: str, impact_line: str, *fix_steps: str) -> tuple[str, str]:
    rc = f"ROOT CAUSE: {rc_line}\n\nIMPACT: {impact_line}"
    fix = "\n".join(f"{i}. {s}" for i, s in enumerate(fix_steps, 1))
    return rc, fix


def g_kernel_mce(tmpl: str, line: str) -> tuple[str, str]:
    h, addr = host(line), hexaddr(line)
    return fmt(
        f"The kernel on {h} raised a machine-check exception at {addr}, "
        f"indicating an uncorrectable hardware fault during a CPU "
        f"instruction or cache-line access. This signature is consistent "
        f"with a transient bit-flip or aging silicon on the affected board.",
        f"{h} is no longer trustworthy for user-facing work and may produce "
        f"silently corrupted results until taken out of rotation.",
        f"Cordon and drain workloads from {h} to a healthy peer immediately.",
        f"Capture the MCE banks via mcelog --client for the vendor RMA packet.",
        f"Schedule memtest86+ in the next maintenance window; replace the DIMM "
        f"or RMA the node if the failure recurs.",
    )


def g_tlb(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A data-TLB miss on {h} escalated into a fatal kernel exception, "
        f"meaning the MMU could not service a virtual-to-physical translation "
        f"for an in-flight memory operation. On compute nodes this typically "
        f"points at corrupted page tables or a failing memory controller.",
        f"The job step running on {h} has terminated; any partial output is "
        f"untrustworthy and must be re-run from the last checkpoint.",
        f"Mark {h} as drained and reroute the queued workload.",
        f"Pull the kernel ring buffer (`dmesg -T | tail -200`) and attach it "
        f"to the incident for vendor analysis.",
        f"If the same rack reports a second TLB fault within 24h, escalate "
        f"to hardware for board replacement.",
    )


def g_storage_interrupt(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A data-storage interrupt fired on {h} — the kernel observed a "
        f"memory-bus protocol violation while servicing a load. RAS logged "
        f"it at INFO because the controller recovered, but the underlying "
        f"signal is the same family as the fatal TLB and MCE events.",
        f"No immediate user impact, but {h} is showing early-warning patterns "
        f"that historically precede a hard failure within hours.",
        f"Flag {h} for elevated monitoring and reduce its scheduling priority.",
        f"Diff EDAC counters against the rack baseline; if any error count is "
        f"climbing, drain proactively.",
        f"Confirm the NIC and memory firmware are at the latest vendor revision.",
    )


def g_thermal(tmpl: str, line: str) -> tuple[str, str]:
    h, t = host(line), temp(line)
    return fmt(
        f"Thermal sensors on {h} are reading {t}, above the configured "
        f"safety threshold. Sustained operation at this temperature accelerates "
        f"silicon ageing and risks an emergency thermal trip from the BMC.",
        f"If the trend continues for another five minutes the node will "
        f"self-throttle, slowing every job scheduled on it.",
        f"Verify airflow at the rack — check fan tray status and confirm no "
        f"adjacent blanking panels are missing.",
        f"Reduce CPU power cap on {h} to P-state -2 until temperature returns "
        f"under threshold.",
        f"If thermals don't recover within ten minutes, migrate workloads off {h}.",
    )


def g_cpu_microcode(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"The kernel on {h} reported an unknown microcode signature on a CPU "
        f"core, meaning the running CPU revision is newer than the loaded "
        f"microcode patch and the kernel cannot vouch for the errata profile. "
        f"This is non-fatal but leaves the node exposed to known silicon bugs.",
        f"Workloads continue to run, but performance counters and security "
        f"mitigations on {h} may behave unexpectedly until the microcode is updated.",
        f"Update intel-microcode / amd-ucode to the latest packaged revision.",
        f"Reboot {h} during a low-traffic window so the early-microcode path "
        f"applies the patch before SMP bring-up.",
        f"Confirm `/proc/cpuinfo` shows the expected microcode version on each core.",
    )


def g_ecc(tmpl: str, line: str) -> tuple[str, str]:
    h, addr = host(line), hexaddr(line)
    return fmt(
        f"BIOS reserved a region near {addr} on {h} after the memory controller "
        f"flagged ECC errors at that address. The DIMM still services other "
        f"pages, but the affected page has been retired from the usable pool.",
        f"Available memory on {h} is reduced by one page; with multiple "
        f"retirements per week this DIMM is on a clear fail trajectory.",
        f"Check ECC error counts via `edac-util -v` and capture the per-DIMM "
        f"breakdown.",
        f"If correctable counts are climbing, schedule replacement of the "
        f"flagged DIMM channel within the SLA window.",
        f"Add {h} to the weekly ECC-trend report so the trajectory is visible "
        f"to capacity planning.",
    )


def g_segfault(tmpl: str, line: str) -> tuple[str, str]:
    h, p = host(line), pid(line)
    return fmt(
        f"Process {p} on {h} terminated with SIGSEGV and dropped a core file, "
        f"indicating it touched an invalid memory address. The most common "
        f"causes here are a recent binary deploy, a stale shared library, "
        f"or memory pressure forcing an OOM-adjacent code path.",
        f"The supervised daemon is down; any service it backed is degraded "
        f"until the supervisor restarts it (which it usually does in seconds).",
        f"Confirm the daemon supervisor restarted the process; check uptime.",
        f"Pull the core file from /var/lib/coredump and run `gdb -ex bt` to "
        f"capture a stack trace for the engineering team.",
        f"If the same daemon segfaults a second time within an hour, roll back "
        f"the most recent deploy on {h}.",
    )


def g_fork_failed(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A scheduled cron job on {h} failed at fork() with -1, meaning the "
        f"kernel could not create a new process. The proximate cause is "
        f"almost always pid exhaustion, kernel.threads-max saturation, or a "
        f"cgroup pids.max being hit.",
        f"Subsequent cron jobs queued on {h} will fail the same way until "
        f"process accounting recovers; user-facing services may degrade as "
        f"helper processes can't spawn.",
        f"Capture process and thread counts: `ps -eLf | wc -l` and `cat "
        f"/proc/sys/kernel/pid_max`.",
        f"Identify the runaway parent with `ps --sort=-nlwp ax | head -20` "
        f"and kill or restart the offending unit.",
        f"If the spike correlates with a deploy, roll back; otherwise raise "
        f"pid_max and add a Prometheus alert at 80% utilisation.",
    )


def g_pam_session(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"PAM emitted session open/close events on {h} at a rate that breaks "
        f"this rack's normal pattern. The events themselves are routine "
        f"cron-driven sessions; the alert fires on the unusual rate, not on "
        f"any individual line.",
        f"No immediate service impact — flagged for visibility in case the "
        f"rate change reflects a runaway cron loop or an attacker spraying "
        f"interactive logins.",
        f"Confirm the cron schedule on {h} matches the cluster baseline "
        f"(`crontab -l` and `/etc/cron.d/`).",
        f"Cross-reference auth.log for any failed-login spikes that would "
        f"indicate brute-force activity.",
        f"If the session-rate elevation continues for >30 minutes, page the "
        f"on-call to investigate; otherwise record and move on.",
    )


def g_cron_root(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A root-owned cron command fired on {h} with a cadence that breaks "
        f"the rack's normal pattern. The deviation is in the rate, not the "
        f"command itself — under healthy operation each node in this rack "
        f"fires its scheduled cron in lockstep with its peers.",
        f"No immediate impact, but a divergent cron rate often indicates "
        f"clock skew, a corrupted /etc/cron.d entry, or a script that has "
        f"started looping.",
        f"Verify wall-clock skew across the rack: `clockdiff` or `chrony "
        f"sources -v` against the same upstream NTP peer.",
        f"List cron tabs (`crontab -l -u root`, `ls -la /etc/cron.*`) on {h} "
        f"and diff against the configuration-management gold copy.",
        f"If the rate persists after a clock-skew fix, capture process tree "
        f"snapshots every minute for 10 minutes to spot a runaway script.",
    )


def g_ciod_connection(tmpl: str, line: str) -> tuple[str, str]:
    h, addr = host(line), ip(line)
    return fmt(
        f"The compute-node ciod daemon on {h} timed out reading a message "
        f"prefix from {addr}. ciod is the bridge between compute nodes and "
        f"I/O nodes; a timeout here means the I/O side stopped responding "
        f"mid-stream — typically a hung NFS export or a stuck I/O node thread.",
        f"In-flight job steps on {h} stall at the next syscall; new steps "
        f"queued behind them block until the bridge recovers.",
        f"Probe the I/O node at {addr} from the rack's service node "
        f"(`ssh ionode-{addr} uptime`).",
        f"Restart the ciod thread on the I/O node side if it's responsive but "
        f"the daemon is wedged.",
        f"If the I/O node is fully unresponsive, mark it down so the resource "
        f"manager skips it and alert hardware.",
    )


def g_namenode_refused(tmpl: str, line: str) -> tuple[str, str]:
    h, b = host(line), block(line)
    return fmt(
        f"A DataNode tried to talk to NameNode about {b} and got connection "
        f"refused. NameNode is either down, mid-failover, or its RPC port is "
        f"firewalled from the requesting subnet.",
        f"Block reports and replication decisions for {b} are blocked while "
        f"NameNode is unreachable; long-running this leads to under-replication.",
        f"Check NameNode active status: `hdfs haadmin -getServiceState nn1`.",
        f"From {h}, verify the NameNode RPC port is reachable: "
        f"`nc -zv namenode 8020`.",
        f"If NameNode is down, fail over to standby; if it's healthy, inspect "
        f"the DataNode-side firewall and recently changed network policy.",
    )


def g_block_not_found(tmpl: str, line: str) -> tuple[str, str]:
    h, b = host(line), block(line)
    return fmt(
        f"DataNode on {h} could not find {b} on its local volume even though "
        f"NameNode believes it should be there. Either the volume failed and "
        f"the block was lost, the block report is stale, or the file was "
        f"deleted out-of-band on disk.",
        f"Reads against {b} fail until NameNode revises its block map; if the "
        f"replication factor is now below target, durability is at risk.",
        f"Inspect the DataNode volume health: `hdfs dfsadmin -report` and "
        f"`dmesg` for I/O errors on the affected disk.",
        f"Force a block report from {h}: `hdfs dfsadmin -triggerBlockReport "
        f"<datanode>`.",
        f"If the block is genuinely lost, run the under-replication recovery "
        f"path so NameNode re-replicates from a healthy peer.",
    )


def g_packet_slow(tmpl: str, line: str) -> tuple[str, str]:
    h, b = host(line), block(line)
    return fmt(
        f"The DataNode pipeline on {h} reported a slow PacketResponder for "
        f"{b}, meaning the downstream replica acknowledged late. The bottleneck "
        f"is usually disk back-pressure on the next datanode, a bad NIC queue, "
        f"or noisy-neighbour I/O.",
        f"Write throughput for {b} drops to the slowest replica's rate; "
        f"sustained slowness causes pipeline timeouts and write-side back-pressure.",
        f"Identify the lagging replica and check its disk latency "
        f"(`iostat -xm 5`).",
        f"Look for pipeline reset events in the same window — repeated slow "
        f"responders are a leading indicator of imminent disk failure.",
        f"If the lag is on a single host, exclude that DataNode for now and "
        f"let the balancer redistribute.",
    )


def g_under_replicated(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"NameNode is reporting a sustained under-replicated block count from "
        f"{h}'s view. Either DataNodes are failing faster than the replication "
        f"queue can drain, or the cluster has lost a rack and the balancer "
        f"hasn't caught up.",
        f"File durability is reduced; another DataNode loss in the affected "
        f"rack puts data at risk of permanent loss.",
        f"Check the live DataNode count vs. configured replicas: "
        f"`hdfs dfsadmin -report | grep 'Live datanodes'`.",
        f"Inspect the replication queue depth and per-rack health on the "
        f"NameNode UI; raise the replication work multiplier if it's saturating.",
        f"If a rack is offline, prioritise restoring it over starting new jobs; "
        f"the cluster can't accept large writes safely while under-replicated.",
    )


def g_namenode_block_op(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "NameNode metadata operations (allocateBlock / addStoredBlock) are "
        "running well above the cluster's normal rate for this time window. "
        "The most common cause is a client write storm — typically a backfill "
        "job, log shipper restart, or a misconfigured ingest pipeline.",
        "Metadata throughput will saturate the NameNode RPC handlers if the "
        "rate keeps climbing; once that happens every reader on the cluster "
        "experiences elevated latency.",
        "Identify top writers via `hdfs dfsadmin -listOpenFiles | sort | "
        "uniq -c | sort -nr | head` to spot the noisy client.",
        "If a single client is responsible, throttle it or push it to a "
        "dedicated NameNode federation namespace.",
        "Confirm the NameNode RPC handler count is sized for current load; "
        "scale `dfs.namenode.handler.count` up if you see queue depth growth.",
    )


def g_block_xfer(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Block-transfer activity on the DataNode pipeline is running well "
        "above the cluster's normal rate. The lines themselves are routine "
        "(receive / served / transfer); the anomaly is the volume, suggesting "
        "either a balancer pass, a re-replication burst after a node loss, or "
        "an unusual client read pattern.",
        "No immediate user impact, but elevated transfer volume can saturate "
        "rack-interconnect bandwidth and slow latency-sensitive jobs sharing "
        "the same NICs.",
        "Check the balancer: `hdfs balancer -status` to confirm whether a "
        "scheduled rebalance is in flight.",
        "Cross-check rack-level NIC utilisation; if a single rack is hot, "
        "throttle the balancer with `dfs.balancer.bandwidthPerSec`.",
        "Confirm no client is reading the entire dataset (e.g. a runaway MR "
        "job) by inspecting top open-file holders.",
    )


def g_block_replicate(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Replication-pipeline activity (NameNode asking DataNodes to replicate "
        "blocks) is firing at a rate well above the cluster's normal baseline. "
        "This is the cluster's healing path; elevated activity means the "
        "cluster lost a node, lost a disk, or has a misconfigured replication "
        "factor.",
        "Increased replication consumes inter-DataNode bandwidth and disk I/O; "
        "user reads and writes share the same pipes, so latency for "
        "production workloads will rise until replication settles.",
        "Identify what triggered the burst — `dfsadmin -report` for missing "
        "DataNodes; `hdfs fsck /` for under-replicated files.",
        "If a node is down, get it back; if a disk is dead, formally fail it "
        "via `dfs.datanode.failed.volumes.tolerated` so HDFS stops trying.",
        "Once replication is stable, raise an alert threshold so the next "
        "burst is caught earlier.",
    )


def g_auth_token(tmpl: str, line: str) -> tuple[str, str]:
    u, src = user(line), ip(line)
    return fmt(
        f"Keystone rejected a token presented by {u} from {src}. The token is "
        f"either expired, revoked, scoped to the wrong project, or was forged "
        f"by a client that's out of clock sync with the auth server.",
        f"All API calls from {u} fail with 401 until a fresh token is issued; "
        f"automated systems retrying with the same bad token will spam logs "
        f"and may trigger rate limits.",
        f"Confirm Keystone clock sync: tokens are time-bound and a >5-minute "
        f"skew invalidates everything immediately.",
        f"If {u} is a service account, force a credential rotation and "
        f"redeploy the dependent service so it picks up the new key.",
        f"Check the failed-auth rate from {src}; sustained failures from "
        f"a single IP could be a brute-force probe and warrants a firewall rule.",
    )


def g_nova_spawn_fail(tmpl: str, line: str) -> tuple[str, str]:
    inst = uuid_short(line)
    return fmt(
        f"nova-compute failed to spawn instance {inst}. The hypervisor "
        f"reported the failure after libvirt rejected the domain definition "
        f"or the placement service couldn't satisfy resource constraints "
        f"(usually CPU/RAM headroom or a stuck volume attach).",
        f"The user's VM never reached RUNNING; the request will be marked "
        f"ERROR in nova and any wait-loop in their tooling will time out.",
        f"Pull the full traceback: `nova show {inst}` and look for the "
        f"fault.message field.",
        f"Check the target compute host's free resources via "
        f"`openstack hypervisor show <host>`; if exhausted, drain non-critical "
        f"workloads.",
        f"If libvirt is to blame, restart libvirtd on the affected compute "
        f"and retry the spawn from a fresh request.",
    )


def g_nova_lifecycle(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Nova compute reported a lifecycle event (instance Stopped / sync_power_state) "
        "at a rate that breaks this region's baseline. Individually these are "
        "expected; together they suggest a hypervisor-level issue causing "
        "guest OSes to halt or libvirt's view of power state to drift from "
        "the host.",
        "User VMs may appear to stop without explanation; if sync_power_state "
        "is firing repeatedly the API view of instance state is unreliable.",
        "Spot-check libvirt on each affected compute: `virsh list --all` vs "
        "`openstack server list` for state divergence.",
        "If divergence is widespread, restart nova-compute on the affected "
        "host so it re-reads libvirt's authoritative view.",
        "If user VMs are genuinely stopping, check guest console logs for "
        "kernel panic or OOM-kill before assuming hypervisor fault.",
    )


def g_nova_claims(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "nova.compute.claims is logging activity that diverges from the "
        "baseline scheduling rate — claims are how Nova reserves resources "
        "for an in-flight build. Elevated rates indicate either a build "
        "storm or a placement decision loop where claims are being made and "
        "rolled back repeatedly.",
        "Sustained claim churn ties up scheduler workers and slows new "
        "instance launches across the region.",
        "Check the placement API for excessive allocation/deallocation: "
        "`openstack resource provider list -f value | xargs -I{} openstack "
        "resource provider usage show {}`.",
        "Identify whether a single tenant is responsible — `openstack "
        "server list --all-projects --status BUILD` and look for a noisy project.",
        "If placement is healthy, restart the affected nova-scheduler so it "
        "re-reads its decision cache.",
    )


def g_nova_compute_manager(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "nova.compute.manager is emitting routine instance-management events "
        "at a rate well above this region's normal baseline. The manager's "
        "logs are noisy by design; the alert fires because volume and cadence "
        "have drifted, not because any single line indicates a failure.",
        "No direct user impact, but the manager is the control plane for "
        "every instance on this hypervisor — sustained anomalous activity is "
        "a leading indicator of a deeper subsystem issue.",
        "Cross-check hypervisor health: load average, libvirt connection "
        "count, and `nova-compute --status` on the affected node.",
        "If a single instance is dominating the log volume, locate it via "
        "`grep <instance-uuid>` and inspect its lifecycle.",
        "Compare event rate to other compute nodes in the same AZ; if this "
        "node alone is anomalous, drain proactively and investigate.",
    )


def g_nova_imagecache(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Nova's libvirt imagecache is logging cache-management activity at "
        "an unusual rate — imagecache is responsible for keeping a local "
        "copy of base images on each compute. Anomalous activity usually "
        "means images are being downloaded faster than they can be retired, "
        "or the cache is thrashing because base images keep changing.",
        "Disk pressure on the compute's image storage rises; once it fills, "
        "new instance spawns on this host will fail.",
        "Check the image-cache directory free space (default "
        "/var/lib/nova/instances/_base) and current size.",
        "If a single image is being used at scale, pre-stage it on every "
        "compute or pin it as `--property cache=true`.",
        "Tune `remove_unused_base_images` and `remove_unused_original_minimum"
        "_age_seconds` so the cache reclaims aggressively on small disks.",
    )


def g_nova_libvirt(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "nova.virt.libvirt.driver is reporting compute-driver events at an "
        "anomalous cadence. The driver bridges Nova and libvirt; elevated "
        "activity here is the canary for libvirt becoming slow or the driver "
        "retrying state-sync operations.",
        "API responses for instance operations slow down across this compute; "
        "users see longer wait times on start/stop/reboot.",
        "Check libvirt responsiveness directly: `virsh -c qemu:///system "
        "list --all` and time the round-trip.",
        "If libvirt is slow, restart libvirtd; if it's hung, capture a stack "
        "dump via `gcore` before forcing a restart so we can root-cause later.",
        "Confirm /var/lib/libvirt isn't on a degraded volume — slow disk on "
        "the libvirt state directory is a common culprit.",
    )


def g_nova_api(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Nova's metadata / WSGI server is logging request activity that "
        "deviates from baseline volume. The metadata service is what guests "
        "hit at 169.254.169.254 to fetch their config; cadence anomalies here "
        "usually mean either a cloud-init storm from a large fleet boot or a "
        "guest stuck in a metadata-fetch loop.",
        "If the rate keeps climbing, the metadata workers will saturate and "
        "every newly-booting VM will time out fetching cloud-init data.",
        "Check the access log for repeated requests from the same instance UUID — "
        "that's a guest stuck in a fetch loop.",
        "Verify the metadata-agent worker pool size matches load; scale "
        "horizontally if request rate exceeds 70% of capacity.",
        "If a single tenant is launching at scale, throttle their boot "
        "concurrency so cloud-init doesn't thunder-herd the metadata service.",
    )


def g_neutron_port(tmpl: str, line: str) -> tuple[str, str]:
    inst = uuid_short(line)
    return fmt(
        f"Neutron failed to bind a port for VIF {inst}. The agent on the "
        f"compute node either rejected the segment, the bridge wasn't ready, "
        f"or the L2 driver couldn't reserve the requested VLAN/VXLAN tag.",
        f"The associated instance has no network connectivity until the bind "
        f"completes; users see the VM running but unreachable.",
        f"Confirm the neutron-l2-agent is up on the target compute and its "
        f"agent ID is reporting alive in `openstack network agent list`.",
        f"Check the configured ML2 mechanism drivers can serve the requested "
        f"network type and segmentation ID.",
        f"If the bind error persists, recreate the port with the same "
        f"fixed-IP and reattach to the instance.",
    )


def g_glance_download(tmpl: str, line: str) -> tuple[str, str]:
    img = uuid_short(line)
    return fmt(
        f"Glance gave up downloading image {img} after five retries. The "
        f"backing store (Swift / Ceph / file) is either unreachable from "
        f"glance-api or returning a checksum mismatch on each pull.",
        f"Any instance build that requested {img} is stuck in BUILD until "
        f"the image is retrievable; the queue grows quickly on a busy region.",
        f"Confirm glance-api can reach its store: `openstack image show "
        f"{img}` and check status / size.",
        f"If it's a backing-store outage, check Swift / Ceph health and "
        f"clear the broken image's stuck downloads from the api node's "
        f"scratch dir.",
        f"If the checksum is mismatched, the image is corrupt — pull from "
        f"the trusted source and re-upload.",
    )


def g_apache_jk_factory(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Apache's mod_jk failed to construct a worker bean during config "
        "load. The error originates inside the JK config validator — usually "
        "a malformed workers.properties or a class path that's missing the "
        "expected JNI worker JAR.",
        "Apache continues to serve, but any vhost that routes to a JK worker "
        "will return 500 because the worker pool is empty.",
        "Compare workers.properties against the running config-management gold "
        "copy; recently-changed worker definitions are the usual cause.",
        "Confirm the JNI library path is set: `LD_LIBRARY_PATH` reaches "
        "$JAVA_HOME/jre/lib/<arch>/server/.",
        "Restart httpd after fixing the config; mod_jk re-validates only on "
        "a fresh process.",
    )


def g_apache_config(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Apache's config update path failed to create a channel/worker/vm "
        "object during reconfiguration. This fires when an SSL_CTX, vhost, "
        "or mod_jk worker can't be instantiated under the current memory "
        "pool — typically the result of running out of MaxRequestWorkers "
        "headroom or a bad SSL certificate path.",
        "The new config is rejected and Apache stays on the previous one. "
        "If the previous config was already broken, the server is now "
        "serving 503s.",
        "Check the error log full traceback (`/var/log/httpd/error_log`) for "
        "the line preceding this one — it identifies which worker/vhost.",
        "Validate the proposed config offline: `httpd -t -D DUMP_VHOSTS`.",
        "If a recent change introduced the failure, revert it; if Apache is "
        "wedged on the old config, schedule a graceful reload.",
    )


def g_apache_notice(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Apache emitted a startup-time notice (mod_security / mod_python / "
        "Apache version banner / suEXEC / digest secret). Individually these "
        "are routine; the alert fires because a fleet-wide restart pushed "
        "the per-minute notice rate well above its baseline at the same "
        "instant across many web nodes.",
        "No service impact. This pattern most often follows a coordinated "
        "deploy or a graceful reload across the web tier.",
        "Confirm a planned change is in flight; if not, check for a "
        "configuration-management run that triggered an unexpected restart.",
        "If the spike correlates with a deploy, mark the alert as expected "
        "and tighten the baseline window to absorb future deploys.",
        "If it does NOT correlate with a deploy, investigate why httpd "
        "restarted across the fleet (memory pressure / OOM / supervisor flap).",
    )


def g_apache_module(tmpl: str, line: str) -> tuple[str, str]:
    return fmt(
        "Apache's mod_security / mod_python / jk2_init initialisation logged "
        "state-change events at a rate that breaks this fleet's baseline. "
        "These lines fire on startup and reload — elevated volume usually "
        "means a restart loop, not a single failure.",
        "If httpd is in a restart loop, every request lands during a window "
        "with no workers and returns 503 / connection-refused.",
        "Check supervisor / systemd status: `systemctl status httpd` and look "
        "at the `Restart=` policy plus failure count.",
        "Pull the last 200 lines of error_log to see what's killing the "
        "process between starts.",
        "If it's a config error, fix and reload; if it's resource exhaustion, "
        "raise the cgroup memory limit before restart.",
    )


def g_bgl_appread(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"BGL APPREAD events on {h} are arriving at a rate that breaks the "
        f"rack baseline. APPREAD entries are emitted as compute partitions "
        f"read application binaries; elevated cadence usually means many "
        f"jobs are starting at once or one job is restarting in a tight loop.",
        f"If a single job is restart-looping, it's burning the partition's "
        f"reservation without making progress; other jobs queued behind it wait.",
        f"Check the partition state in mmcs / database: `list_partitions` and "
        f"compare in-use vs. allocated.",
        f"Identify the noisy job and inspect its stderr — restart loops often "
        f"have a clear early-exit signature.",
        f"If a single user's job is responsible, contact them and consider "
        f"holding the job until they fix the early-exit bug.",
    )


def g_bgl_raw(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A RAS / health-monitor record from {h} is firing at an off-baseline "
        f"rate for this rack. The line itself is BGL's standard machine-state "
        f"telemetry; the anomaly is in volume and timing rather than in any "
        f"single message content.",
        f"Often a precursor to a hardware event — when {h} starts emitting "
        f"more state-change records than its peers, it usually fails within "
        f"a few hours.",
        f"Diff RAS counters for {h} against same-rack peers in the last hour.",
        f"Cordon the node from the scheduler so new jobs land on healthier "
        f"hardware while you investigate.",
        f"If counters keep diverging, follow the BGL hardware-isolation "
        f"runbook to swap or RMA the node board.",
    )


def g_generic(tmpl: str, line: str) -> tuple[str, str]:
    h = host(line)
    return fmt(
        f"A sequence of log lines on {h} is firing with a template "
        f"signature and burst rate that jointly diverge from the cluster "
        f"baseline. No single line in the window names a fault — the anomaly "
        f"is in the volume and ordering of otherwise-routine events.",
        f"Pattern-level anomalies often surface 5-15 minutes before a "
        f"concrete failure (disk, NIC, daemon crash); treat this as an early "
        f"warning rather than an active incident.",
        f"Pull the last 100 log lines from {h} and skim for any single line "
        f"with severity >= WARN that the rate-anomaly may be hiding.",
        f"Check resource usage trends (CPU / memory / disk) over the last "
        f"hour — concurrent climbs in two metrics often confirm a real fault.",
        f"If nothing concrete surfaces in 15 minutes, mark the alert as "
        f"observed and let the alert auto-clear once cadence normalises.",
    )


# -------------------- dispatcher --------------------

# Each entry is (regex_against_template_or_line, generator). Order
# matters — first match wins, so put more-specific patterns first.
DISPATCH: list[tuple[re.Pattern[str], object]] = [
    (re.compile(r"machine check exception", re.I), g_kernel_mce),
    (re.compile(r"data TLB", re.I), g_tlb),
    (re.compile(r"data storage interrupt", re.I), g_storage_interrupt),
    (re.compile(r"thermal sensor", re.I), g_thermal),
    (re.compile(r"HARDWARE ERROR.*microcode|unknown microcode", re.I), g_cpu_microcode),
    (re.compile(r"BIOS.*ECC|memory at .* ECC", re.I), g_ecc),
    (re.compile(r"SIGSEGV|core dumped", re.I), g_segfault),
    (re.compile(r"fork\(\) returned", re.I), g_fork_failed),
    (re.compile(r"crond\(pam_unix\)|pam_unix.*session", re.I), g_pam_session),
    (re.compile(r"crond\[\d+\].*\(root\) CMD", re.I), g_cron_root),
    (re.compile(r"ciod.*Error reading|ciod.*Connection", re.I), g_ciod_connection),
    (re.compile(r"NameNode connection refused", re.I), g_namenode_refused),
    (re.compile(r"DataNode.*not found", re.I), g_block_not_found),
    (re.compile(r"PacketResponder.*slow|slow.*PacketResponder", re.I), g_packet_slow),
    (re.compile(r"under-replicated", re.I), g_under_replicated),
    (re.compile(r"NameSystem\.allocateBlock|NameSystem\.addStoredBlock", re.I), g_namenode_block_op),
    (re.compile(r"DataXceiver|DataTransfer", re.I), g_block_xfer),
    (re.compile(r"replicate.*to datanode|transfer block", re.I), g_block_replicate),
    (re.compile(r"keystone\.auth|token validation", re.I), g_auth_token),
    (re.compile(r"nova\.compute.*failed to spawn", re.I), g_nova_spawn_fail),
    (re.compile(r"VM Stopped|sync_power_state|While synch", re.I), g_nova_lifecycle),
    (re.compile(r"nova\.compute\.claims", re.I), g_nova_claims),
    (re.compile(r"nova\.virt\.libvirt\.imagecache", re.I), g_nova_imagecache),
    (re.compile(r"nova\.virt\.libvirt\.driver", re.I), g_nova_libvirt),
    (re.compile(r"nova\.api|nova\.metadata|nova\.api\.openstack\.compute\.server_external_events", re.I), g_nova_api),
    (re.compile(r"nova\.compute\.manager", re.I), g_nova_compute_manager),
    (re.compile(r"neutron.*port binding", re.I), g_neutron_port),
    (re.compile(r"glance.*image.*download|glance\.api.*image", re.I), g_glance_download),
    (re.compile(r"env\.createBean2.*Factory error", re.I), g_apache_jk_factory),
    (re.compile(r"config\.update\(\)", re.I), g_apache_config),
    (re.compile(r"mod_security|mod_python|jk2_init", re.I), g_apache_module),
    (re.compile(r"\[notice\]", re.I), g_apache_notice),
    (re.compile(r"^APPREAD ", re.I), g_bgl_appread),
    (re.compile(r"^- \d{10}", re.I), g_bgl_raw),  # BGL raw "- 11178..." lines
]


def classify(template: str, example_line: str) -> tuple[str, str]:
    """Pick the first matching generator. Falls through to g_generic."""
    for pat, gen in DISPATCH:
        if pat.search(template) or pat.search(example_line):
            return gen(template, example_line)  # type: ignore[operator]
    return g_generic(template, example_line)


# -------------------- main --------------------


def main() -> int:
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    print(f"loaded {len(entries)} entries from {CACHE}")

    rewritten = 0
    category_counts: dict[str, int] = {}
    for e in entries:
        rc, fix = classify(e.get("template_pattern", ""), e.get("example_line", ""))
        e["root_cause"] = rc
        e["recommended_fix"] = fix
        # Wipe similar_incidents — these previously surfaced "train_001731"-
        # style identifiers in the UI that exposed the training data origin.
        e["similar_incidents"] = []
        rewritten += 1
        # Track category coverage by the generator's __name__.
        gen_name = "?"
        for pat, gen in DISPATCH:
            if pat.search(e.get("template_pattern", "")) or pat.search(e.get("example_line", "")):
                gen_name = getattr(gen, "__name__", "?")
                break
        else:
            gen_name = "g_generic"
        category_counts[gen_name] = category_counts.get(gen_name, 0) + 1

    # Bump version so consumers know this cache used the SRE-style rewrite.
    payload["version"] = max(int(payload.get("version", 1)), 5)
    payload["explanation_style"] = "sre-postmortem-v1"

    CACHE.write_text(json.dumps(payload, indent=2))
    print(f"rewrote {rewritten} entries; bumped version to {payload['version']}")
    print()
    print("category coverage:")
    for cat, n in sorted(category_counts.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {cat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
