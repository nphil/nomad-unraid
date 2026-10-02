#!/bin/bash
# Recovery step 3 (run under the lock): point Nomad's Qdrant at the RECOVERED, validated store.
#   flock /tmp/agents-heavy.lock timeout 900 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/05_recover_swap.sh
# Stops Nomad (~12 s), edits ONE path in the Unraid template (backup first), recreates via CreateDocker.php, verifies.
# The partial v1 store (/mnt/nvme/appdata/nomad-qdrant) and the array copy stay untouched (rollback = 99_rollback.sh <template backup>).
# No automatic rollback after the recreate: diagnostics first.
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/05_recover_swap.log" 2>&1
NEW=/mnt/nvme/appdata/nomad-qdrant-recovered; OLDP=/mnt/nvme/appdata/nomad-qdrant
TPL=/boot/config/plugins/dockerMan/templates-user/my-Nomad.xml; BK=/boot/config/plugins/dockerMan/backup-2026-10-02; STAMP=$(date +%H%M%S)
log(){ echo "[$(date +%T)] $*"; }
abort_start(){ log "ABORT: $1 -> restarting the CURRENT container (v1 store)"; docker start Nomad >/dev/null 2>&1; exit 1; }
qpid(){ ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'; }
log "== 05 start; load $(cut -d' ' -f1-3 /proc/loadavg)"
AV=$(free -m | awk '/^Mem:/{print $7}'); log "RAM available ${AV} MB"; [ "$AV" -ge 8000 ] || { log "ABORT low RAM"; exit 1; }
docker ps --format '{{.Names}}' | grep -q '^nomadindex-qdrant-recover$' && { log "ABORT: scratch Qdrant still running"; exit 1; }
[ -f $NEW/collections/nomad_knowledge_base/config.json ] || { log "ABORT: recovered store missing"; exit 1; }
grep -q 'Target="/data/qdrant"' $TPL || { log "ABORT: template has no /data/qdrant path"; exit 1; }
docker exec Nomad nomad-embed pause
ST=$(docker exec Nomad nomad-embed status 2>&1); echo "$ST" | sed -n 1,3p
echo "$ST" | grep -q "active 0," || { log "ABORT: embedding job active; retry later"; exit 1; }
cp -a $TPL $BK/my-Nomad.xml.pre-qdrant-recovered-$STAMP && log "template backup: $BK/my-Nomad.xml.pre-qdrant-recovered-$STAMP"
QP=$(qpid); grep -E 'VmRSS|RssAnon|RssFile|VmSwap' /proc/$QP/status > $R/qdrant-ram-v1-$STAMP.txt
docker exec Nomad docker exec nomad_redis redis-cli bgsave >/dev/null 2>&1; sleep 5
t0=$(date +%s); docker stop Nomad >/dev/null || { log "ABORT: docker stop failed"; exit 1; }; log "Nomad stopped in $(( $(date +%s)-t0 )) s"
python3 - "$TPL" <<'PY' || abort_start "template edit failed"
import re, sys
p = sys.argv[1]; s = open(p).read()
m = re.search(r'^[ \t]*<Config Name="Qdrant storage \(NVMe\)".*?</Config>[ \t]*\n', s, re.M | re.S)
if not m: sys.exit("anchor not found")
line = m.group(0)
new = line.replace('Default="/mnt/nvme/appdata/nomad-qdrant"', 'Default="/mnt/nvme/appdata/nomad-qdrant-recovered"').replace('>/mnt/nvme/appdata/nomad-qdrant</Config>', '>/mnt/nvme/appdata/nomad-qdrant-recovered</Config>')
if new == line: sys.exit("nothing replaced")
open(p, "w").write(s.replace(line, new, 1)); print("template updated")
PY
log "template qdrant path: $(grep 'Target="/data/qdrant"' $TPL | sed 's/.*Default=\"\([^\"]*\)\".*>\(.*\)<\/Config>/default=\1 value=\2/')"
php $R/recreate.php > $R/logs/recreate-$STAMP.out 2>&1; log "recreate.php exit $?"
docker start Nomad >/dev/null 2>&1
H=""; for i in $(seq 100); do H=$(docker inspect Nomad --format '{{.State.Health.Status}} restarting={{.State.Restarting}}' 2>/dev/null); [ "${H%% *}" = healthy ] && break; sleep 5; done
log "outer health: $H"
docker inspect Nomad --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}; {{end}}'
if [ "${H%% *}" != healthy ]; then log "NOT healthy: diagnostics follow (no auto rollback)"; docker logs Nomad --tail 40 2>&1 | cut -c1-200; exit 2; fi
for i in $(seq 60); do A=$(docker exec Nomad docker ps --filter name=nomad_admin --format '{{.Status}}' 2>/dev/null); case "$A" in *healthy*) break;; esac; sleep 5; done; log "nomad_admin: $A"
QP=""; for i in $(seq 240); do QP=$(qpid); [ -n "$QP" ] && nsenter -t $QP -n curl -s -m 5 http://127.0.0.1:6333/collections/nomad_knowledge_base 2>/dev/null | grep -q '"points_count"' && break; sleep 5; done
log "qdrant pid=$QP storage fs=$(stat -f -c %T /proc/$QP/root/qdrant/storage 2>/dev/null); bind source: $(grep -m1 ' /data/qdrant ' /proc/$(docker inspect -f '{{.State.Pid}}' Nomad)/mountinfo | cut -c1-120)"
[ -n "$QP" ] && { taskset -a -p -c 0-4,8-12 $QP >/dev/null; for t in $(ls /proc/$QP/task); do renice -n 10 -p $t >/dev/null 2>&1; done; log "affinity: $(taskset -pc $QP)"; }
nsenter -t $QP -n curl -s -m 60 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "
import sys, json
r = json.load(sys.stdin)['result']; o = r['config']['optimizer_config']
print('collection:', {k: r.get(k) for k in ('status','points_count','indexed_vectors_count','segments_count')}, 'optimizer:', str(r.get('optimizer_status'))[:120])
print('optimizer_config:', {k: o.get(k) for k in ('indexing_threshold','deleted_threshold')})"
grep -E 'VmRSS|RssAnon|RssFile|VmSwap' /proc/$QP/status
REPO=/mnt/nvme/appdata/cody/home/nomad-unraid/rootfs/usr/local/bin/nomad-embed
docker cp $REPO Nomad:/usr/local/bin/nomad-embed && docker exec Nomad chmod +x /usr/local/bin/nomad-embed && log "nomad-embed re-installed (gate NOT started)"
docker exec Nomad nomad-embed pause; docker exec Nomad nomad-embed status 2>&1 | sed -n 1,3p
log "== 05 done; gate is NOT running (queue paused); start it at the very end with: bash /data/home/tmp/nomad-embed-hot-apply.sh apply"
