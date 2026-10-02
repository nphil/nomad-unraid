#!/bin/bash
# Dedupe step 1 (run under the lock): scan the live Qdrant for exact-duplicate candidates and write the delete plan. NO deletion here.
#   flock /tmp/agents-heavy.lock timeout 1500 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/06_dedupe_scan_plan.sh
# Resumable only as a whole (scan restarts from scratch). Niced, CPUs 0-4,8-12 (same as Qdrant's pin).
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/06_dedupe.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
qpid(){ ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'; }
QP=$(qpid); [ -n "$QP" ] || { log "ABORT: no qdrant"; exit 1; }
AV=$(free -m | awk '/^Mem:/{print $7}'); log "== 06 start; load $(cut -d' ' -f1-3 /proc/loadavg); RAM available ${AV} MB; qdrant pid $QP"; [ "$AV" -ge 8000 ] || { log "ABORT low RAM"; exit 1; }
PC=$(nsenter -t $QP -n curl -s -m 30 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])"); [ "${PC:-0}" -ge 3500000 ] || { log "ABORT: collection has only ${PC:-?} points (recovered store not live?)"; exit 1; }
log "collection: $(nsenter -t $QP -n curl -s -m 30 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print({k: r.get(k) for k in ('status','points_count','segments_count')})")"
run(){ nsenter -t $QP -n taskset -c 0-4,8-12 nice -n 10 python3 $R/dedupe.py "$1"; }
if [ ! -s $R/dup_candidates.jsonl ] || [ "${RESCAN:-0}" = 1 ]; then run scan || { log "ABORT: scan failed"; exit 1; }; else log "reusing existing dup_candidates.jsonl ($(wc -l < $R/dup_candidates.jsonl) groups)"; fi
run plan || { log "ABORT: plan failed"; exit 1; }
log "delete_ids.txt: $(wc -l < $R/delete_ids.txt) ids"; log "== 06 done"
