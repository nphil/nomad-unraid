#!/bin/bash
# Roll Nomad back to a previous template (restore backup, recreate, start). Run on the host under the heavy lock.
# usage: 99_rollback.sh /boot/config/plugins/dockerMan/backup-2026-10-02/my-Nomad.xml.pre-qdrant-recovered-HHMMSS   (-> v1 NVMe store)
# NEVER use the ...pre-qdrant-nvme-... backup: it has no NVMe Qdrant path, so Qdrant would start on the OLD array store and rewrite it
# (the old store is read-only forensic evidence: its temp_segments.HOLD-builder-DO-NOT-DELETE dir holds the original id table copy).
set -uo pipefail; R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair
B=${1:?backup template path}; [ -f "$B" ] || { echo "no such backup"; exit 1; }
grep -q 'Target="/data/qdrant"' "$B" || { echo "REFUSING: this template has no NVMe Qdrant path (Qdrant would start on the old array store)"; exit 1; }
cp -a "$B" /boot/config/plugins/dockerMan/templates-user/my-Nomad.xml
docker stop Nomad >/dev/null 2>&1
php $R/recreate.php > $R/logs/rollback-recreate.out 2>&1; docker start Nomad >/dev/null 2>&1
for i in $(seq 100); do H=$(docker inspect Nomad --format '{{.State.Health.Status}}'); [ "$H" = healthy ] && break; sleep 5; done; echo "health: $H"
docker inspect Nomad --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}; {{end}}'
echo "NEXT: re-run /data/home/tmp/nomad-embed-hot-apply.sh apply from the Cody container"
