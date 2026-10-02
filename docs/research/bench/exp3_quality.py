"""Quality (nDCG@10) on small BEIR sets, per model and prompt variant. Lock-guarded; resumable (embeddings cached in emb/).
usage: python3 exp3_quality.py MODEL VARIANT[,VARIANT] DATASETS [server_args]
variants: native (model's own prompts), nomadfix (NOMAD's hard-coded 'search_document: ' / 'search_query: '), none
"""
import json, sys, time, os
from bench_lib import *
import srv_locked as srv
from models_cfg import MODELS
import beir_eval
k = sys.argv[1]; variants = sys.argv[2].split(","); datasets = sys.argv[3].split(",")
args = sys.argv[4] if len(sys.argv) > 4 else "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"
m = MODELS[k]
PFX = {"native": (m["doc"], m["q"]), "nomadfix": ("search_document: ", "search_query: "), "none": ("", "")}
todo = []
for v in variants:
    for ds in datasets:
        tag = f"{k}_{v}"
        if os.path.exists(f"{beir_eval.EMB}/{tag}_{ds}_docs.npy"): continue
        todo.append((v, ds))
out_file = "exp3_quality.jsonl"
def results_for(v, ds, base):
    dp, qp = PFX[v]
    return beir_eval.run_dataset(base, k, ds, dp, qp, f"{k}_{v}", bs=16, clients=3)
cname = f"nomadindex-q-{k}"
if todo:
    l = srv.wait_quiet(max_load=1e9)  # quality is load-insensitive; the lock alone gates us
    p, t = srv.start(cname, m["gguf"], 18704, f"--pooling {m['pooling']} {args}", max_life=1700)
    base = "http://192.168.1.69:18704"
    try:
        for v, ds in todo:
            r = results_for(v, ds, base); r.update({"model": k, "variant": v, "server_args": args, "load1": srv.load1()})
            open(out_file, "a").write(json.dumps(r) + "\n")
    finally:
        srv.stop(cname, p)
# always (re)score from cached embeddings so truncated/quantized variants can be derived offline
for v in variants:
    for ds in datasets:
        dp, qp = PFX[v]
        r = beir_eval.run_dataset("", k, ds, dp, qp, f"{k}_{v}")
        r.update({"model": k, "variant": v, "rescored": True}); open(out_file, "a").write(json.dumps(r) + "\n")
