#!/usr/bin/env python3
"""After a nightly-window test: are the NEW points (created_at >= t0) in Qdrant, searchable, and being indexed?
usage (host, inside Qdrant's netns): nsenter -t <pid> -n python3 new_points_check.py <t0 in epoch ms>"""
import json, sys, time, urllib.request
BASE = "http://127.0.0.1:6333"; COL = "nomad_knowledge_base"; EMB = "http://192.168.1.69:9292/v1/embeddings"
t0 = int(sys.argv[1])
def post(url, body, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
def get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r: return json.load(r)
info = get(f"/collections/{COL}")["result"]
print("collection now:", {k: info.get(k) for k in ("status", "points_count", "indexed_vectors_count", "segments_count")})
flt = {"must": [{"key": "created_at", "range": {"gte": t0}}]}
n_new = post(f"{BASE}/collections/{COL}/points/count?timeout=290", {"filter": flt, "exact": True})["result"]["count"]  # created_at is not indexed: full payload scan, > Qdrant's default 60 s
print("points created since the test started:", n_new)
if n_new == 0: print("NO NEW POINTS"); sys.exit(2)
pts = post(f"{BASE}/collections/{COL}/points/scroll?timeout=290", {"filter": flt, "limit": 400, "with_payload": {"include": ["text", "article_title", "source", "created_at", "active"]}, "with_vector": False})["result"]["points"]
step = max(1, len(pts) // 6); chosen = pts[::step][:6]
ok = 0
for p in chosen:
    pl = p["payload"]; text = (pl.get("text") or "")[:240]
    if len(text) < 40: continue
    q = post(EMB, {"model": "nomic-embed-text:v1.5", "input": ["search_query: " + text], "encoding_format": "float"})["data"][0]["embedding"]
    t = time.time()
    hits = post(f"{BASE}/collections/{COL}/points/search", {"vector": q, "limit": 15, "score_threshold": 0.3, "with_payload": {"include": ["article_title"]}, "filter": {"must_not": [{"key": "active", "match": {"value": False}}]}})["result"]
    dt = time.time() - t; rank = next((i + 1 for i, h in enumerate(hits) if h["id"] == p["id"]), None); ok += rank is not None
    print("new point %s | %-40s | rank in top-15: %s | top score %.3f | %.0f ms" % (p["id"][:8], (pl.get("article_title") or "")[:40], rank, hits[0]["score"] if hits else 0, dt * 1000))
print("found %d of %d sampled NEW points in the top 15 of a NOMAD-style search on their own text" % (ok, len([c for c in chosen if len((c["payload"].get("text") or "")) >= 40])))
sys.exit(0 if ok else 3)
