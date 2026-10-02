"""NOMAD-like retrieval test: LLM-written questions -> Wikipedia chunks produced by NOMAD's own chunker (dataset/chunks_wikipedia.jsonl).
usage: python3 exp5_nomadwiki.py MODEL VARIANT[,VARIANT] [server_args]   (lock-guarded, resumable via emb/ cache)"""
import json, sys, os, time, numpy as np
from bench_lib import *
import srv_locked as srv
from models_cfg import MODELS
import beir_eval
k = sys.argv[1]; variants = sys.argv[2].split(",")
args = sys.argv[3] if len(sys.argv) > 3 else "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"
m = MODELS[k]
PFX = {"native": (m["doc"], m["q"]), "nomadfix": ("search_document: ", "search_query: "), "none": ("", "")}
S = json.load(open("nomadwiki_set.json"))
rows = {}
with open('/data/home/tmp/nomadindex/dataset/chunks_wikipedia.jsonl') as f:
    for line in f:
        try: o = json.loads(line)
        except Exception: break
        rows[o["i"]] = o
ci = S["corpus_i"]; qs = S["questions"]
MAXC = 4000  # NOMAD caps embed inputs at 4000 chars
def score(D, Q, qs):
    Dn = D / np.linalg.norm(D, axis=1, keepdims=True).clip(1e-9); Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True).clip(1e-9)
    pos = {i: j for j, i in enumerate(ci)}
    r1 = r5 = r10 = mrr = 0.0
    for qi, q in enumerate(qs):
        s = Dn @ Qn[qi]; tgt = pos[q["chunk_i"]]
        rank = int((s > s[tgt]).sum()) + 1
        r1 += rank <= 1; r5 += rank <= 5; r10 += rank <= 10; mrr += (1 / rank) if rank <= 10 else 0
    n = len(qs); return {"recall@1": r1 / n, "recall@5": r5 / n, "recall@10": r10 / n, "mrr@10": mrr / n, "nq": n, "corpus": len(ci)}
todo = [v for v in variants if not os.path.exists(f"{beir_eval.EMB}/{k}_{v}_nomadwiki_docs.npy")]
if todo:
    p, t = srv.start(f"nomadindex-w-{k}", m["gguf"], 18706, f"--pooling {m['pooling']} {args}", max_life=1700)
    base = "http://192.168.1.69:18706"
    try:
        for v in todo:
            dp, qp = PFX[v]; t0 = time.time()
            Q = beir_eval.embed_many(base, k, [qp + q["question"] for q in qs], bs=16, clients=3)
            D = beir_eval.embed_many(base, k, [dp + rows[i]["text"][:MAXC] for i in ci], bs=16, clients=3)
            np.save(f"{beir_eval.EMB}/{k}_{v}_nomadwiki_docs.npy", D.astype(np.float16)); np.save(f"{beir_eval.EMB}/{k}_{v}_nomadwiki_queries.npy", Q.astype(np.float16))
            print(k, v, "embedded in", round(time.time() - t0), "s", flush=True)
    finally:
        srv.stop(f"nomadindex-w-{k}", p)
for v in variants:
    D = np.load(f"{beir_eval.EMB}/{k}_{v}_nomadwiki_docs.npy").astype(np.float32); Q = np.load(f"{beir_eval.EMB}/{k}_{v}_nomadwiki_queries.npy").astype(np.float32)
    r = score(D, Q, qs); r.update({"model": k, "variant": v, "dataset": "nomadwiki", "dim": int(D.shape[1])})
    print(json.dumps(r)); open("exp5_nomadwiki.jsonl", "a").write(json.dumps(r) + "\n")
