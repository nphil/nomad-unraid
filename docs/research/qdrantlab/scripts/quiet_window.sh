#!/bin/bash
# One-shot driver for Main's quiet window (NOT executed yet). Each step takes /tmp/agents-heavy.lock itself (inside qlab.Lab) for the
# life of its own throw-away qdrant/qdrant:v1.16.3 container; timing phases refuse to run if the host 1-min load is >= 8.
# usage: quiet_window.sh [prep|core|extras|timing|all]    (default all)   logs: logs/quiet_<step>.log
set -u
cd /data/home/tmp/nomadindex/qdrantlab
export OPENBLAS_NUM_THREADS=2
STEP=${1:-all}
run() { echo "=== $(date +%T) $*" | tee -a logs/quiet_$STEP.log; nice -n 15 "$@" >> logs/quiet_$STEP.log 2>&1 || echo "=== rc=$? for $*" | tee -a logs/quiet_$STEP.log; }
if [[ $STEP == prep || $STEP == all ]]; then      # local only, nice 19, no lock: ~15 min CPU
  mkdir -p /tmp/qlab-work
  [ -f /tmp/qlab-work/syn_vectors.f32 ] || nice -n 19 python3 scripts/gen_synth.py --n 500000 --text-median 600 --out /tmp/qlab-work/syn
  for N in 100000 300000; do nice -n 19 python3 scripts/run_v.py --variant V0 --n $N --phase prebuild --procs 2; done
fi
if [[ $STEP == core || $STEP == all ]]; then      # size / RAM / recall (+ provisional timings) at 100k, one lock hold per variant
  for V in V0 V1 V2 V3; do run python3 scripts/run_v.py --variant $V --n 100000 --phase all; done
  run python3 scripts/inplace.py --n 100000 --patch v1
  run python3 scripts/fidelity.py --sets nomadwiki,scifact,nfcorpus,arguana     # needs bench/emb/nomic15_nomadfix_<set>_{docs,queries}.npy
fi
if [[ $STEP == extras || $STEP == all ]]; then    # scale + anon-heap attribution
  for V in V0 V1 V2 V3; do run python3 scripts/run_v.py --variant $V --n 300000 --phase all; done
  run python3 scripts/run_v.py --variant V1 --n 300000 --phase all --cold 700m --tag .cold
  for V in E_plain E_noidx E_idxdisk E_intid; do run python3 scripts/run_v.py --variant $V --n 100000 --phase all --light; done
fi
if [[ $STEP == timing || $STEP == all ]]; then    # speed numbers on the retained collections (load must be < 8)
  for V in V0 V1 V2 V3; do for N in 100000 300000; do run python3 scripts/run_v.py --variant $V --n $N --phase timing; done; done
fi
echo "=== $(date +%T) done $STEP" | tee -a logs/quiet_$STEP.log
