#!/usr/bin/env python3
"""NOMAD-shaped searches + latency + recall vs exact. Run inside Qdrant's netns: nsenter -t <pid> -n python3 verify_search.py [reps]"""
import json, os, sys, time, random, statistics as st, uuid, urllib.request
BASE = os.environ.get("QDRANT_BASE", "http://127.0.0.1:6333"); TAG = os.environ.get("TAG", "run"); COL = "nomad_knowledge_base"; R = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/results"
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
def post(path, body, timeout=300):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
FILT = {"must_not": [{"key": "active", "match": {"value": False}}]}
def search(vec, exact=False, thr=0.3, limit=15, rescore=None):
    b = {"vector": vec, "limit": limit, "with_payload": {"include": ["article_title", "section_title", "source"]}, "filter": FILT}
    if thr is not None: b["score_threshold"] = thr
    if exact: b["params"] = {"exact": True, "quantization": {"ignore": True}}  # float ground truth
    elif rescore is not None: b["params"] = {"quantization": {"rescore": rescore}}
    t = time.time(); r = post(f"/collections/{COL}/points/search", b)["result"]; return r, time.time() - t
res = {"queries": [], "recall": {}}
for q in json.load(open(f"{R}/verify_queries.json")):
    try:
        hits, cold = search(q["vec"]); lat = [search(q["vec"])[1] for _ in range(REPS)]
        top = [(round(h["score"], 3), (h["payload"].get("article_title") or "")[:50], (h["payload"].get("source") or "").rsplit("/", 1)[-1][:28]) for h in hits[:3]]
        res["queries"].append({"name": q["name"], "text": q["text"], "hits": len(hits), "first_s": round(cold, 3), "median_s": round(st.median(lat), 4), "p90_s": round(sorted(lat)[max(0, int(0.9 * len(lat)) - 1)], 4), "top3": top})
        print(q["name"], "| hits", len(hits), "| first %.3fs median %.4fs" % (cold, st.median(lat)), "|", top[0] if top else None, flush=True)
    except Exception as e:
        res["queries"].append({"name": q["name"], "error": str(e)[:200]}); print(q["name"], "ERROR", str(e)[:150], flush=True)
allmed = [x["median_s"] for x in res["queries"] if "median_s" in x]
if allmed: res["median_of_medians_s"] = round(st.median(allmed), 4); res["p90_of_medians_s"] = round(sorted(allmed)[max(0, int(0.9 * len(allmed)) - 1)], 4)
try:
    if os.environ.get("SKIP_RECALL"): raise RuntimeError("skipped (SKIP_RECALL set)")
    pts = post(f"/collections/{COL}/points/scroll", {"limit": 30, "offset": str(uuid.uuid4()), "with_vector": True, "with_payload": False})["result"]["points"]
    rec = []; rec_rs = []; t_ex = []
    for p in pts:
        a, _ = search(p["vector"], thr=None); b, te = search(p["vector"], exact=True, thr=None); t_ex.append(te)
        A = {h["id"] for h in a}; B = {h["id"] for h in b}; rec.append(len(A & B) / max(1, len(B)))
        c, _ = search(p["vector"], thr=None, rescore=True); C = {h["id"] for h in c}; rec_rs.append(len(C & B) / max(1, len(B)))
    res["recall"] = {"n": len(rec), "default_params_recall_at_15_mean": round(st.mean(rec), 4), "default_min": round(min(rec), 3), "rescore_true_recall_at_15_mean": round(st.mean(rec_rs), 4), "float_exact_search_median_s": round(st.median(t_ex), 2)}
    print("recall@15 vs exact:", res["recall"], flush=True)
except Exception as e:
    res["recall"] = {"error": str(e)[:200]}; print("recall ERROR", str(e)[:200])
json.dump(res, open(f"{R}/verify_search_{TAG}_{time.strftime('%H%M%S')}.json", "w"), indent=1)
