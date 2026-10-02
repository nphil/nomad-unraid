import json, time, sys
from bench_lib import *
import srv
texts = json.load(open('texts_prod_sample.json'))
model = "nomic"
configs = {
  "A_prod_like(-c2048 -b2048 -ub2048)": "--pooling mean -ngl 999 -c 2048 -b 2048 -ub 2048",
  "B_np8(-c8192 -b4096 -ub4096 -np8 -fa on)": "--pooling mean -ngl 999 -c 8192 -b 4096 -ub 4096 -np 8 -fa on",
  "C_np16(-c16384 -b8192 -ub8192 -np16 -fa on)": "--pooling mean -ngl 999 -c 16384 -b 8192 -ub 8192 -np 16 -fa on",
}
results = []
for name, args in configs.items():
    cname = "nomadindex-bench-exp1"
    print("=== config", name, flush=True)
    try:
        t = srv.start(cname, "nomic-embed-text-v1.5.Q8_0.gguf", 18701, args)
    except Exception as e:
        print("START FAILED", e); srv.stop(cname); continue
    base = "http://192.168.1.69:18701"
    time.sleep(2)
    print(" load time", round(t,1), "s")
    for clients, batch in [(1, 8), (4, 8), (8, 8), (4, 32)]:
        rec = load_test(base, model, texts, clients, batch, seconds=25)
        rec["config"] = name; rec["vram_mb"] = srv.vram_mb(cname)
        print(json.dumps(rec), flush=True); results.append(rec)
    srv.stop(cname)
json.dump(results, open('exp1_nomic_server_configs.json', 'w'), indent=1)
