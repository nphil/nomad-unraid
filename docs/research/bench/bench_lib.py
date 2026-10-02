import json, time, urllib.request, urllib.error, subprocess, threading, statistics as st, random, os, sys
def sh(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
def host_state():
    s = sh("ssh unraid 'cat /proc/loadavg | cut -d\" \" -f1-3; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits'")
    return s.replace("\n", " | ")
def post_json(url, body, timeout=300):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    return data, time.time() - t0
def embed(base, model, inputs, timeout=300, extra=None):
    body = {"model": model, "input": inputs, "encoding_format": "float"}
    if extra: body.update(extra)
    data, dt = post_json(base + "/v1/embeddings", body, timeout)
    vecs = [d["embedding"] for d in data["data"]]
    toks = (data.get("usage") or {}).get("prompt_tokens")
    return vecs, dt, toks
def sweep(base, model, texts, batch_sizes, reps, clients=1, prefix="search_document: ", log=print, timeout=300):
    """Each rep sends clients concurrent requests of `batch` texts; returns per-config dict."""
    out = []
    rnd = random.Random(1)
    for b in batch_sizes:
        lat = []; toks_total = 0; chunks_total = 0; wall0 = time.time(); errs = 0
        def worker(k):
            nonlocal toks_total, chunks_total, errs
            for r in range(reps):
                batch = [prefix + t for t in rnd.sample(texts, b)]
                try:
                    v, dt, tk = embed(base, model, batch, timeout)
                    lat.append(dt); chunks_total += len(batch); toks_total += (tk or 0)
                except Exception as e:
                    errs += 1; log(f"   err batch={b}: {str(e)[:160]}")
        ths = [threading.Thread(target=worker, args=(k,)) for k in range(clients)]
        hs = host_state()
        for t in ths: t.start()
        for t in ths: t.join()
        wall = time.time() - wall0
        rec = {"batch": b, "clients": clients, "reps": reps, "errors": errs, "wall_s": round(wall, 2),
               "chunks_per_s": round(chunks_total / wall, 1) if wall else None,
               "tokens_per_s": round(toks_total / wall) if toks_total else None,
               "tokens_total": toks_total, "chunks_total": chunks_total,
               "lat_median_s": round(st.median(lat), 3) if lat else None, "lat_max_s": round(max(lat), 3) if lat else None,
               "host_before": hs}
        log(json.dumps(rec)); out.append(rec)
    return out

def load_test(base, model, texts, clients, batch, seconds, prefix="search_document: ", timeout=300, warm=True, log=print):
    """Closed-loop load: `clients` threads each send `batch`-sized requests back to back for `seconds`.
    Returns steady-state chunks/s and tokens/s plus latency stats."""
    rnd = random.Random(123)
    stop = time.time() + seconds
    lat = []; chunks = [0]; toks = [0]; errs = [0]; lock = threading.Lock()
    if warm:
        try: embed(base, model, [prefix + t for t in rnd.sample(texts, min(batch, 8))], timeout)
        except Exception as e: log("warm err " + str(e)[:100])
    hs0 = host_state()
    t_start = time.time()
    def worker(seed):
        r = random.Random(seed)
        while time.time() < stop:
            b = [prefix + t for t in r.sample(texts, batch)]
            try:
                v, dt, tk = embed(base, model, b, timeout)
                with lock:
                    lat.append(dt); chunks[0] += len(b); toks[0] += (tk or 0)
            except Exception as e:
                with lock: errs[0] += 1
                log("   err: " + str(e)[:140]); time.sleep(0.5)
    ths = [threading.Thread(target=worker, args=(1000 + k,)) for k in range(clients)]
    for t in ths: t.start()
    for t in ths: t.join()
    wall = time.time() - t_start
    hs1 = host_state()
    rec = {"clients": clients, "batch": batch, "seconds": round(wall, 1), "requests": len(lat), "errors": errs[0],
           "chunks_per_s": round(chunks[0] / wall, 1), "tokens_per_s": round(toks[0] / wall),
           "tokens_per_chunk": round(toks[0] / max(1, chunks[0]), 1),
           "lat_p50_s": round(st.median(lat), 3) if lat else None, "lat_max_s": round(max(lat), 3) if lat else None,
           "host_start": hs0, "host_end": hs1}
    return rec

def consistency_test(base, model, texts, prefix="", n=12):
    """Embed n texts one by one and as one batch; report min/mean cosine between the two (batch-drift / numerics check)."""
    import numpy as np
    sample = [prefix + t for t in texts[:n]]
    singles = []
    for t in sample:
        v, dt, tk = embed(base, model, [t]); singles.append(v[0])
    batch, dt, tk = embed(base, model, sample)
    a = np.asarray(singles, dtype=np.float64); b = np.asarray(batch, dtype=np.float64)
    cos = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1))
    return {"n": n, "cos_min": float(cos.min()), "cos_mean": float(cos.mean()), "norm_mean": float(np.linalg.norm(b, axis=1).mean())}
