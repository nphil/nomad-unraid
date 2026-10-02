"""VRAM of the embedding servers (host-measured: PIDs of the container's processes matched against nvidia-smi compute apps), NORMAL load.
Flags = what llama-swap would run: nomic (production: -c 2048 -b 2048 -ub 2048) and granite (NomadIndexAgent's proposal: --pooling cls -c 8192 -b 4096 -ub 4096).
Run under one held lock: withlock.sh python3 vram_probe.py   (uses srv_held)."""
import json, random, time
from bench_lib import *
import srv_held as srv
texts = json.load(open('texts_prod_sample.json'))
CASES = [("nomic15_prod_flags", "nomic-embed-text-v1.5.Q8_0.gguf", "mean", "-ngl 999 -c 2048 -b 2048 -ub 2048", "nomic15", "search_document: "),
         ("granite_proposed_flags", "granite-embedding-english-r2.Q8_0.gguf", "cls", "-ngl 999 -c 8192 -b 4096 -ub 4096", "granite_r2", ""),
         ("granite_bench_flags", "granite-embedding-english-r2.Q8_0.gguf", "cls", "-ngl 999 -c 4096 -b 2048 -ub 2048 -fa on", "granite_r2", "")]
def vram(cname):
    pids = set(srv.sh(f"ssh unraid \"docker top {cname} -eo pid\"", 30).split()[1:])
    out = srv.sh("ssh unraid 'nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits'", 30)
    tot = 0
    for line in out.splitlines():
        a, m = [x.strip() for x in line.split(",")]
        if a in pids: tot += int(m)
    return tot
for name, gguf, pool, args, mk, pre in CASES:
    cname = "nomadindex-vram"
    p, t = srv.start(cname, gguf, 18708, f"--pooling {pool} {args}", max_life=300)
    base = "http://192.168.1.69:18708"
    try:
        v0 = vram(cname)
        embed(base, mk, [pre + x for x in random.Random(1).sample(texts, 8)], 120)
        v1 = vram(cname)
        for _ in range(3): embed(base, mk, [pre + x for x in random.Random(2).sample(texts, 32)], 120)
        v2 = vram(cname)
        print(json.dumps({"case": name, "vram_idle_loaded_mib": v0, "after_8": v1, "after_3x32": v2, "start_s": round(t, 1), "load1": srv.load1()}), flush=True)
    finally:
        srv.stop(cname, p)
