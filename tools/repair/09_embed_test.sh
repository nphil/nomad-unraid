#!/bin/bash
# New-points test (run under the lock, ~16 min, uses the GPU embedding server): open the nightly queue for 10 minutes and check that
# new chunks land in Qdrant, are searchable and get indexed. Leaves the queue PAUSED again at the end (the gate is re-applied separately).
#   PHASE=1 flock /tmp/agents-heavy.lock timeout 2400 bash .../09_embed_test.sh     (PHASE 1 and 2 = two windows; each measures what a ZFS snapshot taken before it ends up pinning)
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/09_embed_test.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
QP=$(ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'); [ -n "$QP" ] || { log "ABORT no qdrant"; exit 1; }
count(){ nsenter -t $QP -n curl -s -m 60 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print('pts', r['points_count'], 'indexed', r['indexed_vectors_count'], 'segs', r['segments_count'], r['status'])"; }
AV=$(free -m | awk '/^Mem:/{print $7}'); log "== 09 start; load $(cut -d' ' -f1-3 /proc/loadavg); RAM available ${AV} MB"; [ "$AV" -ge 8000 ] || { log "ABORT low RAM"; exit 1; }
log "before: $(count)"; docker exec Nomad nomad-embed status 2>&1 | sed -n 1,3p
PHASE=${PHASE:-1}; DSN=nvme/appdata/nomad-qdrant-recovered; MPN=/mnt/nvme/appdata/nomad-qdrant-recovered; SNAP=churn-$PHASE
zfs destroy $DSN@$SNAP 2>/dev/null; zfs snapshot $DSN@$SNAP && log "snapshot @$SNAP taken; dataset: $(zfs list -H -o used,usedbydataset,usedbysnapshots $DSN | tr '\t' ' ') (used, by dataset, by snapshots)"
T0=$(date +%s%3N); log "t0 (epoch ms) = $T0"
docker exec Nomad nomad-embed now 10 2>&1 | tail -2
for i in $(seq 22); do sleep 30; log "$(count)"; done
docker exec Nomad nomad-embed now off 2>&1 | tail -2
docker exec Nomad nomad-embed pause >/dev/null 2>&1   # no gate is running here, so close the queue ourselves right away
log "waiting for the running batches to finish (max 10 min)"
for i in $(seq 20); do sleep 30; A=$(docker exec Nomad nomad-embed status 2>&1 | grep -E '^Jobs' | sed 's/.*active \([0-9]*\),.*/\1/'); [ "${A:-1}" = 0 ] && break; done
docker exec Nomad nomad-embed pause 2>&1 | tail -1; docker exec Nomad nomad-embed status 2>&1 | sed -n 1,3p
log "after: $(count)"
sleep 60; log "after 60 s more: $(count)"
nsenter -t $QP -n python3 $R/new_points_check.py $T0; echo "new_points_check exit=$?"
nsenter -t $QP -n curl -s -m 60 "http://127.0.0.1:6333/telemetry?details_level=6" | python3 -c "
import sys, json
t = json.load(sys.stdin)['result']['collections']['collections'][0]['shards'][0]['local']
for e in (t.get('optimizations') or {}).get('log', [])[-4:]: print('  optimizer log:', json.dumps(e)[:260])
for s in t['segments']: i = s['info']; print('  segment', i['segment_type'], 'pts', i['num_points'], 'idx', i['num_indexed_vectors'])"
log "settling: waiting for the optimizer to go green (max 8 min)"
for i in $(seq 16); do ST=$(count); case "$ST" in *green) break;; esac; sleep 30; done; log "settled: $(count)"
log "CHURN phase $PHASE: snapshot holds $(zfs get -Hp -o value used $DSN@$SNAP | awk '{printf "%.0f MB", $1/1e6}') unique to it; dataset now: $(zfs list -H -o used,usedbydataset,usedbysnapshots $DSN | tr '\t' ' ')"
python3 $R/snapdiff.py $DSN $MPN $SNAP
zfs destroy $DSN@$SNAP && log "snapshot @$SNAP destroyed"
log "== 09 done"
