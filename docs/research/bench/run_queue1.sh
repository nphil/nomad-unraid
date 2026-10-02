#!/bin/bash
cd /data/home/tmp/nomadindex/bench
for spec in "nomic15 nomadfix" "gemma300 native,nomadfix" "granite_r2 none" "jina5nano native,nomadfix"; do
  set -- $spec
  echo "=== $(date +%T) exp5 $1 $2"
  nice -n 15 python3 exp5_nomadwiki.py $1 $2 2>&1 | tail -15
done
echo "=== $(date +%T) queue1 done"
