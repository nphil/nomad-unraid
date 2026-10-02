#!/bin/bash
# Recall diagnostic (run under the lock, ~3-5 min, CPU-moderate): flock /tmp/agents-heavy.lock timeout 900 bash <this>
set -uo pipefail
R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair; mkdir -p $R/logs; exec >>"$R/logs/11_recall_diag.log" 2>&1
QP=$(ps -eo pid,args | awk '$2=="./qdrant"{print $1; exit}'); [ -n "$QP" ] || { echo "no qdrant"; exit 1; }
echo "[$(date +%T)] == 11 start; load $(cut -d' ' -f1-3 /proc/loadavg)"
nsenter -t $QP -n taskset -c 0-4,8-12 nice -n 5 python3 $R/recall_diag.py
echo "[$(date +%T)] == 11 done"
