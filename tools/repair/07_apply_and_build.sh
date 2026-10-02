#!/bin/bash
# Step 7 (run under the lock, ~5-10 min): apply the reviewed dedupe plan, then START the int8 + HNSW build.
#   flock /tmp/agents-heavy.lock timeout 1500 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/07_apply_and_build.sh
# The build keeps running inside Qdrant after this script ends (niced, pinned to CPUs 0-4,8-12, 2 indexing threads, max 2 optimizer tasks);
# pause it with 04_patch_build.sh pause, watch it with 04_patch_build.sh watch (read-only API polling, no lock needed).
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/07_apply_build.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
qpid(){ ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'; }
QP=$(qpid); [ -n "$QP" ] || { log "ABORT: no qdrant"; exit 1; }
AV=$(free -m | awk '/^Mem:/{print $7}'); log "== 07 start; load $(cut -d' ' -f1-3 /proc/loadavg); RAM available ${AV} MB"; [ "$AV" -ge 8000 ] || { log "ABORT low RAM"; exit 1; }
docker exec Nomad nomad-embed status 2>&1 | grep -E '^Queue|^Jobs'
PC=$(nsenter -t $QP -n curl -s -m 30 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['points_count'])")
[ "${PC:-0}" -ge 3500000 ] || { log "ABORT: only ${PC:-?} points (recovered store not live?)"; exit 1; }
N=$(wc -l < $R/delete_ids.txt); [ "$N" -gt 0 ] || { log "ABORT: empty delete plan"; exit 1; }
log "applying $N planned deletions to a collection with $PC points"
nsenter -t $QP -n taskset -c 0-4,8-12 nice -n 10 python3 $R/dedupe.py apply || { log "ABORT: apply failed (partial deletes are safe: re-run is idempotent)"; exit 1; }
log "dedupe applied; status:"; bash $R/04_patch_build.sh status
log "starting int8 + HNSW build (PATCH)"; bash $R/04_patch_build.sh start
sleep 90; bash $R/04_patch_build.sh status
log "== 07 done (build continues in the background)"
