#!/usr/bin/env python3
"""build_results.py - merge smoke measurements, production telemetry facts, documented formulas and the extrapolation
into /data/home/tmp/nomadindex/qdrantlab/results.json (machine-readable twin of results.md)."""
import json
import os

BASE = '/data/home/tmp/nomadindex/qdrantlab'
RES = f'{BASE}/results'
extr = json.load(open(f'{RES}/extrapolation.json'))
smoke = json.load(open(f'{RES}/smoke_summary.json'))
base = json.load(open(f'{RES}/baseline.test.10000.smoke.json'))
plain = json.load(open(f'{RES}/plain.test.10000.smoke.json'))
u = plain['unstick']

out = {
    'meta': {
        'slice': 'qdrantlab', 'qdrant_version': 'v1.16.3 (= production)', 'status': 'partial: scope cut by instruction (host overload / one-heavy-job lock)',
        'tags': {'smoke': 'measured N=10,000 throw-away collection, host load 40-165, timings PROVISIONAL', 'prod': 'live production telemetry snapshot / host ls,du',
                 'src': 'Qdrant v1.16.3 source / OpenAPI', 'docs': 'Qdrant documentation formula', 'infer': 'inference, not measured'},
        'not_run': ['N>=100k variant runs', 'real-vector recall/NDCG (bench/emb was empty)', 'in-place quantization PATCH proof', 'restart-with-leftovers test',
                    'anon-heap attribution runs (E_plain/E_noidx/E_idxdisk/E_intid)'],
        'scripts_exercised_end_to_end': ['scripts/run_variant.py with the EARLIER qlab.py (N=10k smoke)'],
        'scripts_written_never_run': ['scripts/qlab.py (current version)', 'scripts/run_v.py', 'scripts/inplace.py', 'scripts/fidelity.py', 'scripts/quiet_window.sh'],
        'deferred_runs': 'local://quiet-NomadQdrantLab.md',
    },
    'defaults_check': {'verified': True, 'detail': 'NOMAD createCollection call on v1.16.3 gives on_disk_payload=true, hnsw m16/ef100/full_scan 10000/on_disk false, indexing_threshold 10000, wal 32 MB, no quantization = production config (state/qdrant_collection.json)'},
    'nomad_search_shape_v1_35_0': {'limit': 15, 'score_threshold': 0.3, 'with_payload': True, 'filter': {'must_not': [{'key': 'active', 'match': {'value': False}}]},
                                   'params': None, 'note': 'collection==eval exclusion only in facet calls (rag_service.ts l.43-45 vs l.1030-1042)'},
    'quantization_defaults_v1_16_3': {'rescore_default': {'scalar_int8': False, 'product': False, 'binary': True}, 'oversampling_default': 1.0,
                                      'consequence': 'NOMAD (no search params) gets NO rescoring with int8; score_threshold applies to int8-approximate scores',
                                      'source': 'lib/segment/src/vector_storage/quantized/quantized_vectors.rs l.194-208; lib/segment/src/types.rs l.480-505'},
    'smoke_N10000': {
        'disk_allocated_B_per_point': {k: v['allocated_B_per_pt'] for k, v in smoke['baseline.test.10000.smoke']['disk_per_point'].items()},
        'disk_total_ex_wal_B_per_point': smoke['baseline.test.10000.smoke']['disk_total_ex_wal_B_per_pt'],
        'rss_MB': smoke['baseline.test.10000.smoke']['rss'], 'rss_plain_MB': smoke['plain.test.10000.smoke']['rss'],
        'telemetry_bytes_per_point': smoke['baseline.test.10000.smoke']['telemetry_bytes_per_pt'],
        'recall_synthetic_default_hnsw_ef100': base['modes'][0]['recall@10'],
        'upserts_PROVISIONAL': {'small_1to5_per_call_pts_per_s': [316, 108], 'bulk_500_per_call_pts_per_s': [2297, 2001], 'steady_small_pts_per_s': [286, 314]},
        'plain_to_indexed_patch': {'body': {'optimizers_config': {'indexing_threshold': 10000}}, 'seconds': round(u['seconds'], 1),
                                   'disk_MB': {'before': round(u['before']['storage_allocated'] / 1e6, 1), 'peak': round(u['peak_storage_allocated'] / 1e6, 1),
                                               'after': round(u['after']['storage_allocated'] / 1e6, 1)},
                                   'peak_anon_MB': round(u['peak_rss_anon'] / 1e6, 1), 'cpu_s': 24.6, 'host_load_1min': 99.35},
        'nomad_ensure_seconds': plain['nomad_ensure'],
    },
    'production_facts': {
        'points': 4110669, 'plain_segment_points': 3989177, 'vectors_B_per_point': 3072, 'payload_stored_B_per_point': 2171.2,
        'payload_index_B_per_point': 91, 'jemalloc_allocated_GB': 5.91, 'heap_B_per_point': 1438, 'status': 'red',
        'optimizer_error': 'Directory not empty (os error 39) removing a *.deleted segment dir',
        'storage_path': {'container_bind': '/mnt/user/Stash/Nomad (FUSE shfs)', 'qdrant_dir_on_disks_GB': {'disk2': 3.5, 'disk3': 38, 'disk5': 0}},
        'ensure_calls_15h': {'PUT_index': {'count': 2040, 'avg_s': 4.77, 'max_s': 1481}, 'setPayload': {'count': 507, 'avg_s': 155.2, 'max_s': 3290}},
    },
    'extrapolation': extr,
    'recommendation': {
        'create_body': {'vectors': {'size': 768, 'distance': 'Cosine', 'on_disk': True},
                        'quantization_config': {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}},
                        'hnsw_config': {'m': 16, 'ef_construct': 100, 'on_disk': False}, 'on_disk_payload': True},
        'patch_body_in_place': {'vectors': {'': {'on_disk': True}}, 'quantization_config': {'scalar': {'type': 'int8', 'quantile': 0.99, 'always_ram': True}}},
        'v2_extra': {'hnsw_config': {'on_disk': True}},
        'storage': 'bind a direct NVMe/ZFS path (/mnt/nvme/...) or a single /mnt/diskN path, never /mnt/user (FUSE shfs)',
    },
}
json.dump(out, open(f'{BASE}/results.json', 'w'), indent=1)
print('wrote', f'{BASE}/results.json', os.path.getsize(f'{BASE}/results.json'), 'bytes')
