"""CPU-only: effect of MRL truncation, int8 scalar and binary quantization (with/without rescoring) on retrieval quality,
computed from cached embeddings in emb/. usage: python3 exp8_compress.py [tag_prefix ...]   e.g. nomic15_nomadfix gemma300_native"""
import glob, json, os, sys, numpy as np
import beir_eval
EMB = beir_eval.EMB
def norm(x): return x / np.linalg.norm(x, axis=1, keepdims=True).clip(1e-9)
def int8(x, lo=None, hi=None):
    if lo is None: lo, hi = np.quantile(x, 0.005), np.quantile(x, 0.995)
    return np.clip(np.round((x - lo) / (hi - lo) * 255), 0, 255).astype(np.uint8), lo, hi
def deint8(q, lo, hi): return q.astype(np.float32) / 255 * (hi - lo) + lo
def evaluate_variants(tag, ds):
    D = np.load(f"{EMB}/{tag}_{ds}_docs.npy").astype(np.float32); Q = np.load(f"{EMB}/{tag}_{ds}_queries.npy").astype(np.float32)
    if ds == "nomadwiki":
        S = json.load(open("nomadwiki_set.json")); pos = {i: j for j, i in enumerate(S["corpus_i"])}
        tgt = np.array([pos[q["chunk_i"]] for q in S["questions"]])
        def metric(Dx, Qx, rerank_full=None, over=1):
            r5 = 0; r1 = 0
            for qi in range(len(Qx)):
                s = norm(Dx) @ norm(Qx[qi:qi+1]).T if False else (norm(Dx) @ norm(Qx[qi:qi+1])[0])
                if rerank_full is not None:
                    top = np.argpartition(-s, 5 * over)[:5 * over]; s2 = norm(rerank_full[0][top]) @ norm(rerank_full[1][qi:qi+1])[0]
                    order = top[np.argsort(-s2)]
                else: order = np.argsort(-s)[:5]
                r1 += order[0] == tgt[qi]; r5 += tgt[qi] in order[:5]
            return {"recall@1": r1 / len(Qx), "recall@5": r5 / len(Qx)}
    else:
        corpus, queries, qrels = beir_eval.load(ds)
        doc_ids = list(corpus); q_ids = [q for q in queries if q in qrels]
        def metric(Dx, Qx, rerank_full=None, over=1):
            if rerank_full is None: return {"ndcg@10": beir_eval.evaluate(doc_ids, Dx, q_ids, Qx, qrels)["ndcg@10"]}
            Dn = norm(Dx); Qn = norm(Qx); Df = norm(rerank_full[0]); Qf = norm(rerank_full[1]); nd = []
            for qi in range(len(q_ids)):
                s = Dn @ Qn[qi]; top = np.argpartition(-s, min(10 * over, len(s) - 1))[:10 * over]
                s2 = Df[top] @ Qf[qi]; order = top[np.argsort(-s2)][:10]
                nd.append(beir_eval.ndcg_at_k([doc_ids[o] for o in order], qrels[q_ids[qi]], 10))
            return {"ndcg@10": float(np.mean(nd))}
    out = {"full_f32": metric(D, Q)}
    for d in (512, 384, 256, 128):
        if d < D.shape[1]: out[f"mrl_{d}"] = metric(norm(D[:, :d]), norm(Q[:, :d]))
    qd, lo, hi = int8(D); Dq = deint8(qd, lo, hi); out["int8_nores"] = metric(Dq, Q)
    Db = np.where(D > 0, 1.0, -1.0).astype(np.float32); Qb = np.where(Q > 0, 1.0, -1.0).astype(np.float32)
    out["binary_nores"] = metric(Db, Qb); out["binary_rescore_x4"] = metric(Db, Qb, (D, Q), 4); out["binary_rescore_x10"] = metric(Db, Qb, (D, Q), 10)
    return out
if __name__ == "__main__":
    tags = sys.argv[1:] or sorted({os.path.basename(f).rsplit("_", 2)[0] for f in glob.glob(f"{EMB}/*_docs.npy")})
    res = {}
    for f in sorted(glob.glob(f"{EMB}/*_docs.npy")):
        base = os.path.basename(f)[:-9]; tag, ds = base.rsplit("_", 1) if base.count("_") >= 1 else (base, "")
        # tag is everything up to the last underscore-separated dataset token
        for dsn in ("nomadwiki", "scifact", "nfcorpus", "arguana", "scidocs"):
            if base.endswith("_" + dsn): tag, ds = base[: -len(dsn) - 1], dsn
        if tags and not any(tag.startswith(t) for t in tags): continue
        res[f"{tag}|{ds}"] = evaluate_variants(tag, ds); print(tag, ds, json.dumps(res[f"{tag}|{ds}"]), flush=True)
    json.dump(res, open("exp8_compress.json", "w"), indent=1)
