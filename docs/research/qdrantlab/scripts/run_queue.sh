#!/bin/bash
# usage: run_queue.sh <name> "<args1>" "<args2>" ...   each arg-string = one run_v.py invocation (one lock hold); retries once on failure
cd /data/home/tmp/nomadindex/qdrantlab
export OPENBLAS_NUM_THREADS=2
NAME=$1; shift
LOG=logs/queue_$NAME.log
for spec in "$@"; do
  for attempt in 1 2; do
    echo "=== $(date +%T) attempt $attempt: run_v.py $spec" | tee -a $LOG
    nice -n 15 python3 scripts/run_v.py $spec >> $LOG 2>&1 && break
    rc=$?; echo "=== $(date +%T) rc=$rc" | tee -a $LOG
    [ $rc -eq 4 ] && break
  done
done
echo "=== $(date +%T) queue $NAME done" | tee -a $LOG
