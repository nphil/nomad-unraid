#!/bin/bash
# Recovery step 1 (heavy I/O; run under the lock):
#   flock /tmp/agents-heavy.lock timeout 1500 bash /mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/03_recover_copy.sh
# Builds a RECOVERED Qdrant store on a NEW NVMe dataset from the pristine array copy:
#   everything except the broken big segment / temp_segments / *.deleted, plus the big segment rebuilt from the leftover builder folder.
# Resumable (files with the same size+mtime are skipped). The array copy is only READ.
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/03_recover_copy.log" 2>&1
DS=nvme/appdata/nomad-qdrant-recovered; MP=/mnt/nvme/appdata/nomad-qdrant-recovered
O2=/mnt/disk2/Stash/Nomad/qdrant; O3=/mnt/disk3/Stash/Nomad/qdrant
CB=collections/nomad_knowledge_base/0; BASE=c98bf53f-759c-4d00-9749-5b1c1fcf4033; BLD=$CB/temp_segments.HOLD-builder-DO-NOT-DELETE/segment_builder_n3vl4Q
SEG=$MP/$CB/segments/$BASE
log(){ echo "[$(date +%T)] $*"; }
log "== 03 start; load $(cut -d' ' -f1-3 /proc/loadavg)"
AV=$(free -m | awk '/^Mem:/{print $7}'); [ "$AV" -ge 10000 ] || { log "ABORT <10 GB RAM available ($AV MB)"; exit 1; }
if ! zfs list $DS >/dev/null 2>&1; then
  zfs create -o mountpoint=$MP -o recordsize=16K -o primarycache=metadata -o atime=off $DS || { log "ABORT: zfs create failed"; exit 1; }
  log "dataset created"
fi
mkdir -p "$MP"

# copy_tree SRC DST  (bash-glob skip patterns for the big-file loop come from SH_EXC, rsync excludes from RS_EXC)
RS_EXC=(); SH_EXC=()
copy_tree(){
  local src=$1 dst=$2 n=0 skipped=0 bytes=0 f rel d sz
  mkdir -p "$dst"
  rsync -aS --numeric-ids --max-size=4M "${RS_EXC[@]}" "$src"/ "$dst"/ || { log "ABORT: small-file rsync failed ($src)"; exit 1; }
  while IFS= read -r -d '' f; do
    rel=${f#$src/}; local skip=0 p
    for p in "${SH_EXC[@]}"; do case "$rel" in $p) skip=1;; esac; done
    [ $skip = 1 ] && continue
    d=$dst/$rel; sz=$(stat -c %s "$f")
    if [ -f "$d" ] && [ "$(stat -c %s "$d")" = "$sz" ] && [ "$(stat -c %Y "$d")" = "$(stat -c %Y "$f")" ]; then skipped=$((skipped+1)); continue; fi
    mkdir -p "$(dirname "$d")"
    dd if="$f" of="$d.part" bs=16M iflag=direct conv=sparse status=none || { log "ABORT: dd failed on $f"; exit 1; }
    truncate -s "$sz" "$d.part"; touch -r "$f" "$d.part"; mv -f "$d.part" "$d"
    n=$((n+1)); bytes=$((bytes+sz)); [ $((n % 50)) -eq 0 ] && log "  $src: copied $n big files ($((bytes/1000000)) MB), skipped $skipped"
  done < <(find "$src" -type f -size +4M -print0)
  log "copied $src -> $dst: $n big files ($((bytes/1000000)) MB), skipped(already ok) $skipped"
}

log "-- phase 1: rest of the old store (everything except broken big segment, temp_segments, *.deleted)"
RS_EXC=(--exclude="$CB/temp_segments*" --exclude="$CB/segments/$BASE" --exclude="$CB/segments/*.deleted")
SH_EXC=("$CB/temp_segments*/*" "$CB/segments/$BASE/*" "$CB/segments/*.deleted/*")
copy_tree $O2 $MP; copy_tree $O3 $MP

log "-- phase 2: big segment storages from the leftover builder folder (disk3)"
RS_EXC=(); SH_EXC=()
copy_tree $O3/$BLD/payload_storage $SEG/payload_storage
copy_tree $O3/$BLD/vector_storage $SEG/vector_storage

log "-- phase 3: id table conversion + segment metadata"
python3 $R/recover_convert.py $SEG || { log "ABORT: conversion failed"; exit 1; }

log "-- phase 4: collection config offline edit (no automatic HNSW build before dedupe)"
CFG=$MP/collections/nomad_knowledge_base/config.json
[ -f $R/config.json.orig-recovery ] || cp -a $CFG $R/config.json.orig-recovery
python3 - "$CFG" <<'PY'
import json, sys
p = sys.argv[1]; c = json.load(open(p)); o = c["optimizer_config"]
print("before:", {k: o.get(k) for k in ("indexing_threshold", "deleted_threshold")})
o["indexing_threshold"] = 0; o["deleted_threshold"] = 1.0
json.dump(c, open(p, "w")); print("after: ", {k: json.load(open(p))["optimizer_config"].get(k) for k in ("indexing_threshold", "deleted_threshold")})
PY

log "-- checks"
find $MP -name '*.part' | head -3
echo "segments:"; ls $MP/$CB/segments/; echo "wal files: $(ls $MP/$CB/wal | wc -l)"
du -sh $MP; zfs list -o name,used,avail $DS
for f in payload_storage/tracker.dat payload_storage/bitmask.dat payload_storage/gaps.dat vector_storage/vectors/status.dat; do
  echo "$f $(stat -c %s $SEG/$f) vs builder $(stat -c %s $O3/$BLD/$f)"
done
echo "vector chunks: $(ls $SEG/vector_storage/vectors | grep -c chunk_) (builder $(ls $O3/$BLD/vector_storage/vectors | grep -c chunk_)); payload pages: $(ls $SEG/payload_storage | grep -c page_) (builder $(ls $O3/$BLD/payload_storage | grep -c page_))"
log "== 03 done"
