#!/usr/bin/env python3
"""summarize.py [run-json ...] - compact console view of run_v.py results (default: all results/V*-syn-*.json and E_*)."""
import glob
import json
import os
import sys

RES = '/data/home/tmp/nomadindex/qdrantlab/results'


def mb(x):
    return f'{x:.0f}'


def show(path):
    R = json.load(open(path))
    n = R['n']
    print(f"\n=== {R['run']}  N={n}  {R.get('desc', '')}")
    al = R.get('after_load')
    if al:
        d = al['disk']
        b = d['buckets']
        pts = d['points']
        parts = {k: round(v['allocated'] / pts, 1) for k, v in b.items() if k != 'wal'}
        print(f"  disk allocated: total {d['storage_allocated'] / 1e6:.0f} MB = {d['storage_allocated'] / pts:.0f} B/pt "
              f"(wal {b.get('wal', {}).get('allocated', 0) / 1e6:.0f} MB fixed); per point ex-WAL: {parts}")
        print(f"  segments {d['segments']} indexed {d['indexed_vectors']}/{pts}; telemetry segs: "
              f"{[(s['type'], s['points']) for s in al['telemetry'].get('segments', [])]}")
        m = al['mem']
        print(f"  RAM after load (running process): anon {m['RssAnon_MB']} MB  file {m['RssFile_MB']} MB  HWM {m['VmHWM_MB']}  cg {m['cg_current_MB']}")
    if R.get('measure', {}).get('after_restart'):
        ar = R['measure']['after_restart']
        m = ar['mem']
        d = ar['disk']
        print(f"  RAM after restart: anon {m['RssAnon_MB']} MB ({m['RssAnon_MB'] * 1e6 / n:.0f} B/pt)  file {m['RssFile_MB']} MB ({m['RssFile_MB'] * 1e6 / n:.0f} B/pt)  cg {m['cg_current_MB']}")
        sm = ar['smaps_top'][:4]
        print('  smaps top:', [(x['name'].split('/')[-2] + '/' + x['name'].split('/')[-1] if '/' in x['name'] else x['name'], x['rss_kb'] // 1024, x['anon_kb'] // 1024) for x in sm])
        print(f"  jemalloc: {ar['metrics']}")
    for k in ('after_200_queries', 'after_queries'):
        if R.get('measure', {}).get(k):
            m = R['measure'][k]['mem']
            print(f"  RAM {k}: anon {m['RssAnon_MB']}  file {m['RssFile_MB']}")
    if R.get('measure', {}).get('after_ensure'):
        m = R['measure']['after_ensure']['mem']
        print(f"  RAM after NOMAD ensure(): anon {m['RssAnon_MB']}  file {m['RssFile_MB']}; ensure timings {json.dumps({k: round(v, 3) for k, v in R['measure']['nomad_ensure'].items()})}")
    for s in R.get('ingest_segments', []):
        print(f"  ingest {s['key']:<18} {s['points']} pts {s['mode']} {s['batch']}/call: {s['points_per_s_server']:.0f} pts/s server-side, {s['calls_per_s_server']:.0f} calls/s, "
              f"p50 {s['call_ms_p50']:.1f} p95 {s['call_ms_p95']:.1f} ms  (load at end {s.get('load_at_end')})")
    print(f"  build tail {R.get('tail_wait_after_last_upsert_s')}s after last upsert; cpu_s {R.get('cpu_s')}; bulk_recipe {R.get('bulk_recipe')}")
    for md in R.get('measure', {}).get('modes', []):
        L = md['lat']
        print(f"  mode {md['mode']:<18} recall@10 {md['recall@10']:.4f} @15 {md['recall@15']:.4f}  p50 {L['p50_ms']:.1f} p95 {L['p95_ms']:.1f} p99 {L['p99_ms']:.1f} ms  "
              f"score_err {md.get('score_abs_err_vs_exact')}  load {md['load_before'][0]}->{md['load_after'][0]} {'' if md['load_ok'] else 'PROVISIONAL'}")
    for s in R.get('sessions', []):
        print(f"  session {s['phase']}: lock wait {s.get('lock_wait_s', 0):.0f}s, restart {s.get('restart')}, load {s.get('load_start')} -> {s.get('load_end')} {'ERROR' if s.get('error') else ''}")


if __name__ == '__main__':
    paths = sys.argv[1:] or sorted(glob.glob(f'{RES}/V*-syn-*.json') + glob.glob(f'{RES}/E_*-syn-*.json'))
    for p in paths:
        if 'smoke' in p:
            continue
        show(p)
