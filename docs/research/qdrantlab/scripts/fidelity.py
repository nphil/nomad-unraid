#!/usr/bin/env python3
"""fidelity.py - search fidelity of Qdrant layouts on REAL nomic-embed-text-v1.5 vectors (float16 .npy from NomadIndexAgent).

For every set (nomadwiki, scifact, nfcorpus, arguana, scidocs) and layout variant it builds a throw-away collection in ONE
lock-held Qdrant session, runs the NOMAD search shape (limit 15, score_threshold 0.3, must_not active=false) with several
search-parameter modes, and reports
  * recall@10/@15 against EXACT full-precision (768-d float32) brute-force top-k of the same embeddings
  * task quality: NDCG@10 + recall@15 for BEIR sets (qrels/test.tsv), hit@1/5/10/15 + MRR@10 for nomadwiki (one target chunk per question)
Matryoshka variants truncate the first d dims and re-normalise (docs and queries), truth stays the 768-d exact ranking.

usage: fidelity.py --sets nomadwiki,scifact --variants f32,int8,bin1,mrl512,mrl384,mrl256 [--out results/fidelity.json]
"""
import argparse
import json
import math
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qlab  # noqa
from qlab import *  # noqa

EMB = '/data/home/tmp/nomadindex/bench/emb'
BEIR = '/data/home/tmp/nomadindex/bench/beir'
TAG = 'nomic15_nomadfix'
NWSET = '/data/home/tmp/nomadindex/bench/nomadwiki_set.json'
FID = 'fid'

Q_INT8 = {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}
Q_BIN = {'binary': {'always_ram': True}}
Q_BIN2 = {'binary': {'always_ram': True, 'encoding': 'two_bits', 'query_encoding': 'scalar8bits'}}
DISKV = {'vectors': {'on_disk': True}}


def qq(**kw):
    return {'quantization': kw}


MODES_F32 = [{'name': 'default', 'params': None}, {'name': 'hnsw_ef256', 'params': {'hnsw_ef': 256}}]
MODES_Q = [{'name': 'default', 'params': None}, {'name': 'norescore', 'params': qq(rescore=False)},
           {'name': 'rescore_os1', 'params': qq(rescore=True, oversampling=1.0)},
           {'name': 'rescore_os2', 'params': qq(rescore=True, oversampling=2.0)},
           {'name': 'rescore_os3', 'params': qq(rescore=True, oversampling=3.0)}]
MODES_B = MODES_Q + [{'name': 'rescore_os5', 'params': qq(rescore=True, oversampling=5.0)}]

VARIANTS = {
    'f32': dict(dim=768, create={}, modes=MODES_F32),
    'int8': dict(dim=768, create={**DISKV, 'quantization_config': Q_INT8}, modes=MODES_Q),
    'bin1': dict(dim=768, create={**DISKV, 'quantization_config': Q_BIN}, modes=MODES_B),
    'bin2': dict(dim=768, create={**DISKV, 'quantization_config': Q_BIN2}, modes=MODES_B),
    'f16': dict(dim=768, create={'vectors': {'datatype': 'float16'}}, modes=MODES_F32[:1]),
}
for d in (512, 384, 256, 128):
    VARIANTS[f'mrl{d}'] = dict(dim=d, create={}, modes=MODES_F32[:1])
    VARIANTS[f'mrl{d}_int8'] = dict(dim=d, create={**DISKV, 'quantization_config': Q_INT8}, modes=MODES_Q[:1] + MODES_Q[3:5])
    VARIANTS[f'mrl{d}_bin1'] = dict(dim=d, create={**DISKV, 'quantization_config': Q_BIN}, modes=MODES_B[:1] + MODES_B[3:6])


def norm(x):
    return x / np.linalg.norm(x, axis=1, keepdims=True).clip(1e-9)


def trunc(x, d):
    return norm(x[:, :d]) if d < x.shape[1] else norm(x)


def ndcg_at_k(ranked, rel, k=10):
    dcg = sum(rel.get(d, 0) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def load_set(name):
    D = np.load(f'{EMB}/{TAG}_{name}_docs.npy').astype(np.float32)
    Q = np.load(f'{EMB}/{TAG}_{name}_queries.npy').astype(np.float32)
    if name == 'nomadwiki':
        S = json.load(open(NWSET))
        ci = S['corpus_i']
        pos = {i: j for j, i in enumerate(ci)}
        tgt = [pos[q['chunk_i']] for q in S['questions']]
        assert len(ci) == len(D), (len(ci), len(D))
        return {'kind': 'nomadwiki', 'D': D, 'Q': Q[:len(tgt)], 'target': tgt}
    corpus, queries, qrels = [], {}, {}
    ids = []
    with open(f'{BEIR}/{name}/corpus.jsonl') as f:
        for line in f:
            ids.append(json.loads(line)['_id'])
    qtext = {}
    with open(f'{BEIR}/{name}/queries.jsonl') as f:
        for line in f:
            o = json.loads(line)
            qtext[o['_id']] = o['text']
    with open(f'{BEIR}/{name}/qrels/test.tsv') as f:
        next(f)
        for line in f:
            q, d, s = line.rstrip('\n').split('\t')
            if int(s) > 0:
                qrels.setdefault(q, {})[d] = int(s)
    qrels = {q: r for q, r in qrels.items() if q in qtext}
    q_ids = [q for q in qtext if q in qrels]
    assert len(ids) == len(D), (name, len(ids), len(D))
    assert len(q_ids) == len(Q), (name, len(q_ids), len(Q))
    return {'kind': 'beir', 'D': D, 'Q': Q, 'doc_ids': ids, 'q_ids': q_ids, 'qrels': qrels}


def exact_rank(D, Q, k=100):
    Dn, Qn = norm(D), norm(Q)
    S = Qn @ Dn.T
    top = np.argpartition(-S, min(k, S.shape[1] - 1), axis=1)[:, :k]
    order = np.take_along_axis(top, np.argsort(-np.take_along_axis(S, top, axis=1), axis=1), axis=1)
    return order, np.take_along_axis(S, order, axis=1)


def task_metrics(S, ranked_rows):
    """ranked_rows: list (per query) of doc-row lists (best first)."""
    out = {}
    if S['kind'] == 'beir':
        nd, rc = [], []
        for qi, rows in enumerate(ranked_rows):
            rel = S['qrels'][S['q_ids'][qi]]
            docs = [S['doc_ids'][r] for r in rows]
            nd.append(ndcg_at_k(docs, rel, 10))
            rc.append(len(set(docs[:15]) & set(rel)) / len(rel))
        out = {'ndcg@10': float(np.mean(nd)), 'recall@15': float(np.mean(rc)), 'nq': len(nd)}
    else:
        h1 = h5 = h10 = h15 = mrr = 0.0
        for qi, rows in enumerate(ranked_rows):
            t = S['target'][qi]
            rk = rows.index(t) + 1 if t in rows else 10 ** 9
            h1 += rk <= 1
            h5 += rk <= 5
            h10 += rk <= 10
            h15 += rk <= 15
            mrr += (1.0 / rk) if rk <= 10 else 0.0
        n = len(ranked_rows)
        out = {'hit@1': h1 / n, 'hit@5': h5 / n, 'hit@10': h10 / n, 'hit@15': h15 / n, 'mrr@10': mrr / n, 'nq': n}
    return out


def run_variant(lab, S, name, v, truth_rows, truth_scores, log_fn):
    qd = lab.qd
    d = v['dim']
    D, Q = trunc(S['D'], d), trunc(S['Q'], d)
    if qd.req('GET', f'/collections/{FID}')[0] == 200:
        qd.ok('DELETE', f'/collections/{FID}')
    create_collection(qd, coll=FID, dim=d, create=v['create'], indexes=True)
    t0 = perf_counter()
    rows = np.arange(len(D))
    pay = [b'{"active":true,"source":"/app/storage/zim/x.zim","content_type":"zim_article"}'] * 500
    for s in range(0, len(D), 500):
        r = rows[s:s + 500]
        qd.ok('PUT', f'/collections/{FID}/points?wait=true', points_body(r, D[r], pay[:len(r)]))
    t_up = perf_counter() - t0
    tg, info = wait_green(qd, FID, stable=3)
    out = {'dim': d, 'points': len(D), 'upsert_s': t_up, 'build_wait_s': tg, 'segments': info['segments_count'],
           'indexed_vectors': info['indexed_vectors_count'], 'modes': []}
    for mode in v['modes']:
        bodies = query_bodies(Q, params=mode['params'], filt=FILTER_V135)
        lat, srv, res = run_queries(qd, bodies, coll=FID)
        # recall vs exact 768-d float32 truth (only truth items above the 0.3 threshold)
        rec = {}
        for k in (10, 15):
            vals = []
            for qi, hits in enumerate(res):
                gt = truth_rows[qi][:k][truth_scores[qi][:k] >= 0.3]
                if len(gt) == 0:
                    continue
                got = {uuid_row(h[0]) for h in hits[:k]}
                vals.append(len(got & set(gt.tolist())) / len(gt))
            rec[f'recall@{k}_vs_exact768'] = float(np.mean(vals)) if vals else None
        ranked = [[uuid_row(h[0]) for h in hits] for hits in res]
        m = {'mode': mode['name'], 'params': mode['params'], **rec, 'mean_hits': float(np.mean([len(h) for h in res])),
             'task': task_metrics(S, ranked), 'p50_ms': float(np.percentile(lat, 50) * 1e3)}
        out['modes'].append(m)
        log_fn(f"    {name:<13} {mode['name']:<12} recall@15={m['recall@15_vs_exact768']:.4f} task={json.dumps({k2: round(x, 4) for k2, x in m['task'].items() if k2 != 'nq'})} "
               f"hits={m['mean_hits']:.1f} p50={m['p50_ms']:.1f}ms")
    qd.ok('DELETE', f'/collections/{FID}')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sets', default='nomadwiki,scifact,nfcorpus,arguana')
    ap.add_argument('--variants', default='f32,int8,bin1,bin2,mrl512,mrl384,mrl256,mrl128,mrl384_int8,mrl256_int8')
    ap.add_argument('--out', default=f'{RES}/fidelity.json')
    ap.add_argument('--mem', default='4g')
    a = ap.parse_args()
    os.nice(15)
    ID_MODE['mode'] = 'int'
    results = json.load(open(a.out)) if os.path.exists(a.out) else {}
    sets = [s for s in a.sets.split(',') if os.path.exists(f'{EMB}/{TAG}_{s}_docs.npy')]
    missing = [s for s in a.sets.split(',') if s not in sets]
    if missing:
        log(f'sets without embeddings yet (skipped): {missing}')
    if not sets:
        return 5
    loaded = {}
    for s in sets:
        S = load_set(s)
        order, sc = exact_rank(S['D'], S['Q'], k=100)
        S['truth_rows'], S['truth_scores'] = order[:, :15], sc[:, :15]
        S['exact_task'] = task_metrics(S, [list(map(int, r)) for r in order[:, :15]])
        loaded[s] = S
        log(f"set {s}: docs {len(S['D'])} queries {len(S['Q'])} exact-768 task metrics {json.dumps({k: round(v, 4) for k, v in S['exact_task'].items()})}")
        results.setdefault(s, {})['exact768'] = S['exact_task']
        results[s]['docs'] = len(S['D'])
        results[s]['queries'] = len(S['Q'])
        for d in (512, 384, 256, 128):  # exact truncated ranking (separates MRL loss from ANN loss)
            o2, _ = exact_rank(trunc(S['D'], d), trunc(S['Q'], d), k=100)
            results[s].setdefault('exact_trunc', {})[str(d)] = task_metrics(S, [list(map(int, r)) for r in o2[:, :15]])
    lab = Lab('fidelity', mem=a.mem)
    try:
        while lab.free_gb() < 7:
            time.sleep(60)
        lab.start(session=True)
        log(f"container up (lock wait {lab.t_lock_wait:.0f}s), host load {loadavg()}")
        for s in sets:
            for vn in a.variants.split(','):
                v = VARIANTS[vn]
                try:
                    log(f'  set {s} variant {vn}')
                    results[s].setdefault('variants', {})[vn] = run_variant(lab, loaded[s], vn, v, loaded[s]['truth_rows'],
                                                                           loaded[s]['truth_scores'], log)
                    dump(a.out, results)
                except Exception:
                    log('ERROR ' + traceback.format_exc())
                    results[s].setdefault('variants', {})[vn] = {'error': traceback.format_exc()[-400:]}
                    lab.qd.conn = None
    finally:
        results['_meta'] = {'finished': time.strftime('%Y-%m-%d %H:%M:%S'), 'qdrant': 'v1.16.3', 'host_load_end': loadavg()}
        dump(a.out, results)
        lab.stop()
        lab.rmstorage()
    return 0


if __name__ == '__main__':
    sys.exit(main())
