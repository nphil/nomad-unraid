#!/usr/bin/env python3
"""extrapolate.py - per-point constants -> disk / RAM at 4.1M, 8M, 20M, 40M points for the four layouts.
Every constant carries its provenance tag:
  [prod]    measured on the live production collection (telemetry snapshot state/qdrant_telemetry.json, NomadIndexAgent)
  [smoke]   measured by this lab on a throw-away Qdrant v1.16.3 at N=10,000 (results/baseline.test.10000.smoke.json ...)
  [docs]    Qdrant documented formula (capacity-planning / quantization pages, links in results.md)
  [infer]   inference, not measured
Writes results/extrapolation.json and prints a markdown table block.
"""
import json
import os

RES = '/data/home/tmp/nomadindex/qdrantlab/results'
NS = [4.1e6, 8e6, 20e6, 40e6]
GB = 1e9  # decimal GB

# ---- per point constants (bytes) ---------------------------------------------------------------------------------
C = {
    'vec_f32': (768 * 4, '[prod] 12,254,751,744 B / 3,989,177 pts = 3,072; = dims*4 [docs]'),
    'payload_stored': (2171, '[prod] 8,661,381,888 B / 3,989,177 pts (mixed libraries); Wikipedia chunks ~2.4 KB per NomadIndexAgent'),
    'payload_index_disk': (91, '[prod] NomadIndexAgent (source/content_type/collection/active indexes)'),
    'id_tracker_disk': (35, '[smoke] id_tracker folder 35 B/pt allocated (docs: 52 B/pt resident in RAM)'),
    'hnsw_graph': (54, '[smoke] 38 B per point on a 7,000-of-10,000 indexed collection = 54 B per indexed pt, m=16 compressed links (docs formula uncompressed: m*2*4*1.2 = 154)'),
    'quant_int8': (768, '[docs] 1 byte per dimension'),
    'quant_bin': (96, '[docs] 1 bit per dimension'),
    # RAM-only items
    'ram_id_tracker': (52, '[docs] capacity-planning: id tracker resident in RAM, 52 B/pt'),
    'ram_payload_index': (130, '[docs] payload index ~ 2 x indexed payload (source ~51 B + content_type ~11 B + bool) ~ 130 B/pt; resident'),
    'anon_slack_prod': (1270, '[prod] jemalloc live heap 5.9 GB / 4.11M pts = 1,440 B/pt minus the 182 B/pt the formulas explain = ~1,270 B/pt unexplained, plain-segment state'),
}
WAL_FIXED_GB = 0.06  # [smoke] 61 MB allocated


def per_point():
    c = {k: v[0] for k, v in C.items()}
    d = {}
    d['V0'] = c['vec_f32'] + c['payload_stored'] + c['payload_index_disk'] + c['id_tracker_disk'] + c['hnsw_graph']
    for v in ('V1', 'V2', 'V3'):
        d[v] = d['V0'] + c['quant_int8']
    # RAM needed for a FAST, healthy (indexed) collection, documented formulas (+ measured graph size)
    r = {}
    r['V0'] = c['vec_f32'] + c['hnsw_graph'] + c['ram_id_tracker'] + c['ram_payload_index']
    r['V1'] = c['quant_int8'] + c['hnsw_graph'] + c['ram_id_tracker'] + c['ram_payload_index']
    r['V2'] = c['quant_int8'] + c['ram_id_tracker'] + c['ram_payload_index']
    r['V3_mandatory'] = c['ram_id_tracker'] + c['ram_payload_index'] * 0  # payload index on_disk, quantized+graph mmap'd
    r['V3_hot_cache'] = c['quant_int8'] + c['hnsw_graph'] + c['ram_payload_index']  # what the page cache would like to hold
    return d, r, c


def main():
    d, r, c = per_point()
    out = {'constants_B_per_point': {k: {'bytes': v[0], 'source': v[1]} for k, v in C.items()},
           'disk_B_per_point': d, 'ram_B_per_point_formula': r, 'wal_fixed_GB': WAL_FIXED_GB, 'N': NS, 'tables': {}}
    rows = {}
    for v in ('V0', 'V1', 'V2', 'V3'):
        rows[v] = {
            'disk_GB': [round(d[v] * n / GB + WAL_FIXED_GB, 1) for n in NS],
            'disk_GB_payload_2400': [round((d[v] + (2400 - c['payload_stored'])) * n / GB + WAL_FIXED_GB, 1) for n in NS],
        }
    for v in ('V0', 'V1', 'V2'):
        rows[v]['ram_GB_formula'] = [round(r[v] * n / GB, 1) for n in NS]
        rows[v]['ram_GB_with_prod_anon_slack'] = [round((r[v] + c['anon_slack_prod']) * n / GB, 1) for n in NS]
    rows['V3']['ram_GB_formula_mandatory'] = [round(r['V3_mandatory'] * n / GB, 1) for n in NS]
    rows['V3']['ram_GB_formula_hot_cache_wanted'] = [round((r['V3_mandatory'] + r['V3_hot_cache']) * n / GB, 1) for n in NS]
    rows['V3']['ram_GB_with_prod_anon_slack'] = [round((r['V3_mandatory'] + c['anon_slack_prod']) * n / GB, 1) for n in NS]
    # largest N that fits 10 GB of RAM
    fit = {}
    for v, key in (('V0', 'V0'), ('V1', 'V1'), ('V2', 'V2'), ('V3', 'V3_mandatory')):
        fit[v] = {'formula_M_points': round(10e9 / r[key] / 1e6, 1),
                  'with_prod_anon_slack_M_points': round(10e9 / (r[key] + c['anon_slack_prod']) / 1e6, 1)}
    out['tables'] = rows
    out['fits_10GB'] = fit
    # CPU-based build estimate [infer]: 10k-point plain->indexed rebuild used ~24.6 CPU-s (results/plain.test.10000.smoke.json)
    cpu_ms_per_pt = 2.46
    out['build_cpu_estimate'] = {'cpu_ms_per_point_at_10k_smoke': cpu_ms_per_pt,
                                 'cpu_hours': {f'{int(n / 1e6) if n >= 1e6 else n}M': round(cpu_ms_per_pt * 1e-3 * n / 3600, 1) for n in NS},
                                 'note': '[infer] HNSW cost per point grows ~log N, so real values may be up to ~2x higher; divide by the cores actually granted (4)'}
    json.dump(out, open(f'{RES}/extrapolation.json', 'w'), indent=1)
    print('disk B/pt', d)
    print('RAM B/pt (formula)', r)
    for v in rows:
        print(v, json.dumps(rows[v]))
    print('fits 10 GB', json.dumps(fit))
    print('build', json.dumps(out['build_cpu_estimate']))


if __name__ == '__main__':
    main()
