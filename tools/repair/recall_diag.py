#!/usr/bin/env python3
"""Is the recall gap real or just ties between identical/near-identical chunks? Run inside Qdrant's netns (nsenter -t <pid> -n).
A) the 10 NOMAD-style natural-language queries (what users do): identity recall@15 + score gap, default params and rescore=true
B) 60 random points as queries: identity recall, TIE-AWARE recall (an approximate hit counts if its float score >= the exact 15th score - 1e-4),
   and how many of the exact top-15 have a (near) identical vector to the query (score >= 0.9999)."""
import json, random, statistics as st, sys, time, urllib.request, uuid
BASE = "http://127.0.0.1:6333"; COL = "nomad_knowledge_base"
R = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/results"
FILT = {"must_not": [{"key": "active", "match": {"value": False}}]}
def post(path, body, timeout=300):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)["result"]
def search(vec, params=None, thr=None, limit=15, flt=FILT):
    b = {"vector": vec, "limit": limit, "filter": flt, "with_payload": False}
    if thr is not None: b["score_threshold"] = thr
    if params: b["params"] = params
    return post(f"/collections/{COL}/points/search", b)
EXACT = {"exact": True, "quantization": {"ignore": True}}
def float_scores(vec, ids):  # exact float scores for a given id list
    flt = {"must": [{"has_id": list(ids)}]}
    return {h["id"]: h["score"] for h in search(vec, EXACT, None, len(ids), flt)}
def evaluate(vec, thr):
    ex = search(vec, EXACT, thr); exids = [h["id"] for h in ex]
    out = {"n_exact": len(ex)}
    if not ex: return out
    s15 = ex[-1]["score"]
    for name, params in (("default", None), ("rescore", {"quantization": {"rescore": True}})):
        ap = search(vec, params, thr); apids = [h["id"] for h in ap]
        fs = float_scores(vec, apids) if apids else {}
        out[name] = {"identity": len(set(apids) & set(exids)) / len(exids), "tie_aware": sum(1 for i in apids if fs.get(i, -1) >= s15 - 1e-4) / len(exids),
                     "score_gap": (st.mean(h["score"] for h in ex) - st.mean(fs.get(i, 0) for i in apids)) if apids else None, "n_approx": len(ap)}
    out["near_identical_in_exact"] = sum(1 for h in ex if h["score"] >= 0.9999)
    out["exact_scores"] = [round(h["score"], 4) for h in ex[:5]] + ["..."] + [round(ex[-1]["score"], 4)]
    return out
def summary(rows, key):
    v = [r[key] for r in rows if key in r]
    return {"identity_mean": round(st.mean(x["identity"] for x in v), 4), "identity_min": round(min(x["identity"] for x in v), 3), "tie_aware_mean": round(st.mean(x["tie_aware"] for x in v), 4), "tie_aware_min": round(min(x["tie_aware"] for x in v), 3), "mean_score_gap": round(st.mean(x["score_gap"] for x in v if x["score_gap"] is not None), 5)}
res = {}
qs = json.load(open(f"{R}/verify_queries.json")); rowsA = []
for q in qs:
    r = evaluate(q["vec"], 0.3); r["name"] = q["name"]; rowsA.append(r)
    print("A %-18s identity default %.2f rescore %.2f | tie-aware default %.2f | score gap %.5f | near-identical in exact top: %d" % (q["name"], r["default"]["identity"], r["rescore"]["identity"], r["default"]["tie_aware"], r["default"]["score_gap"] or 0, r["near_identical_in_exact"]), flush=True)
res["A_natural_queries"] = {"default": summary(rowsA, "default"), "rescore": summary(rowsA, "rescore")}; print("A summary:", json.dumps(res["A_natural_queries"]), flush=True)
random.seed(21); rowsB = []
pts = []
for _ in range(6):
    pts += post(f"/collections/{COL}/points/scroll", {"limit": 10, "offset": str(uuid.UUID(int=random.getrandbits(128))), "with_vector": True, "with_payload": False})["points"]
for p in pts[:60]:
    r = evaluate(p["vector"], None); rowsB.append(r)
res["B_point_queries"] = {"n": len(rowsB), "default": summary(rowsB, "default"), "rescore": summary(rowsB, "rescore"), "queries_with_ties_or_near_duplicates_in_exact_top15": sum(1 for r in rowsB if r.get("near_identical_in_exact", 0) >= 2)}
worst = sorted(rowsB, key=lambda r: r["default"]["identity"])[:4]
for r in worst: print("B worst: identity %.2f tie-aware %.2f | near-identical in exact top-15: %d | exact scores %s" % (r["default"]["identity"], r["default"]["tie_aware"], r["near_identical_in_exact"], r["exact_scores"]), flush=True)
print("B summary:", json.dumps(res["B_point_queries"]), flush=True)
json.dump(res, open(f"{R}/recall_diag_{time.strftime('%H%M%S')}.json", "w"), indent=1)
