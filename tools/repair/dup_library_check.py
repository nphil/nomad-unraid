#!/usr/bin/env python3
"""Is library B (to remove) covered by library A? Reads only. Run on the Unraid host.

  python3 dup_library_check.py <A source substring> <B source substring> [sample=300]

Writes $WORK/<B>_ids.txt (every point id of B, for scrap_delete.py via IDS=...) and prints:
point counts per source, and for a random sample of B chunks how many have an identical or
near-identical chunk in A (same text, or cosine >= 0.995 on the stored vectors, searched among A only).
"""
import collections, difflib, json, os, random, re, subprocess, sys

A, B = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 300
WORK = os.environ.get("WORK", "scrap-work"); os.makedirs(WORK, exist_ok=True)
COL = "nomad_knowledge_base"
QP = subprocess.check_output("pgrep -x qdrant | head -1", shell=True).decode().strip()


def q(path, body=None):
    cmd = ["nsenter", "-t", QP, "-n", "curl", "-s", "-m", "300", "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    return json.loads(subprocess.check_output(cmd + ["http://127.0.0.1:6333" + path]))


facet = q(f"/collections/{COL}/facet", {"key": "source", "limit": 100})["result"]["hits"]
src = {h["value"]: h["count"] for h in facet}
sa = [s for s in src if A in s]; sb = [s for s in src if B in s]
assert len(sa) == 1 and len(sb) == 1, (sa, sb)
sa, sb = sa[0], sb[0]
print(f"A {sa}: {src[sa]} points\nB {sb}: {src[sb]} points")


def scroll(source, with_vector=False, payload=("article_path", "chunk_index", "text"), ids=None):
    out, off = [], None
    flt = {"must": [{"key": "source", "match": {"value": source}}]}
    while True:
        body = {"limit": 5000, "with_payload": list(payload) if payload else False, "with_vector": with_vector, "filter": flt}
        if off is not None:
            body["offset"] = off
        r = q(f"/collections/{COL}/points/scroll", body)["result"]
        out += r["points"]; off = r.get("next_page_offset")
        if off is None:
            return out


bpoints = scroll(sb, payload=("char_count",))
ids = [p["id"] for p in bpoints]
open(f"{WORK}/{B}_ids.txt", "w").write("".join(f"{i}\n" for i in ids))
print(f"{len(ids)} ids of B written")
random.seed(5)
sample = random.sample(ids, N)
pts = q(f"/collections/{COL}/points", {"ids": sample, "with_payload": True, "with_vector": True})["result"]
norm = lambda t: re.sub(r"\s+", " ", (t or "").strip().lower())
res = collections.Counter(); worst = []
for p in pts:
    hits = q(f"/collections/{COL}/points/search", {"vector": p["vector"], "limit": 5, "with_payload": ["text", "article_path"],
                                                   "filter": {"must": [{"key": "source", "match": {"value": sa}}]}})["result"]
    t = norm(p["payload"].get("text"))
    best = max(hits, key=lambda h: difflib.SequenceMatcher(None, t, norm(h["payload"].get("text"))).quick_ratio()) if hits else None
    sim = difflib.SequenceMatcher(None, t, norm(best["payload"].get("text"))).ratio() if best else 0
    score = hits[0]["score"] if hits else 0
    k = "identical text" if best and sim == 1 else "near-identical (text >= 0.95 similar or cosine >= 0.995)" if (sim >= 0.95 or score >= 0.995) else "NOT covered"
    res[k] += 1
    if k == "NOT covered":
        worst.append({"article": p["payload"].get("article_path"), "chunk": p["payload"].get("chunk_index"), "cos": round(score, 4), "sim": round(sim, 3), "text": (p["payload"].get("text") or "")[:80]})
print(f"sample {len(pts)}:", dict(res), f"covered {100 * (len(pts) - res['NOT covered']) / len(pts):.1f}%")
for w in worst[:12]:
    print("  uncovered:", w)
