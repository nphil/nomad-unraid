import json, time, sys, urllib.error
from bench_lib import *
import srv
from models_cfg import MODELS
texts = json.load(open('texts_prod_sample.json'))
k = sys.argv[1]; args = sys.argv[2]; m = MODELS[k]; cname = "nomadindex-bench-diag"
t = srv.start(cname, m["gguf"], 18703, f"--pooling {m['pooling']} {args}")
base = "http://192.168.1.69:18703"
print("started", round(t,1), "vram", srv.vram_mb(cname), flush=True)
for clients, batch, secs in [(4, 8, 20)]:
    rec = load_test(base, k, texts, clients, batch, seconds=secs, prefix=m["doc"])
    print(json.dumps(rec), flush=True)
print("--- container state:", sh("ssh unraid 'docker ps -a --filter name=nomadindex-bench-diag --format \"{{.Status}}\"'"))
print("--- container logs (grep errors)"); 
lg = srv.logs(cname, 400)
import re
for line in lg.splitlines():
    if re.search(r"(error|fail|abort|cuda|assert|oom|out of memory|too large|exceed|400|500|crash)", line, re.I): print(line[:300])
print("--- tail"); print("\n".join(lg.splitlines()[-12:]))
srv.stop(cname)
