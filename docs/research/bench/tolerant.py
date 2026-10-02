"""Monkeypatch for beir_eval.embed_many: a batch the server refuses (input > physical batch / slot context) is retried item by item; an item that is still
refused counts as REJECTED (its vector becomes zeros, so it can never be retrieved - exactly what NOMAD would lose) instead of aborting the whole run.
Rejections are appended to /data/home/tmp/normalload/t5/rejected.jsonl.  NormalLoadRunAgent 2026-10-02."""
import json, threading, time
import numpy as np
import beir_eval
from bench_lib import embed
def embed_many(base, model, texts, bs=16, clients=4, timeout=600, dim=None, retries=3):
    out = [None] * len(texts); idx = list(range(0, len(texts), bs)); lock = threading.Lock(); pos = [0]; rej = []
    def worker():
        while True:
            with lock:
                if pos[0] >= len(idx): return
                s = idx[pos[0]]; pos[0] += 1
            batch = texts[s:s + bs]; v = None
            for _ in range(retries):
                try: v, _dt, _tk = embed(base, model, batch, timeout); break
                except Exception: v = None; time.sleep(1)
            if v is None:
                v = []
                for k, t in enumerate(batch):
                    e = None
                    for _ in range(2):
                        try: e = embed(base, model, [t], timeout)[0][0]; break
                        except Exception: time.sleep(0.5)
                    if e is None:
                        with lock: rej.append(s + k)
                    v.append(e)
            for k, vec in enumerate(v): out[s + k] = vec
    ths = [threading.Thread(target=worker) for _ in range(clients)]
    for t in ths: t.start()
    for t in ths: t.join()
    d = next((len(x) for x in out if x is not None), dim or 768)
    for i, x in enumerate(out):
        if x is None: out[i] = [0.0] * d
    open("/data/home/tmp/normalload/t5/rejected.jsonl", "a").write(json.dumps({"model": model, "n": len(texts), "rejected": len(rej), "first": sorted(rej)[:8], "ts": time.time()}) + "\n")
    return np.asarray(out, dtype=np.float32)
beir_eval.embed_many = embed_many
