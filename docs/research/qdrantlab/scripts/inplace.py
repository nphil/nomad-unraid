#!/usr/bin/env python3
"""inplace.py - prove that a collection created with NOMAD's defaults can be switched to compact settings IN PLACE
(PATCH /collections/{name}, no re-embedding), and document what a restart does to leftovers.

One lock-held Qdrant session (<= ~12 min):
  1. build the 100k-point V0 (NOMAD defaults) collection exactly like run_v.py V0 (NOMAD-style small upserts, then bulk)
  2. start a background query thread (NOMAD search shape, default params) that runs during everything below
  3. PATCH to the compact layout (--patch v1: int8 always_ram + originals on disk), trace status/segments/disk/RAM until green
  4. recall vs exact before/after, restart (graceful), restart with fake leftover `*.deleted` + `temp_segments` dirs,
     crash (SIGKILL) in the middle of a second rebuild, restart again; record what Qdrant logs/does
usage: inplace.py --n 100000 [--patch v1|v2]
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
from time import perf_counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qlab  # noqa
from qlab import *  # noqa
import run_v as rv  # noqa

PATCHES = {
    'v1': {'vectors': {'': {'on_disk': True}},
           'quantization_config': {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}},
    'v2': {'vectors': {'': {'on_disk': True}}, 'hnsw_config': {'on_disk': True},
           'quantization_config': {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}},
}


def du(lab):
    return int(ssh(f"du -s --block-size=1 {lab.storage} | cut -f1").strip())


class Bg:
    """background NOMAD-shaped searches; records (t, latency, http status, n results)."""

    def __init__(self, bodies, t0):
        self.bodies, self.t0, self.samples, self.stop_flag = bodies, t0, [], False
        self.th = threading.Thread(target=self.run, daemon=True)

    def run(self):
        qd = Qd()
        i = 0
        while not self.stop_flag:
            t = perf_counter()
            try:
                st, data, dt = qd.raw('POST', f'/collections/{COLL}/points/search', self.bodies[i % len(self.bodies)])
                n = len(json.loads(data).get('result', [])) if st == 200 else -1
                self.samples.append((t - self.t0, dt, st, n))
            except Exception as e:  # noqa
                self.samples.append((t - self.t0, None, -1, -1))
                qd.conn = None
            i += 1
            time.sleep(0.05)

    def start(self):
        self.th.start()

    def stop(self):
        self.stop_flag = True
        self.th.join(timeout=30)

    def summary(self, t_from=None, t_to=None):
        s = [x for x in self.samples if (t_from is None or x[0] >= t_from) and (t_to is None or x[0] <= t_to)]
        ok = [x for x in s if x[2] == 200 and x[1] is not None]
        lat = np.array([x[1] for x in ok]) if ok else np.array([0.0])
        return {'queries': len(s), 'ok': len(ok), 'errors': len(s) - len(ok),
                'empty_results': sum(1 for x in ok if x[3] == 0),
                'p50_ms': float(np.percentile(lat, 50) * 1e3), 'p95_ms': float(np.percentile(lat, 95) * 1e3),
                'p99_ms': float(np.percentile(lat, 99) * 1e3), 'max_ms': float(lat.max() * 1e3)}


def trace_until_green(lab, qd, t0, label, min_seen=30, timeout=1500, poll=2.0):
    series, saw_busy = [], False
    ok = 0
    while True:
        info = qd.info()
        sn = lab.snapshot()
        series.append({'t': round(perf_counter() - t0, 1), 'status': info['status'], 'optimizer': str(info['optimizer_status'])[:60],
                       'segments': info['segments_count'], 'indexed': info['indexed_vectors_count'], 'points': info['points_count'],
                       'du_alloc_MB': round(du(lab) / 1e6, 1), 'anon_MB': round(sn['status.RssAnon'] / 1e6, 1),
                       'file_MB': round(sn['status.RssFile'] / 1e6, 1), 'cg_MB': round(sn['cgmem.current'] / 1e6, 1),
                       'cpu_s': round(sn['cgcpu.usage_usec'] / 1e6, 1), 'load1': sn['loadavg'][0]})
        busy = info['status'] != 'green' or info['optimizer_status'] != 'ok'
        saw_busy = saw_busy or busy
        if not busy and (saw_busy or perf_counter() - t0 > min_seen):
            ok += 1
            if ok >= 3:
                break
        else:
            ok = 0
        if perf_counter() - t0 > timeout:
            series[-1]['timeout'] = True
            break
        time.sleep(poll)
    peak = lambda k: max(x[k] for x in series)
    return {'label': label, 'seconds': series[-1]['t'], 'saw_busy': saw_busy, 'peak_du_alloc_MB': peak('du_alloc_MB'),
            'peak_anon_MB': peak('anon_MB'), 'peak_file_MB': peak('file_MB'), 'peak_cg_MB': peak('cg_MB'),
            'min_du_alloc_MB': min(x['du_alloc_MB'] for x in series), 'cpu_s_total': series[-1]['cpu_s'] - series[0]['cpu_s'],
            'series': series}


def host_ls(lab, rel):
    return ssh(f"ls -la {lab.storage}/collections/{COLL}/0/{rel} 2>&1 | head -20; du -sb {lab.storage}/collections/{COLL}/0/{rel} 2>&1 | head -1").strip()


def qdrant_log_tail(lab, grep='segment|deleted|temp|optimi|Removing|remov|WARN|ERROR|Loaded|load', n=25):
    return ssh(f"docker logs --tail 200 {lab.name} 2>&1 | grep -i -E '{grep}' | tail -{n} | cut -c1-260").strip().split('\n')


def recall_block(lab, qv, gt, label):
    out = []
    for mode in (rv.M_PLAIN[:1] if label == 'before' else rv.M_QUANT[:1] + rv.M_QUANT[3:5]):
        d, res = rv.run_mode(lab, qv, mode, gt, FILTER_V135, passes=1)
        d.pop('_res_first', None)
        out.append(d)
        log(f"  [{label}] {mode['name']:<12} recall@10={d['recall@10']:.4f} @15={d['recall@15']:.4f} p50={d['lat']['p50_ms']:.1f} "
            f"p95={d['lat']['p95_ms']:.1f} ms (PROVISIONAL if host load >= 8)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=100000)
    ap.add_argument('--patch', default='v1')
    ap.add_argument('--queries', type=int, default=500)
    ap.add_argument('--small', type=int, default=6000)
    ap.add_argument('--batch', type=int, default=1000)
    ap.add_argument('--tag', default='.ip')
    ap.add_argument('--no-crash', action='store_true')
    ap.add_argument('--mem', default='4g')
    ap.add_argument('--budget-min', type=float, default=8.0)
    A = ap.parse_args()
    os.nice(15)
    a = argparse.Namespace(variant='V0', phase='load', data='syn', n=A.n, queries=A.queries, small=A.small, batch=A.batch,
                           mem=A.mem, steady_calls=1000, budget_min=A.budget_min, tag=A.tag, force=False, procs=3, cold='')
    ds = rv.get_ds()
    qrows, irows = rv.perm_rows(ds, a)
    gt = rv.get_gt(ds, qrows, irows, a)
    qv = ds.vectors(qrows)
    R = rv.load_R(a)
    OUT = f'{RES}/inplace.{A.patch}.json'
    X = {'patch_name': A.patch, 'patch_body': PATCHES[A.patch], 'n': A.n, 'start': time.strftime('%H:%M:%S'), 'load_start': loadavg()}
    lab = Lab(rv.run_id(a).replace('.', '-'), mem=A.mem)
    sess = {'phase': 'inplace', 'start': time.strftime('%H:%M:%S')}
    bg = None
    try:
        while lab.free_gb() < 7:
            time.sleep(60)
        lab.start(session=True)
        X['lock_wait_s'] = lab.t_lock_wait
        log(f'container up after {lab.t_lock_wait:.0f}s lock wait; load {loadavg()}')
        # ---- 1. V0 collection with NOMAD defaults (skipped if already loaded)
        if not R.get('load_phase_done'):
            rc = rv.do_load(a, R, lab, ds, irows, sess)
            if rc:
                raise RuntimeError('load incomplete, re-run')
            rv.save_R(a, R)
        qd = lab.qd
        X['before'] = {'info': qd.info(), 'mem': R['after_load']['mem'], 'disk': R['after_load']['disk']}
        wait_green(qd, stable=3)
        time.sleep(5)
        X['recall_before'] = recall_block(lab, qv, gt, 'before')
        # ---- 2. background searches
        T0 = perf_counter()
        bg = Bg(query_bodies(qv[:200], params=None, filt=FILTER_V135), T0)
        bg.start()
        time.sleep(10)
        X['bg_before'] = bg.summary()
        # ---- 3. PATCH in place
        t_patch = perf_counter() - T0
        st, js, dt = qd.req('PATCH', f'/collections/{COLL}', PATCHES[A.patch])
        X['patch_response'] = {'http': st, 'body': js, 'seconds': dt}
        log(f'PATCH -> {st} {json.dumps(js)[:200]} ({dt:.2f}s)')
        X['trace'] = trace_until_green(lab, qd, perf_counter(), 'patch_rebuild')
        t_done = perf_counter() - T0
        X['bg_during_rebuild'] = bg.summary(t_patch, t_done)
        log(f"rebuild: {X['trace']['seconds']}s, peak disk {X['trace']['peak_du_alloc_MB']} MB (min {X['trace']['min_du_alloc_MB']}), "
            f"peak anon {X['trace']['peak_anon_MB']} MB, cpu {X['trace']['cpu_s_total']:.0f}s; searches during: {X['bg_during_rebuild']}")
        bg.stop()
        bg = None
        time.sleep(15)
        X['after'] = rv.collect_state(lab, qd, 'after_patch')
        X['info_after'] = qd.info()
        X['recall_after'] = recall_block(lab, qv, gt, 'after')
        # ---- 4. restart behaviour
        X['restarts'] = {}
        r = lab.restart()
        tg, info = rv.wait_built(qd, A.n)
        X['restarts']['graceful'] = {**r, 'ready_to_green_s': tg, 'status': info['status'], 'points': info['points_count'],
                                     'quantization_config': info['config']['params'].get('vectors'), 'quant_top': info['config'].get('quantization_config'),
                                     'mem': rv.mem_view(lab.snapshot())}
        log(f"graceful restart: shutdown {r['shutdown_s']:.1f}s start->ready {r['start_to_ready_s']:.1f}s; status {info['status']}")
        # fake leftovers: a `.deleted` segment dir with content and a temp_segments dir with a 50 MB blob
        seg = f'{lab.storage}/collections/{COLL}/0'
        ssh(f"mkdir -p {seg}/segments/00000000-0000-4000-8000-00000000dead.deleted/sub {seg}/temp_segments/junk && "
            f"echo x > {seg}/segments/00000000-0000-4000-8000-00000000dead.deleted/sub/f && "
            f"dd if=/dev/zero of={seg}/temp_segments/junk/blob bs=1M count=50 status=none")
        before_ls = ssh(f"ls {seg}/segments | grep -c deleted; ls {seg}/temp_segments")
        r = lab.restart()
        tg, info = rv.wait_built(qd, A.n)
        after_ls = ssh(f"ls {seg}/segments | grep -c deleted; ls {seg}/temp_segments 2>&1 | head -3")
        X['restarts']['fake_leftovers'] = {**r, 'before': before_ls, 'after': after_ls, 'status': info['status'],
                                           'log': qdrant_log_tail(lab)}
        log(f"restart with fake leftovers: before={before_ls!r} after={after_ls!r}; status {info['status']}")
        # crash in the middle of a second rebuild (HNSW m=8 forces re-indexing of every segment)
        if not A.no_crash:
            st, js, dt = qd.req('PATCH', f'/collections/{COLL}', {'hnsw_config': {'m': 8, 'ef_construct': 64}})
            time.sleep(12)
            info = qd.info()
            pre = {'status': info['status'], 'segments': info['segments_count'], 'temp_segments': host_ls(lab, 'temp_segments'),
                   'segments_ls': ssh(f"ls {seg}/segments")}
            r = lab.restart(kill=True)
            tg, info2 = rv.wait_built(qd, A.n, timeout=1500)
            X['restarts']['crash_mid_rebuild'] = {'pre_kill': pre, **r, 'ready_to_green_s': tg, 'status_after': info2['status'],
                                                  'points': info2['points_count'], 'temp_after': host_ls(lab, 'temp_segments'),
                                                  'log': qdrant_log_tail(lab), 'hnsw_after': info2['config']['hnsw_config']}
            log(f"crash+restart: {json.dumps({k: v for k, v in X['restarts']['crash_mid_rebuild'].items() if k in ('status_after', 'points', 'ready_to_green_s')})}")
        X['load_end'] = loadavg()
        X['status'] = 'ok'
    except Exception:
        X['status'] = 'error'
        X['error'] = traceback.format_exc()
        log('ERROR ' + X['error'])
    finally:
        if bg:
            bg.stop()
        dump(OUT, X)
        sess['end'] = time.strftime('%H:%M:%S')
        R['sessions'].append(sess)
        rv.save_R(a, R)
        try:
            lab.stop()
        except Exception as e:  # noqa
            log(f'stop failed: {e}')
        lab.rmstorage()
    log(f'saved {OUT}')
    return 0 if X.get('status') == 'ok' else 1


if __name__ == '__main__':
    sys.exit(main())
