#!/bin/bash
# Clean restart of the Nomad container after the host overload broke `docker exec` into its inner containers
# ("error adding pid ... to cgroups ... cgroup.procs: no such file or directory"; nomad_admin/redis/flatnotes unhealthy).
# Run under the lock: flock /tmp/agents-heavy.lock timeout 900 bash <this>
# Plain stop/start (same container, same template): Redis and Qdrant save on SIGTERM, the writable layer (nomad-embed tool) survives,
# the gate process does not (re-apply with nomad-embed-hot-apply.sh apply afterwards).
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/12_restart.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
qpid(){ ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'; }
AV=$(free -m | awk '/^Mem:/{print $7}'); log "== 12 start; load $(cut -d' ' -f1-3 /proc/loadavg); RAM available ${AV} MB"; [ "$AV" -ge 8000 ] || { log "ABORT low RAM"; exit 1; }
log "inner exec test before: $(docker exec Nomad docker exec nomad_redis redis-cli ping 2>&1 | cut -c1-90)"
t0=$(date +%s); docker stop Nomad >/dev/null || { log "ABORT: docker stop failed"; exit 1; }; log "Nomad stopped in $(( $(date +%s)-t0 )) s (exit $(docker inspect Nomad --format '{{.State.ExitCode}}'), oom $(docker inspect Nomad --format '{{.State.OOMKilled}}'))"
docker start Nomad >/dev/null || { log "ABORT: docker start failed"; exit 1; }
H=""; for i in $(seq 100); do H=$(docker inspect Nomad --format '{{.State.Health.Status}}' 2>/dev/null); [ "$H" = healthy ] && break; sleep 5; done; log "outer health: $H after $(( $(date +%s)-t0 )) s"
for i in $(seq 60); do A=$(docker exec Nomad docker ps --filter name=nomad_admin --format '{{.Status}}' 2>/dev/null); case "$A" in *healthy*) case "$A" in *unhealthy*) ;; *) break;; esac;; esac; sleep 5; done; log "nomad_admin: $A"
QP=""; for i in $(seq 120); do QP=$(qpid); [ -n "$QP" ] && nsenter -t $QP -n curl -s -m 5 http://127.0.0.1:6333/collections/nomad_knowledge_base 2>/dev/null | grep -q '"points_count"' && break; sleep 5; done
log "qdrant pid=$QP storage: $(grep -m1 ' /data/qdrant ' /proc/$(docker inspect -f '{{.State.Pid}}' Nomad)/mountinfo | sed 's/.* - zfs //' | cut -c1-70)"
[ -n "$QP" ] && { taskset -a -p -c 0-4,8-12 $QP >/dev/null; for t in $(ls /proc/$QP/task); do renice -n 10 -p $t >/dev/null 2>&1; done; log "affinity: $(taskset -pc $QP)"; }
nsenter -t $QP -n curl -s -m 60 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print('collection:', {k: r.get(k) for k in ('status','points_count','indexed_vectors_count','segments_count')})"
log "inner exec test after: $(docker exec Nomad docker exec nomad_redis redis-cli ping 2>&1 | cut -c1-90)"
docker exec Nomad nomad-embed status 2>&1 | sed -n 1,3p | cut -c1-200
docker exec Nomad docker ps --format '{{.Names}} {{.Status}}' 2>&1 | head -9
grep -E 'RssAnon|RssFile|VmSwap' /proc/$QP/status | tr -s ' \t' ' ' | tr '\n' ' '; echo
log "== 12 done (gate NOT running: run nomad-embed-hot-apply.sh apply)"
