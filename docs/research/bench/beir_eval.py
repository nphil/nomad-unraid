import json, os, time, threading, numpy as np, random, math
from bench_lib import embed
BEIR = "/data/home/tmp/nomadindex/bench/beir"
EMB = "/data/home/tmp/nomadindex/bench/emb"
os.makedirs(EMB, exist_ok=True)
def load(ds, max_docs=None, seed=0):
    corpus = {}
    with open(f"{BEIR}/{ds}/corpus.jsonl") as f:
        for line in f:
            o = json.loads(line); corpus[o["_id"]] = ((o.get("title") or "") + " " + (o.get("text") or "")).strip()
    queries = {}
    with open(f"{BEIR}/{ds}/queries.jsonl") as f:
        for line in f:
            o = json.loads(line); queries[o["_id"]] = o["text"]
    qrels = {}
    with open(f"{BEIR}/{ds}/qrels/test.tsv") as f:
        next(f)
        for line in f:
            q, d, s = line.rstrip("\n").split("\t")
            if int(s) > 0: qrels.setdefault(q, {})[d] = int(s)
    qrels = {q: r for q, r in qrels.items() if q in queries}
    return corpus, queries, qrels
def embed_many(base, model, texts, bs=16, clients=4, timeout=600, dim=None, retries=3):
    out = [None] * len(texts)
    idx = list(range(0, len(texts), bs))
    lock = threading.Lock(); pos = [0]; errs = []
    def worker():
        while True:
            with lock:
                if pos[0] >= len(idx): return
                s = idx[pos[0]]; pos[0] += 1
            batch = texts[s:s + bs]
            for a in range(retries):
                try:
                    v, dt, tk = embed(base, model, batch, timeout); break
                except Exception as e:
                    v = None; time.sleep(2)
            if v is None: errs.append(s); continue
            for k, vec in enumerate(v): out[s + k] = vec
    ths = [threading.Thread(target=worker) for _ in range(clients)]
    for t in ths: t.start()
    for t in ths: t.join()
    if errs: raise RuntimeError(f"{len(errs)} batches failed")
    return np.asarray(out, dtype=np.float32)
def ndcg_at_k(ranked, rel, k=10):
    dcg = sum(rel.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0
def evaluate(doc_ids, D, q_ids, Q, qrels, k=10):
    Dn = D / np.linalg.norm(D, axis=1, keepdims=True).clip(1e-9); Qn = Q / np.linalg.norm(Q, axis=1, keepdims=True).clip(1e-9)
    nd = []; rc = []; mrr = []
    for i in range(0, len(q_ids), 256):
        S = Qn[i:i + 256] @ Dn.T
        top = np.argpartition(-S, min(100, S.shape[1] - 1), axis=1)[:, :100]
        for j in range(S.shape[0]):
            q = q_ids[i + j]
            order = top[j][np.argsort(-S[j][top[j]])]
            ranked = [doc_ids[o] for o in order]
            rel = qrels[q]
            nd.append(ndcg_at_k(ranked, rel, k))
            rc.append(len(set(ranked[:100]) & set(rel)) / len(rel))
            rr = 0
            for r, d in enumerate(ranked[:k]):
                if d in rel: rr = 1 / (r + 1); break
            mrr.append(rr)
    return {"ndcg@10": float(np.mean(nd)), "recall@100": float(np.mean(rc)), "mrr@10": float(np.mean(mrr)), "nq": len(nd)}
def run_dataset(base, model, ds, doc_prefix, query_prefix, tag, max_len_chars=None, bs=16, clients=4, log=print):
    corpus, queries, qrels = load(ds)
    doc_ids = list(corpus); q_ids = [q for q in queries if q in qrels]
    dtxt = [doc_prefix + (corpus[d][:max_len_chars] if max_len_chars else corpus[d]) for d in doc_ids]
    qtxt = [query_prefix + queries[q] for q in q_ids]
    fd = f"{EMB}/{tag}_{ds}_docs.npy"; fq = f"{EMB}/{tag}_{ds}_queries.npy"
    t0 = time.time()
    if os.path.exists(fd) and os.path.exists(fq):
        D = np.load(fd).astype(np.float32); Q = np.load(fq).astype(np.float32); cached = True
    else:
        Q = embed_many(base, model, qtxt, bs=bs, clients=clients)
        D = embed_many(base, model, dtxt, bs=bs, clients=clients)
        np.save(fd, D.astype(np.float16)); np.save(fq, Q.astype(np.float16)); cached = False
    el = time.time() - t0
    res = evaluate(doc_ids, D, q_ids, Q, qrels)
    res.update({"dataset": ds, "tag": tag, "docs": len(doc_ids), "embed_seconds": round(el, 1), "cached": cached, "dim": int(D.shape[1])})
    log(json.dumps(res)); return res
