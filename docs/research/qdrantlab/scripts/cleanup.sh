#!/bin/bash
# emergency: stop every qdrantlab container, end session loops, kill queued lock waiters of this lab (never touches other agents)
ssh unraid 'rm -f /tmp/qlab-go-* /tmp/qlab-mem-*; pkill -f "[f]lock /tmp/agents-heavy.lock .*nomadindex-qdrantlab"; for c in $(docker ps -aq --filter name=nomadindex-qdrantlab); do docker rm -f $c; done; docker ps -a --format "{{.Names}}" | grep qdrantlab || echo "no qdrantlab containers left"'
