"""Quiet-window speed suite. Every measurement records load1 before/after and is flagged PROVISIONAL if load1 >= 8.
Lock-guarded (flock /tmp/agents-heavy.lock). usage: python3 exp4_speed_suite.py [rounds]"""
import json, sys, time, random
from bench_lib import *
import srv_locked as srv
from models_cfg import MODELS
texts = json.load(open('texts_prod_sample.json'))
rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 2
# (key, gguf override, server args, doc prefix override)
CASES = [
  ("nomic15_q8", "nomic15", "nomic-embed-text-v1.5.Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("nomic15_f32", "nomic15", "nomic-embed-text-v1.5.f32.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("nomic15_f16", "nomic15", "nomic-embed-text-v1.5.f16.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("gemma300_q8", "gemma300", "embeddinggemma-300M-Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("gemma300_f32", "gemma300", "embeddinggemma-300M-F32.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("qwen3_06_q8", "qwen3_06", "Qwen3-Embedding-0.6B-Q8_0.gguf", "-ngl 999 -c 4096 -b 1024 -ub 1024 -fa on"),
  ("arcticm2_q8", "arcticm2", "arctic-embed-m-v2-q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("bgem3_q8", "bgem3", "bge-m3-q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("arcticl2_q8", "arcticl2", "arctic-embed-l-v2-q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("jina5nano_q8", "jina5nano", "v5-nano-retrieval-Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
  ("granite_r2_q8", "granite_r2", "granite-embedding-english-r2.Q8_0.gguf", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on"),
]
TESTS = [(1, 1, 20), (2, 8, 30), (1, 32, 30)]
order = list(CASES)
for rd in range(rounds):
    random.Random(rd).shuffle(order)
    for name, mk, gguf, args in order:
        m = MODELS[mk]; cname = "nomadindex-speed"
        print(f"=== round {rd} {name}", flush=True)
        ql = srv.wait_quiet(max_load=8.0, max_wait=900)
        if ql is None: print("  host never got quiet (load1 >= 8 for 15 min); running anyway, results flagged provisional", flush=True)
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
                rec.update({"case": name, "round": rd, "load1_before": l0, "load1_after": l1, "provisional": max(l0, l1) >= 8,
                            "vram_mb": srv.vram_mb(cname)})
                print(json.dumps(rec), flush=True); open("exp4_speed.jsonl", "a").write(json.dumps(rec) + "\n")
        finally:
            srv.stop(cname, p)
