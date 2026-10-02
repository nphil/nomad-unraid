#!/bin/bash
# Qdrant build control, on the Unraid host. usage: 04_patch_build.sh start | watch [minutes] | pause | resume | status
set -uo pipefail
qpid(){ ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'; }
QP=$(qpid); [ -n "$QP" ] || { echo "no qdrant process"; exit 1; }
api(){ nsenter -t $QP -n curl -s -m 600 -H 'content-type: application/json' "$@"; }
C=http://127.0.0.1:6333/collections/nomad_knowledge_base
pin(){ taskset -a -p -c 0-4,8-12 $QP >/dev/null; for t in $(ls /proc/$QP/task); do renice -n 10 -p $t >/dev/null 2>&1; done; }
status(){ api $C | python3 -c "
import sys, json, time
r = json.load(sys.stdin)['result']; o = r['config']['optimizer_config']
print(time.strftime('%H:%M:%S'), r['status'], 'pts', r['points_count'], 'indexed', r['indexed_vectors_count'], 'segs', r['segments_count'], 'opt_thr', o.get('max_optimization_threads'), 'idx_thr', o.get('indexing_threshold'), 'err:', str(r.get('optimizer_status'))[:90] if r.get('optimizer_status') != 'ok' else 'ok')"
  echo "   load $(cut -d' ' -f1-3 /proc/loadavg) | $(grep -E 'RssAnon|RssFile|VmSwap' /proc/$QP/status | tr -s ' \t' ' ' | tr '\n' ' ') | qdrant cpu% $(ps -o %cpu= -p $QP)"; }
case "${1:-status}" in
  start)
    pin
    api -X PATCH $C -d '{"vectors":{"":{"on_disk":true}},"hnsw_config":{"max_indexing_threads":2},"quantization_config":{"scalar":{"type":"int8","quantile":0.99,"always_ram":false}},"optimizers_config":{"deleted_threshold":0.2,"indexing_threshold":10000,"max_optimization_threads":2}}'; echo; status ;;
  watch)
    END=$(( $(date +%s) + ${2:-20}*60 )); pin
    while [ $(date +%s) -lt $END ]; do status | tee -a /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/logs/04_watch.log; 
      api $C | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; sys.exit(0 if r['status']=='green' and r['indexed_vectors_count']>=0.98*r['points_count'] else 1)" && { echo "BUILD COMPLETE"; exit 0; }
      sleep 60; done; echo "watch window over (build still running or not green)";;
  pause)  api -X PATCH $C -d '{"optimizers_config":{"max_optimization_threads":0}}'; echo; status ;;
  resume) api -X PATCH $C -d '{"optimizers_config":{"max_optimization_threads":2}}'; echo; pin; status ;;
  status) status ;;
esac
