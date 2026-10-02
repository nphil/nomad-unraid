#!/usr/bin/env python3
"""run_v.py - phase-based, lock-friendly runs of NOMAD-style Qdrant variants (slice `qdrantlab`).

Every phase that needs a Qdrant container takes the host-wide lock (/tmp/agents-heavy.lock) for the container's whole
life (see qlab.Lab.start) and stays <= ~12 min; the collection lives in a scratch dir and is re-used by the next phase.

  python3 run_v.py --variant V1 --n 100000 --phase prebuild   # local only: request bodies + exact ground truth (nice 19)
  python3 run_v.py --variant V1 --n 100000 --phase load       # container #1: create, ingest, build, size/RAM numbers
  python3 run_v.py --variant V1 --n 100000 --phase measure    # container #2 (fresh process): RAM after restart, recall, latency, upserts
  python3 run_v.py --variant V1 --n 100000 --phase timing     # quiet-window re-run of ONLY the speed numbers (refuses if load >= 8)
  python3 run_v.py --variant V1 --n 100000 --phase final      # delete the scratch storage of this run

Results accumulate in results/<run>.json. Speed numbers carry the host load; if the 1-min load was >= 8 they are PROVISIONAL.
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from time import perf_counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qlab  # noqa
from qlab import *  # noqa

POOL = '/data/home/tmp/nomadindex/dataset/chunks_wikipedia.jsonl'
SYN_VEC = '/tmp/qlab-work/syn_vectors.f32'
BODY_CACHE = '/tmp/qlab-work/bodies'
LOAD_OK = 8.0  # Main's rule: speed numbers valid only if 1-min load < 8 before AND after

Q_INT8 = {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}
Q_BIN = {'binary': {'always_ram': True}}
DISKV = {'vectors': {'on_disk': True}}
INDEXES = (('source', 'keyword'), ('content_type', 'keyword'), ('collection', 'keyword'), ('active', 'bool'))
IDX_ONDISK = {'source': {'type': 'keyword', 'on_disk': True}, 'content_type': {'type': 'keyword', 'on_disk': True},
              'collection': {'type': 'keyword', 'on_disk': True}, 'active': {'type': 'bool', 'on_disk': True}}


def qq(**kw):
    return {'quantization': kw}


M_PLAIN = [{'name': 'default', 'params': None}, {'name': 'hnsw_ef256', 'params': {'hnsw_ef': 256}}]
M_QUANT = [
    {'name': 'default', 'params': None},                      # what NOMAD sends (no params)
    {'name': 'norescore', 'params': qq(rescore=False)},        # explicit: same as default? (verified by test)
    {'name': 'rescore_os1', 'params': qq(rescore=True, oversampling=1.0)},
    {'name': 'rescore_os2', 'params': qq(rescore=True, oversampling=2.0)},
    {'name': 'rescore_os3', 'params': qq(rescore=True, oversampling=3.0)},
    {'name': 'ignore_quant', 'params': qq(ignore=True)},       # HNSW over the original vectors
]

VARIANTS = {
    'V0': dict(desc='NOMAD defaults (float32 vectors in RAM, HNSW m16/ef100 in RAM, payload on disk)', create={}, modes=M_PLAIN),
    'V1': dict(desc='int8 scalar (always_ram) + originals on disk + HNSW in RAM',
               create={**DISKV, 'quantization_config': Q_INT8}, modes=M_QUANT),
    'V2': dict(desc='V1 + HNSW graph on disk',
               create={**DISKV, 'quantization_config': Q_INT8, 'hnsw_config': {'on_disk': True}}, modes=M_QUANT),
    'V3': dict(desc='V1 built the bulk way: no indexing + no payload indexes while loading; payload indexes, then indexing_threshold 10000 after',
               create={**DISKV, 'quantization_config': Q_INT8, 'optimizers_config': {'indexing_threshold': 0}},
               indexes=False, post_load='bulk_recipe', modes=M_QUANT),
    # ---- extras (anon-RAM investigation, other knobs)
    'E_noidx': dict(desc='V0 without the 4 payload indexes', create={}, indexes=False, ensure_test='skip', modes=M_PLAIN[:1]),
    'E_idxdisk': dict(desc='V0 with the 4 payload indexes on_disk=true', create={}, indexes=IDX_ONDISK, ensure_test='after',
                      modes=M_PLAIN[:1]),
    'E_plain': dict(desc='V0 but HNSW never built (indexing_threshold=0): production-like plain segments',
                    create={'optimizers_config': {'indexing_threshold': 0}}, modes=M_PLAIN[:1]),
    'E_intid': dict(desc='V0 with integer point ids instead of UUIDs', create={}, id_mode='int', modes=M_PLAIN[:1]),
    'E_m8': dict(desc='V0 with HNSW m=8 ef_construct=64', create={'hnsw_config': {'m': 8, 'ef_construct': 64}}, modes=M_PLAIN),
    'E_f16': dict(desc='float16 vector storage, HNSW in RAM', create={'vectors': {'datatype': 'float16'}}, modes=M_PLAIN),
    'E_bin': dict(desc='binary quantization (always_ram), originals on disk',
                  create={**DISKV, 'quantization_config': Q_BIN}, modes=M_QUANT),
    'E_payram': dict(desc='V0 with on_disk_payload=false', create={'on_disk_payload': False}, modes=M_PLAIN[:1]),
}


# ---------------------------------------------------------------------------------------------------------------
def tag_of(a):
    return f"{a.data}_s{a.small}_d768_b{a.batch}_q{a.queries}"


def run_id(a):
    return f"{a.variant}-{a.data}-{a.n}{a.tag}"


def get_ds():
    return PoolDataset(SYN_VEC, POOL)


def perm_rows(ds, a):
    rng = np.random.default_rng(123)
    perm = rng.permutation(ds.n_rows)
    return perm[:a.queries], perm[a.queries:a.queries + a.n]


def get_gt(ds, qrows, irows, a):
    path = f'{WORK}/gt_{a.data}_N{len(irows)}_Q{len(qrows)}.npz'
    if os.path.exists(path):
        z = np.load(path)
        return z['idx'], z['sc']
    log(f'computing exact ground truth: {len(qrows)} queries x {len(irows)} vectors')
    t0 = perf_counter()
    idx, sc = exact_topk(ds.mm, irows, ds.vectors(qrows), k=15)
    np.savez(path, idx=idx, sc=sc)
    log(f'  ground truth done in {perf_counter() - t0:.0f}s')
    return idx, sc


def _prebuild_one(args):
    i, a_dict = args
    a = argparse.Namespace(**a_dict)
    ds = get_ds()
    qrows, irows = perm_rows(ds, a)
    rows = irows[a.small:]
    chunk = rows[i * a.batch:(i + 1) * a.batch]
    if len(chunk) < a.batch:
        return 0
    path = body_cache_path(BODY_CACHE, tag_of(a), i)
    if os.path.exists(path):
        return 0
    body = build_batch_body(ds, chunk, 768)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'wb') as f:
        f.write(body)
    os.replace(path + '.tmp', path)
    return len(chunk)


def phase_prebuild(a):
    os.nice(19)
    ds = get_ds()
    qrows, irows = perm_rows(ds, a)
    get_gt(ds, qrows, irows, a)
    nb = (a.n - a.small) // a.batch
    t0 = perf_counter()
    with mp.Pool(a.procs) as p:
        done = sum(1 for _ in p.imap_unordered(_prebuild_one, [(i, vars(a)) for i in range(nb)]))
    log(f'prebuild: {nb} bulk bodies ready in {perf_counter() - t0:.0f}s (cache {BODY_CACHE}/{tag_of(a)})')


# ---------------------------------------------------------------------------------------------------------------
def state_path(a):
    return f'{RES}/{run_id(a)}.json'


def load_R(a):
    p = state_path(a)
    if os.path.exists(p):
        return json.load(open(p))
    return {'run': run_id(a), 'variant': a.variant, 'desc': VARIANTS[a.variant]['desc'], 'data': a.data, 'n': a.n,
            'small': a.small, 'batch': a.batch, 'queries': a.queries, 'mem_cap': a.mem, 'sessions': [],
            'ingested': 0, 'ingest_segments': [], 'cpu_s': {}}


def save_R(a, R):
    dump(state_path(a), R)


def mem_view(s):
    """compact RSS view in MB from a Lab.snapshot()"""
    g = lambda k: round(s.get(k, 0) / 1e6, 1)
    return {'RssAnon_MB': g('status.RssAnon'), 'RssFile_MB': g('status.RssFile'), 'VmHWM_MB': g('status.VmHWM'),
            'VmSwap_MB': g('status.VmSwap'), 'cg_current_MB': g('cgmem.current'), 'cg_anon_MB': g('cgmem.anon'),
            'cg_file_MB': g('cgmem.file'), 'cg_peak_MB': g('cgmem.peak'), 'load': s.get('loadavg')}


def telemetry_summary(qd):
    try:
        t = qd.ok('GET', '/telemetry?details_level=10')['result']
    except Exception as e:  # noqa
        return {'error': str(e)}
    out = {'segments': []}
    for c in t['collections']['collections']:
        for sh in c['shards']:
            for seg in sh.get('local', {}).get('segments', []):
                info = seg['info']
                vd = seg['config']['vector_data'].get('', {})
                out['segments'].append({
                    'type': info['segment_type'], 'points': info['num_points'], 'indexed': info['num_indexed_vectors'],
                    'vectors_size_bytes': info['vectors_size_bytes'], 'payloads_size_bytes': info['payloads_size_bytes'],
                    'storage_type': vd.get('storage_type'), 'index': vd.get('index', {}).get('type'),
                    'quantization': vd.get('quantization_config'), 'payload_storage': seg['config'].get('payload_storage_type'),
                    'appendable': info['is_appendable']})
    out['memory'] = t.get('memory')
    return out


def metrics_memory(qd):
    st, data, _ = qd.raw('GET', '/metrics')
    keep = {}
    for line in data.decode().splitlines():
        if line.startswith('memory_') or line.startswith('collections_vector_total') or line.startswith('collections_total'):
            k, _, v = line.partition(' ')
            keep[k] = v
    return keep


def collect_state(lab, qd, label):
    """RSS + smaps + jemalloc + telemetry + disk breakdown at one point in time."""
    s = lab.snapshot()
    files, tops = lab.disk()
    info = qd.info()
    return {'label': label, 'time': time.strftime('%H:%M:%S'), 'mem': mem_view(s), 'snap': s,
            'smaps_top': lab.smaps_top(), 'metrics': metrics_memory(qd), 'telemetry': telemetry_summary(qd),
            'disk': {'buckets': disk_summary(files), **tops, 'points': info['points_count'],
                     'segments': info['segments_count'], 'indexed_vectors': info['indexed_vectors_count']},
            'disk_big_files': sorted([(p, a_, al) for p, a_, al in files if al > 2_000_000], key=lambda x: -x[2])[:25],
            'docker_stats': lab.docker_stats()}


def wait_built(qd, n_expected, want_indexed_frac=None, timeout=3 * 3600, verbose=None):
    """green + optimizer ok for 5 polls; optionally also indexed_vectors >= frac * points."""
    t0 = perf_counter()
    ok, t_log = 0, t0
    while perf_counter() - t0 < timeout:
        info = qd.info()
        done = info['status'] == 'green' and info['optimizer_status'] == 'ok'
        if done and want_indexed_frac is not None:
            done = info['indexed_vectors_count'] >= want_indexed_frac * max(1, info['points_count'])
        ok = ok + 1 if done else 0
        if ok >= 5:
            return perf_counter() - t0, info
        if verbose and perf_counter() - t_log > 45:
            t_log = perf_counter()
            verbose(f"  building: status={info['status']} segments={info['segments_count']} "
                    f"indexed={info['indexed_vectors_count']}/{info['points_count']}")
        time.sleep(1.0)
    raise TimeoutError('build did not finish')


def merge_ingest(R, key, stats):
    if stats.get('points'):
        stats = dict(stats)
        stats['key'] = key
        stats['load_at_end'] = loadavg()
        R['ingest_segments'].append(stats)


# ---------------------------------------------------------------------------------------------------------------
def do_load(a, R, lab, ds, irows, sess):
    """create (if needed) + ingest + build + size/RAM snapshot; returns 0 done, 3 budget reached (re-run to continue)"""
    v = VARIANTS[a.variant]
    qd = lab.qd
    ctag = tag_of(a)
    s0 = lab.snapshot()
    deadline = perf_counter() + a.budget_min * 60
    if not collection_exists(qd):
        R['create_body'] = create_collection(qd, dim=768, create=v['create'], indexes=v.get('indexes', True))
        R['info_empty'] = qd.info()
        R['snap_empty'] = lab.snapshot()
        s0 = R['snap_empty']
    n_small = min(a.small, a.n)
    if R['ingested'] < n_small:
        st, nxt = ingest_range(qd, ds, irows, R['ingested'], n_small, mode='small', seed=1, deadline=deadline,
                               report_every=2000, tag='small')
        merge_ingest(R, 'small_into_empty', st)
        R['ingested'] = nxt
        if st.get('points'):
            log(f"  small(1-5/call): {st['points_per_s_server']:.0f} pts/s, {st['calls_per_s_server']:.0f} calls/s, "
                f"p50 {st['call_ms_p50']:.1f} ms p95 {st['call_ms_p95']:.1f} ms")
    if n_small <= R['ingested'] < a.n:
        st, nxt = ingest_range(qd, ds, irows, R['ingested'], a.n, mode='bulk', batch=a.batch, deadline=deadline,
                               cache_dir=BODY_CACHE, cache_tag=ctag, row_base=n_small, tag='bulk')
        merge_ingest(R, 'bulk', st)
        R['ingested'] = nxt
        if st.get('points'):
            log(f"  bulk({a.batch}/call): {st['points_per_s_server']:.0f} pts/s server-side "
                f"({st['points_per_s_total']:.0f} end-to-end), p50 {st['call_ms_p50']:.0f} ms")
    s1 = lab.snapshot()
    R['cpu_s'].setdefault('ingest_sessions', []).append(round((s1['cgcpu.usage_usec'] - s0['cgcpu.usage_usec']) / 1e6, 1))
    if R['ingested'] < a.n:
        sess['incomplete'] = True
        log(f"  budget reached at {R['ingested']}/{a.n} rows - re-run --phase load to continue")
        return 3
    # ---- after the last upsert: let the optimizer finish (build lag) / run the V3 bulk recipe
    t0 = perf_counter()
    s_b = lab.snapshot()
    if v.get('post_load') == 'bulk_recipe':
        t = {}
        tt = perf_counter()
        for f, sc in INDEXES:
            qd.ok('PUT', f'/collections/{COLL}/index?wait=true', {'field_name': f, 'field_schema': sc})
        t['create_4_payload_indexes_s'] = perf_counter() - tt
        R['info_before_threshold'] = qd.info()
        R['state_before_build'] = collect_state(lab, qd, 'before_build_all_plain')
        s_b = lab.snapshot()
        tt = perf_counter()
        qd.ok('PATCH', f'/collections/{COLL}', {'optimizers_config': {'indexing_threshold': 10000}})
        time.sleep(3)
        tg, info = wait_built(qd, a.n, want_indexed_frac=0.97, verbose=log)
        t['patch_threshold_to_green_s'] = perf_counter() - tt
        t['build_points_per_s'] = a.n / t['patch_threshold_to_green_s']
        R['bulk_recipe'] = t
        log(f"  bulk recipe: payload indexes {t['create_4_payload_indexes_s']:.1f}s; build {t['patch_threshold_to_green_s']:.0f}s "
            f"= {t['build_points_per_s']:.0f} pts/s")
    else:
        tg, info = wait_built(qd, a.n, verbose=log)
    s_a = lab.snapshot()
    R['tail_wait_after_last_upsert_s'] = round(perf_counter() - t0, 1)
    R['cpu_s']['build_tail_session'] = round((s_a['cgcpu.usage_usec'] - s_b['cgcpu.usage_usec']) / 1e6, 1)
    R['info_green'] = info
    log(f"  green {R['tail_wait_after_last_upsert_s']:.0f}s after the last upsert: points={info['points_count']} "
        f"indexed={info['indexed_vectors_count']} segments={info['segments_count']}")
    time.sleep(15)
    R['after_load'] = collect_state(lab, qd, 'after_load')
    m = R['after_load']['mem']
    d = R['after_load']['disk']
    log(f"  after load: RssAnon {m['RssAnon_MB']} MB, RssFile {m['RssFile_MB']} MB (HWM {m['VmHWM_MB']}), "
        f"disk allocated {d['storage_allocated'] / 1e6:.0f} MB = {d['storage_allocated'] / d['points']:.0f} B/pt")
    R['load_phase_done'] = True
    return 0


def wait_mem(lab, need_gb=7.0, max_wait_s=1800):
    t0 = perf_counter()
    while lab.free_gb() < need_gb and perf_counter() - t0 < max_wait_s:
        log(f'  host MemAvailable {lab.free_gb():.1f} GB < {need_gb} GB: waiting')
        time.sleep(60)


def finish(a, R, sess, lab, rc):
    sess['end'] = time.strftime('%H:%M:%S')
    sess['load_end'] = loadavg()
    R['sessions'].append(sess)
    try:
        save_R(a, R)
    finally:
        try:
            lab.stop()
        except Exception as e:  # noqa
            log(f'stop failed: {e}')
    log(f'saved {state_path(a)} (rc={rc})')
    return rc


# ---------------------------------------------------------------------------------------------------------------
def run_mode(lab, qv, mode, gt, filt, ks=(10, 15), n=None, passes=1):
    """passes=1: one pass (recall + a first latency sample); passes=2: second pass over the same queries (warm) for latency."""
    qd = lab.qd
    n = n or len(qv)
    bodies = query_bodies(qv[:n], params=mode['params'], filt=filt)
    s0 = lab.snapshot()
    latA, srvA, resA = run_queries(qd, bodies)
    s1 = lab.snapshot()
    res = resA
    d = {'mode': mode['name'], 'params': mode['params'], 'n_queries': n, 'passA': lat_stats(latA, srvA), 'passB': None,
         'passA_majflt_per_q': (s1['majflt'] - s0['majflt']) / n, 'passA_read_MB_per_q': (s1['io.read_bytes'] - s0['io.read_bytes']) / n / 1e6,
         'cpu_ms_per_q_passA': (s1['cgcpu.usage_usec'] - s0['cgcpu.usage_usec']) / n / 1e3}
    s2 = s1
    if passes >= 2:
        latB, srvB, resB = run_queries(qd, bodies)
        s2 = lab.snapshot()
        res = resB
        d['passB'] = lat_stats(latB, srvB)
        d['passB_majflt_per_q'] = (s2['majflt'] - s1['majflt']) / n
        d['cpu_ms_per_q_passB'] = (s2['cgcpu.usage_usec'] - s1['cgcpu.usage_usec']) / n / 1e3
    d['lat'] = d['passB'] or d['passA']
    d['load_before'], d['load_after'] = s0.get('loadavg'), s2.get('loadavg')
    d['load_ok'] = max(float(s0['loadavg'][0]), float(s2['loadavg'][0])) < LOAD_OK
    d.update(recall_at(res, gt[0][:n], gt[1][:n], ks=ks))
    d['_res_first'] = res[:50]
    return d, res


def score_exactness(ds, irows_set_vec_fn, qv, res, k=15, nq=50):
    """mean |returned score - exact cosine| over the top hits of nq queries (≈0 => scores come from original vectors)."""
    errs = []
    for q in range(min(nq, len(res))):
        rows = np.array([uuid_row(h[0]) for h in res[q][:k]])
        if not len(rows):
            continue
        V = ds.vectors(rows)
        V = V / np.linalg.norm(V, axis=1, keepdims=True)
        qn = qv[q] / np.linalg.norm(qv[q])
        exact = V @ qn
        got = np.array([h[1] for h in res[q][:k]])
        errs.append(float(np.abs(exact - got).mean()))
    return float(np.mean(errs)) if errs else None


def nomad_ensure(qd, coll=COLL):
    """What NOMAD's _ensureCollection() sends at the first use after every restart: 4 createPayloadIndex + is_empty backfill."""
    t = {}
    for f, sc in INDEXES:
        st, js, dt = qd.req('PUT', f'/collections/{coll}/index?wait=true', {'field_name': f, 'field_schema': sc})
        t[f'PUT_index_{f}_s'] = dt
    st, js, dt = qd.req('POST', f'/collections/{coll}/points/payload?wait=true',
                        {'payload': {'active': True}, 'filter': {'must': [{'is_empty': {'key': 'active'}}]}})
    t['setPayload_backfill_s'] = dt
    t['setPayload_status'] = st
    return t


def do_measure(a, R, lab, ds, qrows, irows, sess, timing_only=False):
    v = VARIANTS[a.variant]
    if not R.get('load_phase_done'):
        raise SystemExit('run --phase load first')
    gt = get_gt(ds, qrows, irows, a)
    qv = ds.vectors(qrows)
    key = 'timing' if timing_only else 'measure'
    M = R.setdefault(key, {})
    qd = lab.qd
    tg, info = wait_built(qd, a.n)
    M['ready_to_green_s'] = tg
    M['info_start'] = info
    time.sleep(5)
    if not timing_only:
        M['after_restart'] = collect_state(lab, qd, 'after_restart')
        m = M['after_restart']['mem']
        log(f"  after restart: RssAnon {m['RssAnon_MB']} MB, RssFile {m['RssFile_MB']} MB")
        # 200 queries -> RSS
        run_queries(qd, query_bodies(qv[:200]), keep=False)
        M['after_200_queries'] = {'mem': mem_view(lab.snapshot())}
    # ---- search modes: recall + latency (HNSW approximation and quantization both active)
    M['modes'] = []
    light = a.light or a.variant.startswith('E_')
    modes = v['modes'] if not timing_only else [m for m in v['modes'] if m['name'] in ('default', 'rescore_os2')]
    if light and not timing_only:
        modes = v['modes'][:1]
    for mode in modes:
        two = mode['name'] in ('default', 'rescore_os2') or timing_only
        d, res = run_mode(lab, qv, mode, gt, FILTER_V135, passes=2 if two else 1)
        if not timing_only and mode['name'] in ('default', 'rescore_os2', 'norescore', 'ignore_quant'):
            d['score_abs_err_vs_exact'] = score_exactness(ds, None, qv, res)
        d.pop('_res_first', None)
        M['modes'].append(d)
        L = d['lat']
        log(f"  {mode['name']:<13} recall@10={d['recall@10']:.4f} @15={d['recall@15']:.4f} "
            f"p50={L['p50_ms']:.1f} p95={L['p95_ms']:.1f} p99={L['p99_ms']:.1f} ms ({'warm 2nd pass' if two else 'single pass'}) "
            f"load={d['load_before'][0]}->{d['load_after'][0]} {'' if d['load_ok'] else 'PROVISIONAL'}"
            + (f" score_err={d.get('score_abs_err_vs_exact'):.2e}" if d.get('score_abs_err_vs_exact') is not None else ''))
    if not timing_only and not light:
        d, res = run_mode(lab, qv, {'name': 'default_taskfilter', 'params': None}, gt, FILTER_TASK)
        d.pop('_res_first', None)
        M['modes'].append(d)
        if a.variant in ('V0',):
            d, res = run_mode(lab, qv, {'name': 'exact_qdrant', 'params': {'exact': True}}, gt, FILTER_V135, n=100)
            d.pop('_res_first', None)
            M['modes'].append(d)
            log(f"  exact_qdrant(100q) recall@15={d['recall@15']:.4f} (validates the numpy ground truth)")
    if not timing_only:
        M['after_queries'] = {'mem': mem_view(lab.snapshot())}
    # ---- NOMAD ensure() cost (4 x createPayloadIndex + is_empty backfill) and its effect on RAM / index type
    if not timing_only and v.get('ensure_test') != 'skip':
        M['payload_schema_before_ensure'] = qd.info().get('payload_schema')
        M['nomad_ensure'] = nomad_ensure(qd)
        M['nomad_ensure_2nd'] = nomad_ensure(qd)
        time.sleep(5)
        tw, infoe = wait_built(qd, a.n)
        M['after_ensure'] = {'mem': mem_view(lab.snapshot()), 'wait_s': tw, 'payload_schema': infoe.get('payload_schema'),
                             'telemetry': telemetry_summary(qd)}
        log(f"  NOMAD ensure(): index PUTs {[round(M['nomad_ensure'][k], 3) for k in M['nomad_ensure'] if k.startswith('PUT')]} s, "
            f"backfill {M['nomad_ensure']['setPayload_backfill_s']:.2f}s; RssAnon after {M['after_ensure']['mem']['RssAnon_MB']} MB")
    sess['load_end'] = loadavg()
    M['done'] = True
    return 0


def do_steady(a, R, lab, ds, irows, sess, timing_only=False):
    """NOMAD-style single-section upserts (1-5 pts/call, wait=true) and bulk upserts of NEW ids into the loaded collection.
    Runs LAST because it adds duplicate vectors (recall would be distorted afterwards)."""
    key = 'timing' if timing_only else 'measure'
    M = R.setdefault(key, {})
    qd = lab.qd
    rows = irows[:min(a.n, a.steady_calls * 3)]
    l0 = loadavg()
    st, _ = ingest_range(qd, ds, rows, 0, len(rows), mode='small', seed=2, id_offset=10 ** 9, report_every=0,
                         deadline=perf_counter() + 240)
    st['load_before'], st['load_after'] = l0, loadavg()
    st['load_ok'] = max(float(st['load_before'][0]), float(st['load_after'][0])) < LOAD_OK
    M['steady_small'] = st
    log(f"  steady NOMAD-style upserts (1-5 pts/call, wait=true): {st['points_per_s_server']:.0f} pts/s "
        f"{st['calls_per_s_server']:.0f} calls/s p50 {st['call_ms_p50']:.1f} p95 {st['call_ms_p95']:.1f} ms")
    # bulk upserts of NEW ids on the loaded collection (insert path)
    l0 = loadavg()
    rows2 = irows[:min(a.n, 10 * a.batch)]
    st, _ = ingest_range(qd, ds, rows2, 0, len(rows2), mode='bulk', batch=a.batch, id_offset=2 * 10 ** 9, report_every=0,
                         deadline=perf_counter() + 240)
    st['load_before'], st['load_after'] = l0, loadavg()
    st['load_ok'] = max(float(st['load_before'][0]), float(st['load_after'][0])) < LOAD_OK
    M['steady_bulk'] = st
    log(f"  bulk upserts into the loaded collection ({a.batch}/call): {st['points_per_s_server']:.0f} pts/s p50 {st['call_ms_p50']:.0f} ms")
    wait_built(qd, a.n)
    if not timing_only:
        M['after_steady'] = collect_state(lab, qd, 'after_steady_upserts')
    M['steady_done'] = True
    return 0


def run_session(a, steps):
    """ONE container / lock hold for `steps` in order. steps: load, restart, measure, timing, cold:<mem>."""
    ds = get_ds()
    qrows, irows = perm_rows(ds, a)
    assert len(irows) == a.n
    R = load_R(a)
    lab = Lab(run_id(a).replace('.', '-'), mem=a.mem)
    sess = {'phase': '+'.join(steps), 'start': time.strftime('%H:%M:%S'), 'load_start': loadavg()}
    rc = 0
    try:
        wait_mem(lab)
        sess['t_start_to_ready_s'] = lab.start(session=True)
        sess['lock_wait_s'] = lab.t_lock_wait
        sess['load_at_lock'] = loadavg()
        for st in steps:
            if st == 'load':
                rc = do_load(a, R, lab, ds, irows, sess)
                if rc:
                    break
            elif st == 'restart':
                sess['restart'] = lab.restart()
                log(f"  restarted: shutdown {sess['restart']['shutdown_s']:.1f}s, start->ready {sess['restart']['start_to_ready_s']:.1f}s")
            elif st in ('measure', 'timing'):
                rc = do_measure(a, R, lab, ds, qrows, irows, sess, timing_only=(st == 'timing')) or 0
                if rc:
                    break
                if st == 'timing':
                    rc = do_steady(a, R, lab, ds, irows, sess, timing_only=True)
            elif st == 'steady':
                rc = do_steady(a, R, lab, ds, irows, sess)
            elif st.startswith('cold:'):
                rc = do_cold(a, R, lab, ds, qrows, irows, st.split(':', 1)[1])
            else:
                raise ValueError(st)
        sess['load_end'] = loadavg()
    except Exception:
        import traceback
        sess['error'] = traceback.format_exc()
        log('ERROR ' + sess['error'])
        rc = 1
    return finish(a, R, sess, lab, rc=rc)


def do_cold(a, R, lab, ds, qrows, irows, mem):
    """restart with a smaller memory cap (collection no longer fits in page cache), run the default (+rescore_os2) queries."""
    v = VARIANTS[a.variant]
    gt = get_gt(ds, qrows, irows, a)
    qv = ds.vectors(qrows)
    C = R.setdefault('cold', {})
    r = lab.restart(mem=mem)
    qd = lab.qd
    tg, info = wait_built(qd, a.n)
    c = {'mem_cap': mem, **r, 'ready_to_green_s': tg, 'after_restart': mem_view(lab.snapshot()), 'modes': []}
    for mode in [m for m in v['modes'] if m['name'] in ('default', 'rescore_os2')]:
        d, res = run_mode(lab, qv, mode, gt, FILTER_V135, passes=2)
        d.pop('_res_first', None)
        c['modes'].append(d)
        log(f"  cold[{mem}] {mode['name']:<12} recall@15={d['recall@15']:.4f} passA p50/p95={d['passA']['p50_ms']:.0f}/{d['passA']['p95_ms']:.0f} "
            f"passB p50/p95={d['passB']['p50_ms']:.0f}/{d['passB']['p95_ms']:.0f} ms majflt/q A={d['passA_majflt_per_q']:.1f} B={d['passB_majflt_per_q']:.1f} "
            f"read {d['passA_read_MB_per_q']:.2f} MB/q load {d['load_before'][0]}->{d['load_after'][0]} (PROVISIONAL if load>=8)")
    c['end'] = mem_view(lab.snapshot())
    C[mem] = c
    lab.restart(mem=a.mem)  # back to the main cap
    return 0


def phase_load(a):
    return run_session(a, ['load'])


def phase_all(a):
    return run_session(a, ['load', 'restart', 'measure'] + [f'cold:{m}' for m in a.cold.split(',') if m] + (['steady'] if a.steady else []))


def phase_measure(a, timing_only=False):
    if timing_only:
        l1 = float(loadavg()[0])
        if l1 >= LOAD_OK and not a.force:
            log(f'host 1-min load {l1} >= {LOAD_OK}: refusing timing run (use --force to record PROVISIONAL numbers)')
            return 4
    return run_session(a, ['timing'] if timing_only else ['measure'])



def phase_final(a):
    lab = Lab(run_id(a).replace('.', '-'), mem=a.mem)
    lab.rmstorage()
    log(f'removed scratch storage of {run_id(a)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', required=True)
    ap.add_argument('--phase', required=True, choices=['prebuild', 'load', 'measure', 'timing', 'all', 'final'])
    ap.add_argument('--data', default='syn')
    ap.add_argument('--n', type=int, default=100000)
    ap.add_argument('--queries', type=int, default=500)
    ap.add_argument('--small', type=int, default=6000)
    ap.add_argument('--batch', type=int, default=1000)
    ap.add_argument('--mem', default='4g')
    ap.add_argument('--steady-calls', type=int, default=1000)
    ap.add_argument('--budget-min', type=float, default=11.0)
    ap.add_argument('--procs', type=int, default=3)
    ap.add_argument('--tag', default='')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--light', action='store_true', help='measure: only the default search mode (extras / RAM-only runs)')
    ap.add_argument('--steady', action='store_true', help='--phase all: also run the steady-state upsert timing step (normally deferred to the quiet window)')
    ap.add_argument('--cold', default='', help='comma list of memory caps for cold passes in --phase all, e.g. 700m')
    a = ap.parse_args()
    if a.phase != 'prebuild':
        os.nice(15)
    if VARIANTS[a.variant].get('id_mode'):
        ID_MODE['mode'] = VARIANTS[a.variant]['id_mode']
    return {'prebuild': lambda: phase_prebuild(a), 'load': lambda: phase_load(a), 'measure': lambda: phase_measure(a),
            'timing': lambda: phase_measure(a, timing_only=True), 'all': lambda: phase_all(a),
            'final': lambda: phase_final(a)}[a.phase]() or 0


if __name__ == '__main__':
    sys.exit(main())
