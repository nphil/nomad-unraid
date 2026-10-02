#!/usr/bin/env python3
"""Checks a Qdrant that loaded the RECOVERED store (run on the Unraid host).
env: QDRANT_BASE (default http://127.0.0.1:16333), STORE (dir of the recovered store for raw vector reads).
Checks: collection state, exact count, source facet, 120 reference points (payload+vector) vs the independent consistent v1 data,
        40 random points anywhere in the recovered segment vs the raw vectors in the chunk files, and a text sanity sample."""
import array, json, math, os, random, struct, sys, urllib.request
BASE = os.environ.get("QDRANT_BASE", "http://127.0.0.1:16333"); COL = "nomad_knowledge_base"
STORE = os.environ.get("STORE", "/mnt/nvme/appdata/nomad-qdrant-recovered")
R = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/results"
SEG = f"{STORE}/collections/{COL}/0/segments/c98bf53f-759c-4d00-9749-5b1c1fcf4033"
def api(path, body=None, timeout=600):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
ok = True
def check(name, cond, detail=""):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name, detail, flush=True)

info = api(f"/collections/{COL}")["result"]
print("collection:", {k: info.get(k) for k in ("status", "points_count", "indexed_vectors_count", "segments_count")}, "optimizer:", str(info.get("optimizer_status"))[:100])
print("payload_schema:", {k: v.get("data_type") + "/" + str(v.get("points")) for k, v in info.get("payload_schema", {}).items()})
cnt = api(f"/collections/{COL}/points/count", {"exact": True})["result"]["count"]
print("exact count:", cnt, "| old instance reported 4,130,695 (= 138,707 + 3,989,177 + 2,811)")
check("count is close to the old instance's 4,130,695 (within 1%)", abs(cnt - 4130695) <= 0.01 * 4130695, f"(got {cnt}, diff {cnt - 4130695:+d})")
try:
    fac = api(f"/collections/{COL}/facet", {"key": "source", "limit": 30, "exact": False})["result"]["hits"]
    print("top sources:"); [print("   %9d  %s" % (h["count"], str(h["value"]).rsplit("/", 1)[-1][:60])) for h in fac[:12]]
except Exception as e:
    print("facet failed:", str(e)[:150])

# reference points vs independent consistent data (v1 production instance, stale-but-consistent first 79,424 points)
ref = json.load(open(f"{R}/v1_sample.json"))["result"]
got = {p["id"]: p for p in api(f"/collections/{COL}/points", {"ids": [p["id"] for p in ref], "with_payload": True, "with_vector": True})["result"]}
pe = ve = miss = 0; worst = 0.0
for p in ref:
    g = got.get(p["id"])
    if g is None: miss += 1; continue
    pe += g["payload"] == p["payload"]
    d = max(abs(a - b) for a, b in zip(g["vector"], p["vector"])); worst = max(worst, d); ve += d < 1e-6
check("120 reference points present", miss == 0, f"(missing {miss})")
check("reference payloads identical", pe == len(ref) - miss, f"({pe}/{len(ref)})")
check("reference vectors identical", ve == len(ref) - miss, f"({ve}/{len(ref)}, worst abs diff {worst:.2e})")

# alignment anywhere in the recovered segment: random uuids from the rebuilt id table vs raw chunk-file vectors
mp = open(f"{SEG}/mutable_id_tracker.mappings", "rb").read(); n = len(mp) // 21
random.seed(11); ks = sorted(random.sample(range(n), 40)) + [0, n - 1]
import uuid as _u
ids = [str(_u.UUID(bytes=mp[k*21+1:k*21+17])) for k in ks]
res = {p["id"]: p for p in api(f"/collections/{COL}/points", {"ids": ids, "with_payload": True, "with_vector": True})["result"]}
al = 0
for k, i in zip(ks, ids):
    c, s = divmod(k, 10922)
    with open(f"{SEG}/vector_storage/vectors/chunk_{c}.mmap", "rb") as f: f.seek(s * 3072); raw = array.array("f"); raw.frombytes(f.read(3072))
    v = res.get(i, {}).get("vector")
    al += bool(v) and max(abs(a - b) for a, b in zip(v, raw)) < 1e-6
check("42 random points: API vector == raw chunk-file vector", al == len(ks), f"({al}/{len(ks)})")
bad = [p for p in res.values() if not p.get("payload", {}).get("text")]
check("those points have payload text", not bad and len(res) == len(ks), f"(without text: {len(bad)}, found {len(res)}/{len(ks)})")
print("sample texts:")
for p in list(res.values())[:5]:
    pl = p["payload"]; print("   -", (pl.get("article_title") or "")[:48], "|", (pl.get("section_title") or "")[:30], "|", (pl.get("text") or "")[:90].replace("\n", " "))
print("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
