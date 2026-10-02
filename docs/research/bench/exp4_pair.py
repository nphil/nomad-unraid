"""Paired speed run nomic-embed-text-v1.5 Q8_0 (A) vs granite-embedding-english-r2 Q8_0 (B): A,B,A,B,... one llama-server container per case under the heavy lock,
same texts (texts_prod_sample.json = 1,800 real NOMAD chunks), same three load tests, NORMAL load (no quiet gate; load1 before/after recorded per test).
usage: python3 exp4_pair.py [rounds]    -> exp4_pair.jsonl"""
import json, sys, time
from bench_lib import *
import srv_held as srv   # lock is held by the caller (withlock.sh) for the whole paired run
from models_cfg import MODELS
texts = json.load(open('texts_prod_sample.json'))
rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
CASES = [("nomic15_q8", "nomic15", "nomic-embed-text-v1.5.Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
         ("granite_r2_q8", "granite_r2", "granite-embedding-english-r2.Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on")]
TESTS = [(1, 1, 20), (2, 8, 30), (1, 32, 30)]     # (clients, batch, seconds): 1x1 = how NOMAD calls
for rd in range(rounds):
    for name, mk, gguf, args in CASES:
        m = MODELS[mk]; cname = "nomadindex-speed"
        print(f"=== round {rd} {name}", flush=True)
        try:
            p, t = srv.start(cname, gguf, 18705, f"--pooling {m['pooling']} {args}", max_life=900)
        except Exception as e:
            print("START FAILED", str(e)[-400:], flush=True); continue
        base = "http://192.168.1.69:18705"
        try:
            for cl, b, secs in TESTS:
                l0 = srv.load1()
                rec = load_test(base, mk, texts, cl, b, secs, prefix=m["doc"])
                l1 = srv.load1()
                rec.update({"case": name, "round": rd, "load1_before": l0, "load1_after": l1, "start_s": round(t, 1), "vram_mb": srv.vram_mb(cname), "ts": time.time()})
                print(json.dumps(rec), flush=True); open("exp4_pair.jsonl", "a").write(json.dumps(rec) + "\n")
        finally:
            srv.stop(cname, p)
