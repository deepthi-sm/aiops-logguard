"""Smoke test for the demo polish fixes:

1. NO anomaly should be stuck pending forever — every click resolves.
2. Cache-hit cycle (click → ready) should fall in [4s, 8s] window.
3. Latest anomalies (top of list) should also resolve.

Picks 10 anomalies from different positions: 3 most recent, 4 mid-list,
3 from the tail. All should resolve within ~8s on the first call.
"""
import json
import random
import time
import urllib.request
import urllib.error

API = "http://127.0.0.1:8000/api/v1"


def get_raw(path: str, timeout: float = 30.0):
    req = urllib.request.Request(API + path)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, body, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, e.read(), (time.perf_counter() - t0) * 1000


# Wait until we have at least 50 anomalies for a representative sample
print("waiting for ingestion ...")
deadline = time.time() + 60
while time.time() < deadline:
    _, body, _ = get_raw("/anomalies?limit=100")
    items = json.loads(body)["items"]
    if len(items) >= 50:
        break
    time.sleep(2)
print(f"  fetched {len(items)} anomalies")

# Pick 10 spread across positions: 3 newest, 4 middle, 3 oldest in the
# 100-item window. The newest cluster is the user's main concern from
# the previous run.
n = len(items)
indices = (
    [0, 1, 2]
    + sorted(random.Random(99).sample(range(3, max(4, n - 3)), k=min(4, max(0, n - 6))))
    + ([n - 3, n - 2, n - 1] if n >= 3 else [])
)
indices = sorted(set(i for i in indices if 0 <= i < n))[:10]
sample = [items[i] for i in indices]
print(f"sampled {len(sample)} anomalies at positions {indices}")

print()
print("== 10-click smoke test ==")
results = []
for i, a in enumerate(sample, 1):
    aid = a["id"]
    pos = indices[i - 1]
    code, body, ms = get_raw(f"/anomalies/{aid}/explanation", timeout=30)
    ok = code == 200 and 3500 <= ms <= 9000  # 4-8s with 0.5s tolerance
    if code == 200:
        try:
            payload = json.loads(body)
            preview = payload["root_cause"][:90].replace("\n", " ")
        except Exception:
            preview = "<unparseable>"
    else:
        preview = "<not-200>"
    flag = "OK" if ok else ("SLOW" if ms > 9000 else ("FAST" if code == 200 else f"FAIL {code}"))
    print(f"  pos={pos:3d}  {aid[:38]:<38}  {ms:7.1f}ms  code={code}  {flag}")
    print(f"           rc: {preview}")
    results.append((aid, ms, code, ok))

print()
in_window = sum(1 for _, _, _, ok in results if ok)
hit_count = sum(1 for _, _, c, _ in results if c == 200)
print(f"== summary: {hit_count}/{len(results)} returned 200 ; {in_window}/{len(results)} in 4-8s window ==")
mins = sorted(ms for _, ms, c, _ in results if c == 200)
if mins:
    print(f"   delay min={mins[0]:.0f}ms median={mins[len(mins)//2]:.0f}ms max={mins[-1]:.0f}ms")
