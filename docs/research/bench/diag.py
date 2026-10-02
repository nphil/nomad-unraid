import json, time, sys, urllib.error
from bench_lib import *
import srv
from models_cfg import MODELS
texts = json.load(open('texts_prod_sample.json'))
k = sys.argv[1]; args = sys.argv[2]; m = MODELS[k]; cname = "nomadindex-bench-diag"
t = srv.start(cname, m["gguf"], 18703, f"--pooling {m['pooling']} {args}")
base = "http://192.168.1.69:18703"
print("started", round(t,1), "vram", srv.vram_mb(cname), flush=True)
ok = True
for n in [1, 2, 4, 8, 16, 32]:
    try:
        v, dt, tk = embed(base, k, [m["doc"] + x for x in texts[10:10+n]], timeout=120)
        print("batch", n, "ok", round(dt, 2), "s tokens", tk, "dim", len(v[0]), "vram", srv.vram_mb(cname), flush=True)
    except urllib.error.HTTPError as e:
        print("batch", n, "HTTP", e.code, e.read().decode()[:300], flush=True); break
    except Exception as e:
        print("batch", n, "FAIL", str(e)[:200], flush=True); break
print("--- container logs tail"); print(srv.logs(cname, 30))
srv.stop(cname)
