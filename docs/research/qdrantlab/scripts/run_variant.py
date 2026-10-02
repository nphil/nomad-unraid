#!/usr/bin/env python3
"""Run ONE Qdrant layout variant end to end on a throw-away container and write results/<run>.json.

Steps: start container -> create collection (NOMAD call + variant knobs) -> ingest (NOMAD-style small upserts first,
then bulk) -> wait optimizers -> measure disk/RSS/telemetry -> warm queries (latency + recall vs exact numpy
brute force) -> steady-state small upserts -> optional restart passes with capped memory (cold-ish) -> cleanup.
"""
import argparse
import json
import os
import sys
import time
from time import perf_counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlab import *  # noqa

Q_INT8 = {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}
Q_BIN = {'binary': {'always_ram': True}}
Q_BIN2 = {'binary': {'always_ram': True, 'encoding': 'two_bits', 'query_encoding': 'scalar8bits'}}
DISKV = {'vectors': {'on_disk': True}}


def qq(**kw):
    return {'quantization': kw}


MODES_PLAIN = [{'name': 'default', 'params': None}, {'name': 'hnsw_ef256', 'params': {'hnsw_ef': 256}}]
MODES_QUANT = [
    {'name': 'default', 'params': None},  # what NOMAD sends today (no search params)
    {'name': 'norescore', 'params': qq(rescore=False)},
    {'name': 'rescore_os1', 'params': qq(rescore=True, oversampling=1.0)},
    {'name': 'rescore_os2', 'params': qq(rescore=True, oversampling=2.0)},
    {'name': 'rescore_os3', 'params': qq(rescore=True, oversampling=3.0)},
    {'name': 'rescore_os4', 'params': qq(rescore=True, oversampling=4.0)},
    {'name': 'rescore_os5', 'params': qq(rescore=True, oversampling=5.0)},
]


def mrl(d, extra=None, quant=None, disk=False):
    c = {'vectors': {}}
    if disk:
        c['vectors']['on_disk'] = True
    if quant:
        c['quantization_config'] = quant
    if extra:
        c.update(extra)
    return c


VARIANTS = {
    # (a) baseline = exactly what NOMAD v1.35.0 does: createCollection({vectors:{size,distance}}) + 4 payload indexes
    'baseline': dict(create={}, modes=MODES_PLAIN),
    # (g) the 4 payload indexes alone: same as baseline without createPayloadIndex
    'noidx': dict(create={}, indexes=False, modes=MODES_PLAIN[:1]),
    # (f) payload kept in RAM instead of on disk
    'payload_ram': dict(create={'on_disk_payload': False}, modes=MODES_PLAIN[:1]),
    # (b) scalar int8, quantised copy always in RAM, originals on disk
    'int8': dict(create={**DISKV, 'quantization_config': Q_INT8}, modes=MODES_QUANT),
    # (c) binary quantisation (1 bit/dim), quantised copy in RAM, originals on disk
    'bin': dict(create={**DISKV, 'quantization_config': Q_BIN}, modes=MODES_QUANT),
    'bin2bit': dict(create={**DISKV, 'quantization_config': Q_BIN2}, modes=MODES_QUANT),
    # (e) smaller / on-disk HNSW graph
    'm8': dict(create={'hnsw_config': {'m': 8, 'ef_construct': 64}}, modes=MODES_PLAIN),
    'hnsw_disk': dict(create={'hnsw_config': {'on_disk': True}}, modes=MODES_PLAIN[:1]),
    # extra: float16 storage of the vectors (halves vector bytes, no rescoring logic needed)
    'f16': dict(create={'vectors': {'datatype': 'float16'}}, modes=MODES_PLAIN),
    'f16_m8': dict(create={'vectors': {'datatype': 'float16'}, 'hnsw_config': {'m': 8, 'ef_construct': 64}}, modes=MODES_PLAIN[:1]),
    # compact layouts (quantised vectors in RAM; originals, graph and payload on disk)
    'compact_int8': dict(create={**DISKV, 'quantization_config': Q_INT8, 'hnsw_config': {'on_disk': True}}, modes=MODES_QUANT),
    'compact_int8_m8': dict(create={**DISKV, 'quantization_config': Q_INT8, 'hnsw_config': {'m': 8, 'ef_construct': 64}}, modes=MODES_QUANT),
    'compact_bin': dict(create={**DISKV, 'quantization_config': Q_BIN, 'hnsw_config': {'on_disk': True}}, modes=MODES_QUANT),
}
# --- anon-RAM investigation (request from NomadIndexAgent): production sits in a 'plain segment' state ---------
IDX_ONDISK = {'source': {'type': 'keyword', 'on_disk': True}, 'content_type': {'type': 'keyword', 'on_disk': True},
              'collection': {'type': 'keyword', 'on_disk': True}, 'active': {'type': 'bool', 'on_disk': True}}
NOIDX_PLAIN = {'optimizers_config': {'indexing_threshold': 0}}  # 0 = never build HNSW => stays one plain segment
VARIANTS.update({
    'plain': dict(create=NOIDX_PLAIN, modes=MODES_PLAIN[:1], unstick=True),
    'plain_noidx': dict(create=NOIDX_PLAIN, indexes=False, modes=MODES_PLAIN[:1]),
    'idx_ondisk': dict(create={}, indexes=IDX_ONDISK, modes=MODES_PLAIN[:1]),
    'plain_idx_ondisk': dict(create=NOIDX_PLAIN, indexes=IDX_ONDISK, modes=MODES_PLAIN[:1]),
    'intid': dict(create={}, id_mode='int', modes=MODES_PLAIN[:1]),
    'int8_ramfalse': dict(create={**DISKV, 'quantization_config': {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': False}}},
                          modes=MODES_QUANT[:1] + MODES_QUANT[3:5]),
})
# (d) Matryoshka truncation: dimension changes -> needs a new collection (NOMAD hard-codes 768)
for _d in (512, 384, 256, 128):
    VARIANTS[f'mrl{_d}'] = dict(dim=_d, create={}, modes=MODES_PLAIN)
    VARIANTS[f'mrl{_d}_int8'] = dict(dim=_d, create={**DISKV, 'quantization_config': Q_INT8}, modes=MODES_QUANT)
    VARIANTS[f'mrl{_d}_bin'] = dict(dim=_d, create={**DISKV, 'quantization_config': Q_BIN}, modes=MODES_QUANT)
    VARIANTS[f'mrl{_d}_int8ram'] = dict(dim=_d, create={'quantization_config': Q_INT8}, modes=MODES_QUANT[:1] + MODES_QUANT[3:5])


def get_dataset(a):
    if a.data == 'syn':
        return Dataset('/tmp/qlab-work/syn_vectors.f32', '/tmp/qlab-work/syn_chunks.jsonl')
    if a.data == 'test':
        return Dataset('/tmp/qlab-work/test_vectors.f32', '/tmp/qlab-work/test_chunks.jsonl')
    return Dataset(a.vec, a.chunks)


def get_gt(a, ds, irows, qrows):
    path = f'{WORK}/gt_{a.data}_N{len(irows)}_Q{len(qrows)}.npz'
    if os.path.exists(path):
        z = np.load(path)
        return z['idx'], z['sc']
    log(f'computing exact ground truth ({len(qrows)} queries x {len(irows)} vectors)')
    t0 = perf_counter()
    qv = ds.vectors(qrows)
    idx, sc = exact_topk(ds.mm, irows, qv, k=15)
    np.savez(path, idx=idx, sc=sc)
    log(f'  ground truth done in {perf_counter() - t0:.0f}s')
    return idx, sc


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
                    'ram_usage_bytes': info.get('ram_usage_bytes'), 'disk_usage_bytes': info.get('disk_usage_bytes'),
                    'storage_type': vd.get('storage_type'), 'index': vd.get('index', {}).get('type'),
                    'quantization': vd.get('quantization_config'), 'payload_storage': seg['config'].get('payload_storage_type'),
                    'appendable': info['is_appendable']})
    out['memory'] = t.get('memory')
    out['hardware'] = t.get('hardware')
    return out


def metrics_memory(qd):
    st, data, _ = qd.raw('GET', '/metrics')
    keep = {}
    for line in data.decode().splitlines():
        if line.startswith('memory_') or line.startswith('collections_') or line.startswith('app_status'):
            k, _, v = line.partition(' ')
            keep[k] = v
    return keep


def drop_file_cache(lab):
    """Evict this run's files from the host page cache (POSIX_FADV_DONTNEED via dd iflag=nocache); does NOT touch
    anything outside the run's own storage dir (no global drop_caches)."""
    ssh(f"find {lab.storage} -type f -exec dd if={{}} of=/dev/null iflag=nocache count=0 status=none \\; ; true", timeout=900)


def delta(s0, s1, key):
    return s1.get(key, 0) - s0.get(key, 0)


def run_mode(lab, qv, mode, gt, filt, ks=(10, 15), subset=None, tag='warm'):
    qd = lab.qd
    n = len(qv) if not subset else subset
    bodies = query_bodies(qv[:n], params=mode['params'], filt=filt)
    s0 = lab.snapshot()
    latA, srvA, resA = run_queries(qd, bodies)
    s1 = lab.snapshot()
    latB, srvB, resB = run_queries(qd, bodies)
    s2 = lab.snapshot()
    d = {'mode': mode['name'], 'params': mode['params'], 'n_queries': n,
         'passA': lat_stats(latA, srvA), 'passB': lat_stats(latB, srvB),
         'passA_majflt_per_q': (s1['majflt'] - s0['majflt']) / n,
         'passA_read_MB_per_q': (s1['io.read_bytes'] - s0['io.read_bytes']) / n / 1e6,
         'passB_majflt_per_q': (s2['majflt'] - s1['majflt']) / n,
         'passB_read_MB_per_q': (s2['io.read_bytes'] - s1['io.read_bytes']) / n / 1e6,
         'cpu_ms_per_q_passB': (s2['cgcpu.usage_usec'] - s1['cgcpu.usage_usec']) / n / 1e3,
         'cpu_user_ms_per_q_passB': (s2['cgcpu.user_usec'] - s1['cgcpu.user_usec']) / n / 1e3,
         'load_before': s0.get('loadavg'), 'load_after': s2.get('loadavg')}
    d.update(recall_at(resB, gt[0][:n], gt[1][:n], ks=ks))
    d['rss_after_MB'] = s2['status.VmRSS'] / 1e6
    return d, s2


def nomad_ensure(qd, coll=COLL):
    """What NOMAD's _ensureCollection() sends at every (re)start of a job: 4 createPayloadIndex + the is_empty backfill."""
    t = {}
    for f, sc in (('source', 'keyword'), ('content_type', 'keyword'), ('collection', 'keyword'), ('active', 'bool')):
        st, js, dt = qd.req('PUT', f'/collections/{coll}/index?wait=true', {'field_name': f, 'field_schema': sc})
        t[f'PUT_index_{f}_s'] = dt
    st, js, dt = qd.req('POST', f'/collections/{coll}/points/payload?wait=true',
                        {'payload': {'active': True}, 'filter': {'must': [{'is_empty': {'key': 'active'}}]}})
    t['setPayload_backfill_s'] = dt
    t['setPayload_status'] = st
    return t


def unstick(lab, R, v):
    """Plain (never indexed) collection -> enable indexing: what un-sticking production's optimizer would trigger."""
    qd = lab.qd
    snap_before = lab.snapshot()
    files, tops = lab.disk()
    R['unstick'] = {'before': {'snap': snap_before, **tops, 'buckets': disk_summary(files)}}
    body = {'optimizers_config': {'indexing_threshold': 10000}}
    t0 = perf_counter()
    R['unstick']['patch'] = {'body': body, 'response': qd.req('PATCH', f'/collections/{COLL}', body)[1]}
    series = []
    last_info = None
    while True:
        info = qd.info()
        sn = lab.snapshot()
        _, tops = lab.disk()
        series.append({'t': perf_counter() - t0, 'status': info['status'], 'segments': info['segments_count'],
                       'indexed': info['indexed_vectors_count'], 'rss_anon': sn['status.RssAnon'],
                       'rss_file': sn['status.RssFile'], 'hwm': sn['status.VmHWM'], 'cg_current': sn['cgmem.current'],
                       'storage_allocated': tops['storage_allocated'], 'storage_apparent': tops['storage_apparent'],
                       'cpu_usec': sn['cgcpu.usage_usec']})
        if info['status'] == 'green' and info['optimizer_status'] == 'ok' and len(series) > 2 and info['indexed_vectors_count'] > 0:
            break
        if perf_counter() - t0 > 3 * 3600:
            break
        time.sleep(4)
    R['unstick']['series'] = series
    R['unstick']['seconds'] = perf_counter() - t0
    time.sleep(15)
    snap_after = lab.snapshot()
    files, tops = lab.disk()
    R['unstick']['after'] = {'snap': snap_after, **tops, 'buckets': disk_summary(files),
                             'info': qd.info(), 'smaps': lab.smaps_top()}
    R['unstick']['peak_storage_allocated'] = max(x['storage_allocated'] for x in series)
    R['unstick']['peak_rss_anon'] = max(x['rss_anon'] for x in series)
    R['unstick']['peak_hwm'] = max(x['hwm'] for x in series)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--variant', required=True)
    ap.add_argument('--data', default='syn')
    ap.add_argument('--vec')
    ap.add_argument('--chunks')
    ap.add_argument('--n', type=int, default=200000)
    ap.add_argument('--queries', type=int, default=1000)
    ap.add_argument('--mem', default='4g')
    ap.add_argument('--small', type=int, default=6000, help='points ingested NOMAD-style (1-5 per call) first')
    ap.add_argument('--batch', type=int, default=500)
    ap.add_argument('--steady-calls', type=int, default=1500)
    ap.add_argument('--cold', default='', help='comma list of memory caps for restart+cold passes, e.g. 4g,1g')
    ap.add_argument('--keep', action='store_true')
    ap.add_argument('--no-taskfilter', action='store_true')
    ap.add_argument('--tag', default='')
    ap.add_argument('--q-use', type=int, default=0, help='run only the first K of the queries (slow plain scans)')
    ap.add_argument('--unstick', action='store_true', help='after everything: enable indexing (plain variants) and trace it')
    a = ap.parse_args()
    os.nice(15)  # all local heavy work is low priority (Main's directive)
    if VARIANTS[a.variant].get('id_mode'):
        ID_MODE['mode'] = VARIANTS[a.variant]['id_mode']

    v = VARIANTS[a.variant]
    dim = v.get('dim', DIM)
    run_id = f'{a.variant}.{a.data}.{a.n}{a.tag}'
    out_path = f'{RES}/{run_id}.json'
    log(f'=== {run_id}  dim={dim} mem={a.mem}')
    R = {'run': run_id, 'variant': a.variant, 'data': a.data, 'n': a.n, 'dim': dim, 'mem_cap': a.mem,
         'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'load_start': loadavg()}

    ds = get_dataset(a)
    rng = np.random.default_rng(123)
    perm = rng.permutation(ds.n_rows)
    Qn = a.queries
    qrows, irows = perm[:Qn], perm[Qn:Qn + a.n]
    assert len(irows) == a.n, f'dataset has only {ds.n_rows} rows'
    gt = get_gt(a, ds, irows, qrows)
    qv = ds.vectors(qrows, dim)
    if a.q_use:
        qv, gt = qv[:a.q_use], (gt[0][:a.q_use], gt[1][:a.q_use])
    R['dataset'] = {'rows': int(ds.n_rows), 'chunks': ds.chunks_path}

    lab = Lab(run_id.replace('.', '-'), mem=a.mem)
    while lab.free_gb() < 10:
        log('waiting: host MemAvailable < 10 GB')
        time.sleep(60)
    R['host_free_gb_at_start'] = lab.free_gb()
    try:
        R['t_start_to_ready_s'] = lab.start()
        qd = lab.qd
        R['qdrant_root'] = qd.ok('GET', '/')
        R['create_body'] = create_collection(qd, dim=dim, create=v['create'], indexes=v.get('indexes', True))
        R['info_empty'] = qd.info()
        snap0 = lab.snapshot()
        R['snap_empty'] = snap0

        # ---- ingest: NOMAD-style small upserts first, then bulk
        n_small = min(a.small, a.n)
        R['ingest'] = {}
        if n_small:
            R['ingest']['small_empty'] = ingest(qd, ds, irows[:n_small], dim=dim, mode='small', seed=1, tag='small')
            log(f"  small: {R['ingest']['small_empty']['points_per_s_server']:.0f} pts/s server-side, "
                f"p50 {R['ingest']['small_empty']['call_ms_p50']:.1f} ms")
        R['ingest']['bulk'] = ingest(qd, ds, irows[n_small:], dim=dim, mode='bulk', batch=a.batch, tag='bulk',
                                     cache_dir='/tmp/qlab-work/bodies',
                                     cache_tag=f"{a.data}_N{a.n}_s{n_small}_d{dim}_b{a.batch}_{ID_MODE['mode']}")
        log(f"  bulk: {R['ingest']['bulk']['points_per_s_server']:.0f} pts/s server-side "
            f"({R['ingest']['bulk']['points_per_s_total']:.0f} end-to-end)")
        snap_b = lab.snapshot()
        R['snap_after_ingest'] = snap_b
        tg, info = wait_green(qd, verbose=log)
        R['optimizer_wait_after_last_upsert_s'] = tg
        R['info_green'] = info
        log(f'  optimizers done {tg:.0f}s after last upsert; points={info["points_count"]} indexed={info["indexed_vectors_count"]} segments={info["segments_count"]}')
        time.sleep(15)  # let flush_interval (5 s) + mmap flushes settle
        snap_c = lab.snapshot()
        R['snap_loaded'] = snap_c
        R['cpu_usec_build'] = snap_c['cgcpu.usage_usec'] - snap0['cgcpu.usage_usec']
        R['docker_stats_loaded'] = lab.docker_stats()
        files, tops = lab.disk()
        R['disk'] = {'buckets': disk_summary(files), **tops,
                     'points': info['points_count']}
        R['disk_files'] = [(p, a_, al) for p, a_, al in files if a_ > 1_000_000]  # big files only (full list is huge)
        R['telemetry'] = telemetry_summary(qd)
        R['metrics_mem'] = metrics_memory(qd)
        R['smaps_loaded'] = lab.smaps_top()

        # ---- warm queries
        warm = run_queries(qd, query_bodies(qv[:200]), keep=False)  # first 200 queries (task: RSS after 200 queries)
        R['snap_after_200_queries'] = lab.snapshot()
        R['lat_first200'] = lat_stats(warm[0])
        R['modes'] = []
        for mode in v['modes']:
            r, s = run_mode(lab, qv, mode, gt, FILTER_V135)
            R['modes'].append(r)
            log(f"  mode {mode['name']:<13} recall@10={r['recall@10']:.4f} @15={r['recall@15']:.4f} "
                f"p50={r['passB']['p50_ms']:.1f} p95={r['passB']['p95_ms']:.1f} p99={r['passB']['p99_ms']:.1f} ms "
                f"cpu={r['cpu_ms_per_q_passB']:.1f} ms/q (passA p95 {r['passA']['p95_ms']:.1f}; majflt/q {r['passA_majflt_per_q']:.1f})")
        if not a.no_taskfilter:
            r, s = run_mode(lab, qv, {'name': 'default_taskfilter', 'params': None}, gt, FILTER_TASK)
            R['modes'].append(r)
            log(f"  mode default_taskfilter p50={r['passB']['p50_ms']:.1f} p95={r['passB']['p95_ms']:.1f}")
        if a.variant == 'baseline':
            r, s = run_mode(lab, qv, {'name': 'exact_qdrant', 'params': {'exact': True}}, gt, FILTER_V135, subset=100)
            R['modes'].append(r)
            log(f"  mode exact_qdrant (100 q) recall@10={r['recall@10']:.4f} (validates numpy ground truth) p50={r['passB']['p50_ms']:.0f}ms")
        R['snap_after_queries'] = lab.snapshot()
        R['smaps_after_queries'] = lab.smaps_top()
        R['docker_stats_after_queries'] = lab.docker_stats()

        # ---- restart passes with capped memory (cold-ish): fresh process, page cache of this run's files evicted
        R['cold'] = []
        for cap in [c for c in a.cold.split(',') if c]:
            stop_s = lab.stop()
            drop_file_cache(lab)
            lab.mem = cap
            t_ready = lab.start()
            c = {'mem_cap': cap, 'shutdown_s': stop_s, 'start_to_ready_s': t_ready}
            tgc, infoc = wait_green(lab.qd, stable=2)
            c['ready_to_green_s'] = tgc
            c['points_after_restart'] = infoc['points_count']
            c['segments_after_restart'] = infoc['segments_count']
            c['snap_after_restart'] = lab.snapshot()
            c['smaps_after_restart'] = lab.smaps_top()
            modes = [m for m in v['modes'] if m['name'] in ('default', 'rescore_os3')]
            c['modes'] = []
            for mode in modes:
                r, s = run_mode(lab, qv, mode, gt, FILTER_V135)
                c['modes'].append(r)
                log(f"  cold[{cap}] {mode['name']:<12} recall@10={r['recall@10']:.4f} passA p50/p95={r['passA']['p50_ms']:.0f}/{r['passA']['p95_ms']:.0f} "
                    f"passB p50/p95={r['passB']['p50_ms']:.0f}/{r['passB']['p95_ms']:.0f} ms majflt/q A={r['passA_majflt_per_q']:.1f} B={r['passB_majflt_per_q']:.1f}")
            c['snap_end'] = lab.snapshot()
            R['cold'].append(c)

        # ---- final: main memory cap again -> NOMAD ensure() cost, steady-state small upserts (new ids), optional unstick
        if R['cold']:
            lab.stop()
            lab.mem = a.mem
            lab.start()
            wait_green(lab.qd, stable=2)
            R['snap_restart_main_cap'] = lab.snapshot()
            R['smaps_restart_main_cap'] = lab.smaps_top()
        qd = lab.qd
        R['nomad_ensure'] = nomad_ensure(qd)
        R['nomad_ensure_2nd'] = nomad_ensure(qd)
        log(f"  NOMAD ensure(): index PUTs {[round(R['nomad_ensure'][k], 3) for k in R['nomad_ensure'] if k.startswith('PUT')]} s, "
            f"setPayload backfill {R['nomad_ensure']['setPayload_backfill_s']:.2f} s")
        steady_rows = irows[:min(a.n, a.steady_calls * 3)]
        R['ingest']['small_steady'] = ingest(qd, ds, steady_rows, dim=dim, mode='small', seed=2, id_offset=10**9,
                                              tag='steady', report_every=0)
        log(f"  steady small upserts: {R['ingest']['small_steady']['calls_per_s_server']:.1f} calls/s, "
            f"p50 {R['ingest']['small_steady']['call_ms_p50']:.1f} ms p95 {R['ingest']['small_steady']['call_ms_p95']:.1f} ms")
        tg2, info2 = wait_green(qd)
        R['info_after_steady'] = info2
        R['snap_after_steady'] = lab.snapshot()
        R['log_warnings'] = [l for l in ssh(f'docker logs {lab.name} 2>&1 | grep -E "WARN|ERROR" | head -20').splitlines()]
        if a.unstick:
            unstick(lab, R, v)
        R['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
        R['load_end'] = loadavg()
        R['status'] = 'ok'
    except Exception as e:  # noqa
        import traceback
        R['status'] = 'error'
        R['error'] = traceback.format_exc()
        log('ERROR: ' + R['error'])
    finally:
        dump(out_path, R)
        try:
            lab.stop()
        except Exception as e:  # noqa
            log(f'stop failed: {e}')
        if not a.keep:
            try:
                lab.rmstorage()
            except Exception as e:  # noqa
                log(f'rmstorage failed: {e}')
    log(f'wrote {out_path}  status={R["status"]}')
    return 0 if R['status'] == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
