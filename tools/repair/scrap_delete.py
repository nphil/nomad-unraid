#!/usr/bin/env python3
"""Delete the points listed in $IDS (default $WORK/scrap_ids.txt, from scrap_plan.py or dup_library_plan.py) from NOMAD's Qdrant collection.

  flock /tmp/agents-heavy.lock nice -n 15 ionice -c3 python3 scrap_delete.py [batch=2000] [pause_seconds=1]

Deleting by id is idempotent, so an interrupted run can simply be started again. Take a ZFS snapshot of the
Qdrant dataset first (the undo path) and destroy it once verification has passed.
"""
import json, os, subprocess, sys, time

WORK = os.environ.get("WORK", "scrap-work")
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
PAUSE = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
COL = "nomad_knowledge_base"
QP = subprocess.check_output("pgrep -x qdrant | head -1", shell=True).decode().strip()


def q(path, body=None):
    cmd = ["nsenter", "-t", QP, "-n", "curl", "-s", "-m", "900", "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    return json.loads(subprocess.check_output(cmd + ["http://127.0.0.1:6333" + path]))


ids = [l.strip() for l in open(os.environ.get("IDS", f"{WORK}/scrap_ids.txt")) if l.strip()]
before = q(f"/collections/{COL}")["result"]["points_count"]
print(f"{len(ids)} ids planned; collection has {before} points", flush=True)
t0 = time.time()
for n in range(0, len(ids), BATCH):
    r = q(f"/collections/{COL}/points/delete?wait=true", {"points": ids[n:n + BATCH]})
    if r.get("status") != "ok" and r.get("result", {}).get("status") not in ("completed", "acknowledged"):
        sys.exit(f"batch at {n} failed: {r}")
    if (n // BATCH) % 25 == 0:
        print(f"{n + len(ids[n:n + BATCH])}/{len(ids)} deleted ({time.time() - t0:.0f}s)", flush=True)
    time.sleep(PAUSE)
after = q(f"/collections/{COL}")["result"]["points_count"]
print(f"done in {time.time() - t0:.0f}s: {before} -> {after} points ({before - after} removed)")
