#!/bin/bash
# Recovery step 2 (run under the lock): load the RECOVERED store in a capped scratch Qdrant, check it, stop it gracefully.
#   flock /tmp/agents-heavy.lock timeout 2400 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/04_recover_validate.sh
# Never touches the production store or the array copy. Set ROLLBACK=1 to go back to the pre-validation snapshot first.
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/04_recover_validate.log" 2>&1
DS=nvme/appdata/nomad-qdrant-recovered; MP=/mnt/nvme/appdata/nomad-qdrant-recovered; NAME=nomadindex-qdrant-recover
log(){ echo "[$(date +%T)] $*"; }
log "== 04 start; load $(cut -d' ' -f1-3 /proc/loadavg)"
AV=$(free -m | awk '/^Mem:/{print $7}'); log "RAM available ${AV} MB"; [ "$AV" -ge 10000 ] || { log "ABORT <10 GB RAM available"; exit 1; }
zfs list $DS >/dev/null 2>&1 || { log "ABORT: recovered dataset missing (run 03 first)"; exit 1; }
docker rm -f $NAME >/dev/null 2>&1
if [ "${ROLLBACK:-0}" = 1 ]; then zfs rollback -r $DS@pre-validate && log "rolled back to @pre-validate"; fi
zfs list -t snapshot $DS@pre-validate >/dev/null 2>&1 || { zfs snapshot $DS@pre-validate && log "snapshot @pre-validate taken"; }
docker run -d --rm --name $NAME --memory=4g --memory-swap=4g --cpus=4 --cpuset-cpus=0-4,8-12 -v $MP:/qdrant/storage -p 127.0.0.1:16333:6333 qdrant/qdrant:v1.16.3 >/dev/null || { log "ABORT: docker run failed"; exit 1; }
( docker logs -f $NAME > $R/logs/qdrant-scratch-$(date +%H%M%S).log 2>&1 & )
T0=$(date +%s); READY=0
for i in $(seq 300); do
  if curl -s -m 5 http://127.0.0.1:16333/collections/nomad_knowledge_base 2>/dev/null | grep -q '"points_count"'; then READY=1; break; fi
  docker ps --format '{{.Names}}' | grep -q "^$NAME$" || { log "ABORT: scratch container died while loading"; docker logs $NAME 2>&1 | tail -30 | cut -c1-250; break; }
  sleep 5
done
log "ready=$READY after $(( $(date +%s)-T0 )) s"
if [ "$READY" = 1 ]; then
  docker stats --no-stream --format 'mem {{.MemUsage}} cpu {{.CPUPerc}}' $NAME
  QDRANT_BASE=http://127.0.0.1:16333 STORE=$MP python3 $R/recover_check.py; echo "recover_check exit=$?"
  QDRANT_BASE=http://127.0.0.1:16333 SKIP_RECALL=1 TAG=recovered-plain python3 $R/verify_search.py 2
  docker stats --no-stream --format 'mem {{.MemUsage}} cpu {{.CPUPerc}}' $NAME
  log "cgroup peak memory: $(cat /sys/fs/cgroup/docker/$(docker inspect -f '{{.Id}}' $NAME)/memory.peak 2>/dev/null || echo n/a)"
fi
log "-- scratch qdrant log (non-request lines)"
docker logs $NAME 2>&1 | grep -v 'actix_web::middleware::logger' | tail -50 | cut -c1-260
t=$(date +%s); docker stop -t 120 $NAME >/dev/null 2>&1; log "scratch stopped in $(( $(date +%s)-t )) s (container gone: $(docker ps -a --format '{{.Names}}' | grep -c "^$NAME$" | sed 's/1/NO/;s/0/yes/'))"
sleep 2; tail -12 $(ls -t $R/logs/qdrant-scratch-*.log | head -1) | cut -c1-220
du -sh $MP; zfs list -o name,used,avail $DS
log "== 04 done"
