#!/usr/bin/env python3
"""Before/after check for changes to NOMAD's Qdrant collection (the same 8 NOMAD-style searches NOMAD makes).

  python3 search_compare.py snap <tag>        save top-15 hits + latency to $WORK/search_<tag>.json
  python3 search_compare.py diff <tagA> <tagB>  compare the two runs

Run on the Unraid host. The query embeddings (nomic via llama-swap) are computed once and cached in
$WORK/query_vectors.json, so both runs use identical vectors. The search shape is NOMAD's own:
limit 15, score threshold 0.3, active != false.
"""
import json, os, statistics as st, subprocess, sys, time, urllib.request

WORK = os.environ.get("WORK", "scrap-work")
EMBED = os.environ.get("EMBED_URL", "http://192.168.1.69:9292/v1/embeddings")
COL = "nomad_knowledge_base"
QUERIES = ["how long should I boil water to make it safe to drink", "how do I wire a three-way light switch",
           "why does my linear voltage regulator get so hot", "how to replace the battery in an iPhone 8",
           "what are the symptoms of high blood pressure", "python list comprehension tutorial",
           "who was Napoleon Bonaparte", "how do I season a cast iron skillet"]
os.makedirs(WORK, exist_ok=True)


def qdrant(path, body=None):
    qp = subprocess.check_output("pgrep -x qdrant | head -1", shell=True).decode().strip()
    cmd = ["nsenter", "-t", qp, "-n", "curl", "-s", "-m", "120", "-H", "content-type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    return json.loads(subprocess.check_output(cmd + ["http://127.0.0.1:6333" + path]))


def vectors():
    f = f"{WORK}/query_vectors.json"
    if os.path.exists(f):
        return json.load(open(f))
    out = {}
    for s in QUERIES:
        req = urllib.request.Request(EMBED, data=json.dumps({"model": "nomic-embed-text:v1.5", "input": ["search_query: " + s],
                                                             "encoding_format": "float"}).encode(), headers={"content-type": "application/json"})
        out[s] = json.load(urllib.request.urlopen(req, timeout=120))["data"][0]["embedding"]
    json.dump(out, open(f, "w"))
    return out


def key(p):
    pl = p["payload"]
    return f"{os.path.basename(pl.get('source', ''))}|{pl.get('article_path')}|{pl.get('section_title')}|{pl.get('chunk_index')}"


def snap(tag):
    info = qdrant(f"/collections/{COL}")["result"]
    res = {"tag": tag, "time": time.strftime("%F %T"), "status": info["status"], "points": info["points_count"],
           "indexed": info["indexed_vectors_count"], "segments": info["segments_count"], "queries": {}}
    for s, v in vectors().items():
        body = {"vector": v, "limit": 15, "score_threshold": 0.3, "with_payload": {"include": ["source", "article_path", "article_title", "section_title", "chunk_index"]},
                "filter": {"must_not": [{"key": "active", "match": {"value": False}}]}}
        ms, sv, hits = [], [], None
        for _ in range(6):
            t = time.time()
            r = qdrant(f"/collections/{COL}/points/search", body)
            hits = r["result"]
            ms.append((time.time() - t) * 1000); sv.append(r["time"] * 1000)
        res["queries"][s] = {"first_ms": round(ms[0], 1), "warm_median_ms": round(st.median(ms[1:]), 1), "server_median_ms": round(st.median(sv[1:]), 2),
                             "hits": [{"key": key(h), "title": h["payload"].get("article_title"), "score": round(h["score"], 4)} for h in hits]}
    json.dump(res, open(f"{WORK}/search_{tag}.json", "w"), indent=1)
    warm = [q["warm_median_ms"] for q in res["queries"].values()]
    srv = [q["server_median_ms"] for q in res["queries"].values()]
    print(f"{tag}: {res['status']} points={res['points']} indexed={res['indexed']} segments={res['segments']} "
          f"server-side median {st.median(srv):.1f} ms, max {max(srv):.1f} ms; client (nsenter+curl) median {st.median(warm):.1f} ms")


def diff(a, b):
    A, B = (json.load(open(f"{WORK}/search_{t}.json")) for t in (a, b))
    print(f"points {A['points']} -> {B['points']}; status {A['status']} -> {B['status']}; indexed {A['indexed']} -> {B['indexed']}")
    for s in A["queries"]:
        ka = [h["key"] for h in A["queries"][s]["hits"]]; kb = [h["key"] for h in B["queries"][s]["hits"]]
        print(f"- {s[:48]:48} same top1: {ka[:1] == kb[:1]}  top5 overlap {len(set(ka[:5]) & set(kb[:5]))}/5  top15 overlap {len(set(ka) & set(kb))}/15  "
              f"hits {len(ka)}->{len(kb)}  server ms {A['queries'][s].get('server_median_ms')}->{B['queries'][s].get('server_median_ms')}  (client ms {A['queries'][s]['warm_median_ms']}->{B['queries'][s]['warm_median_ms']})")
        if ka[:1] != kb[:1]:
            print(f"    before top1: {A['queries'][s]['hits'][0]['title']!r}\n    after  top1: {B['queries'][s]['hits'][0]['title']!r}")


if __name__ == "__main__":
    snap(sys.argv[2]) if sys.argv[1] == "snap" else diff(sys.argv[2], sys.argv[3])
