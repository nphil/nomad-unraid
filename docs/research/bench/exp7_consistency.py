"""Batch-consistency (accuracy/correctness, not timing): embed 12 real chunks one-by-one vs as one batch with -np 4 slots; cosine should be ~1.0.
usage: python3 exp7_consistency.py MODEL[,MODEL...]"""
import json, sys
from bench_lib import *
import srv_locked as srv
from models_cfg import MODELS
texts = json.load(open('texts_prod_sample.json'))
for k in sys.argv[1].split(","):
    m = MODELS[k]; cname = f"nomadindex-c-{k}"
    p, t = srv.start(cname, m["gguf"], 18707, f"--pooling {m['pooling']} -ngl 999 -c 4096 -b 2048 -ub 2048 -np 4 -fa on", max_life=600)
    try:
        r = consistency_test("http://192.168.1.69:18707", k, texts, prefix=m["doc"])
        r.update({"model": k, "np": 4, "vram_mb": srv.vram_mb(cname)}); print(json.dumps(r), flush=True)
        open("exp7_consistency.jsonl", "a").write(json.dumps(r) + "\n")
    finally:
        srv.stop(cname, p)
