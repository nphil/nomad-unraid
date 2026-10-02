#!/bin/bash
# Final verification (run under the lock, ~10-15 min): state, config, segments, latency + recall, RAM, disk.
#   flock /tmp/agents-heavy.lock timeout 1800 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/08_final_verify.sh
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/08_final_verify.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
QP=$(ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'); [ -n "$QP" ] || { log "ABORT no qdrant"; exit 1; }
api(){ nsenter -t $QP -n curl -s -m 120 "$@"; }
ram(){ grep -E 'RssAnon|RssFile|VmSwap' /proc/$QP/status | tr -s ' \t' ' ' | tr '\n' ' '; }
log "== 08 start; load $(cut -d' ' -f1-3 /proc/loadavg)"; log "RSS before queries: $(ram)"
api http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']; c = r['config']
print('collection:', {k: r.get(k) for k in ('status','points_count','indexed_vectors_count','segments_count')}, 'optimizer:', r.get('optimizer_status'))
print('vectors:', c['params']['vectors'], '| quantization:', c.get('quantization_config'), '| hnsw:', c['hnsw_config'])
print('optimizer_config:', c['optimizer_config'])
print('payload_schema:', {k: (v.get('data_type'), v.get('points')) for k, v in r.get('payload_schema', {}).items()})"
api "http://127.0.0.1:6333/telemetry?details_level=6" | python3 -c "
import sys, json
t = json.load(sys.stdin)['result']['collections']['collections'][0]['shards'][0]['local']
for s in t['segments']:
    i = s['info']; c = s['config']['vector_data'].get('', {})
    print(' segment', i['segment_type'], 'pts', i['num_points'], 'idx', i['num_indexed_vectors'], 'del', i.get('num_deleted_vectors'), 'storage', c.get('storage_type'), 'quant', json.dumps(c.get('quantization_config'))[:90], 'index', c.get('index', {}).get('type'))"
log "-- searches (NOMAD-shaped: limit 15, threshold 0.3, active != false), recall vs float-exact"
nsenter -t $QP -n taskset -c 0-4,8-12 env TAG=final python3 $R/verify_search.py 10
log "RSS after queries: $(ram)"
log "disk: $(zfs list -H -o name,used,refer nvme/appdata/nomad-qdrant-recovered | tr '\t' ' ')"; du -sm /mnt/nvme/appdata/nomad-qdrant-recovered/collections/nomad_knowledge_base/0/segments/* | awk '{s+=$1} END{print "segments on disk MB:", s}'
du -sm /mnt/nvme/appdata/nomad-qdrant-recovered/collections/nomad_knowledge_base/0/wal | awk '{print "wal MB:", $1}'
log "load now $(cut -d' ' -f1-3 /proc/loadavg)"; log "== 08 done"
