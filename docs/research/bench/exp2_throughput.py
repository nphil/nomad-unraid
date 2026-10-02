import json, sys, time, random
from bench_lib import *
import srv
from models_cfg import MODELS, SERVER_ARGS
texts = json.load(open('texts_prod_sample.json'))
keys = sys.argv[1].split(",")
rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 1
out_file = sys.argv[3] if len(sys.argv) > 3 else "exp2_throughput.jsonl"
for rd in range(rounds):
    order = keys if rd % 2 == 0 else list(reversed(keys))
    for k in order:
        m = MODELS[k]; cname = "nomadindex-bench-exp2"
        print(f"=== round {rd} model {k}", flush=True)
        try:
            t = srv.start(cname, m["gguf"], 18702, f"--pooling {m['pooling']} {SERVER_ARGS}")
        except Exception as e:
            print("START FAILED", str(e)[-600:]); srv.stop(cname); continue
        base = "http://192.168.1.69:18702"; time.sleep(1)
        for clients, batch, secs in [(1, 1, 15), (4, 8, 30), (1, 16, 20)]:
            rec = load_test(base, k, texts, clients, batch, seconds=secs, prefix=m["doc"] if m["doc"] else "")
            rec.update({"model": k, "round": rd, "vram_mb": srv.vram_mb(cname), "load_s": round(t, 1)})
            print(json.dumps(rec), flush=True)
            open(out_file, "a").write(json.dumps(rec) + "\n")
        srv.stop(cname)
