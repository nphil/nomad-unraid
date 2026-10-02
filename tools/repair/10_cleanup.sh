#!/bin/bash
# Final cleanup (run under the lock) - ONLY after the final verification passed and Main/Nitin approved (they did, conditional on it).
#   flock /tmp/agents-heavy.lock timeout 1200 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/10_cleanup.sh
# Deletes copies of NOMAD's vector DB that are no longer needed: the old array store CONTENTS (the 'qdrant' directories themselves stay:
# they are the mount-point entries of the container's /data/qdrant bind), my v1 NVMe dataset, the pre-validation snapshot, scratch dirs.
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/10_cleanup.log" 2>&1
log(){ echo "[$(date +%T)] $*"; }
abort(){ log "ABORT: $1"; exit 1; }
DS=nvme/appdata/nomad-qdrant-recovered
QP=$(ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'); [ -n "$QP" ] || abort "no qdrant"
NP=$(docker inspect -f '{{.State.Pid}}' Nomad); MI=$(grep -m1 ' /data/qdrant ' /proc/$NP/mountinfo)
echo "$MI" | grep -q "$DS" || abort "live Qdrant storage is NOT $DS ($MI)"
INFO=$(nsenter -t $QP -n curl -s -m 60 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print(r['status'], r['points_count'], r['indexed_vectors_count'])")
log "== 10 start; live qdrant: $INFO (status points indexed); storage: $(echo "$MI" | sed 's/.* - zfs //' | cut -c1-80)"
set -- $INFO; [ "$1" = green ] && [ "$2" -ge 3200000 ] && [ "$3" -ge $(( $2 * 98 / 100 )) ] || abort "live collection not green/complete"
free_now(){ echo "disk2 $(df -BM --output=avail /mnt/disk2 | tail -1 | tr -d ' ') | disk3 $(df -BM --output=avail /mnt/disk3 | tail -1 | tr -d ' ') | nvme pool $(zfs list -H -o avail nvme)"; }
log "free before: $(free_now)"; zfs list -o name,used,usedbysnapshots,usedbydataset,avail nvme nvme/appdata/nomad-qdrant nvme/appdata/nomad-qdrant-recovered 2>&1 | sed "s/^/  before: /"; df -BM /mnt/disk2 /mnt/disk3 /mnt/nvme | sed "s/^/  before: /"
for d in /mnt/disk2 /mnt/disk3; do
  p=$d/Stash/Nomad/qdrant; [ -d $p ] || continue
  MB=$(du -sm $p | cut -f1); find $p -mindepth 1 -delete; log "old array store on $d: removed ${MB} MB; left: $(ls -A $p | wc -l) entries (directory kept)"
done
if zfs list nvme/appdata/nomad-qdrant >/dev/null 2>&1; then
  [ -z "$(fuser -m /mnt/nvme/appdata/nomad-qdrant 2>/dev/null | tr -d ' ')" ] || abort "v1 dataset still in use (pids: $(fuser -m /mnt/nvme/appdata/nomad-qdrant 2>/dev/null))"
  U=$(zfs get -Hp -o value used nvme/appdata/nomad-qdrant); S=$(zfs get -Hp -o value usedbysnapshots nvme/appdata/nomad-qdrant)
  zfs list -H -t snapshot -o name -d 1 nvme/appdata/nomad-qdrant | sed 's/^/  v1 snapshot to be destroyed with it: /'
  zfs destroy -r nvme/appdata/nomad-qdrant && log "v1 NVMe dataset destroyed WITH its snapshots: freed $(( U / 1000000 )) MB (of which held by snapshots: $(( S / 1000000 )) MB)"
fi
for snap in $(zfs list -H -t snapshot -o name -d 1 $DS | grep -v '@autosnap_'); do
  U=$(zfs get -Hp -o value used $snap); zfs destroy $snap && log "manual/repair snapshot ${snap#*@} destroyed (held ${U:-0} bytes = $(( ${U:-0} / 1000000 )) MB)"
done
if [ -d /mnt/nvme/nomadindex-scratch ]; then MB=$(du -sm /mnt/nvme/nomadindex-scratch | cut -f1); rm -rf /mnt/nvme/nomadindex-scratch; log "scratch dir /mnt/nvme/nomadindex-scratch removed: ${MB} MB"; fi
log "free after: $(free_now)"; zfs list -o name,used,usedbysnapshots,usedbydataset,avail nvme nvme/appdata/nomad-qdrant-recovered 2>&1 | sed "s/^/  after: /"; zfs list -t snapshot -o name,used -r $DS 2>&1 | sed "s/^/  snapshots left: /"; df -BM /mnt/disk2 /mnt/disk3 /mnt/nvme | sed "s/^/  after: /"; ls -A /mnt/user/Stash/Nomad/qdrant | wc -l | sed "s/^/  entries left in the old share dir: /"
INFO2=$(nsenter -t $QP -n curl -s -m 60 http://127.0.0.1:6333/collections/nomad_knowledge_base | python3 -c "import sys,json; r=json.load(sys.stdin)['result']; print(r['status'], r['points_count'], r['indexed_vectors_count'])")
log "live qdrant after cleanup: $INFO2; nomad health: $(docker inspect -f '{{.State.Health.Status}}' Nomad)"; log "== 10 done"
