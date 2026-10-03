#!/usr/bin/env python3
"""Plan the removal of library B's points that library A already covers: every B point whose article_path
also exists in A. B-only articles are kept. Reads only. Run on the Unraid host.

  python3 dup_library_plan.py <A source substring> <B source substring>

Writes $WORK/dup_<B>_ids.txt for `IDS=... python3 scrap_delete.py`.
"""
import json, os, subprocess, sys

A, B = sys.argv[1], sys.argv[2]
WORK = os.environ.get("WORK", "scrap-work"); os.makedirs(WORK, exist_ok=True)
COL = "nomad_knowledge_base"
QP = subprocess.check_output("pgrep -x qdrant | head -1", shell=True).decode().strip()


def q(path, body):
    cmd = ["nsenter", "-t", QP, "-n", "curl", "-s", "-m", "600", "-H", "content-type: application/json", "-d", json.dumps(body), "http://127.0.0.1:6333" + path]
    r = json.loads(subprocess.check_output(cmd))
    assert "result" in r, r
    return r["result"]


hits = {h["value"]: h["count"] for h in q(f"/collections/{COL}/facet", {"key": "source", "limit": 100})["hits"]}
sa = [s for s in hits if A in s]; sb = [s for s in hits if B in s]
assert len(sa) == 1 and len(sb) == 1, (sa, sb)
sa, sb = sa[0], sb[0]


def scroll(source):
    off = None
    while True:
        body = {"limit": 5000, "with_payload": ["article_path"], "with_vector": False, "filter": {"must": [{"key": "source", "match": {"value": source}}]}}
        if off is not None:
            body["offset"] = off
        r = q(f"/collections/{COL}/points/scroll", body)
        yield from r["points"]
        off = r.get("next_page_offset")
        if off is None:
            return


in_a = {p["payload"].get("article_path") for p in scroll(sa)}
ids, keep = [], 0
for p in scroll(sb):
    if p["payload"].get("article_path") in in_a:
        ids.append(p["id"])
    else:
        keep += 1
open(f"{WORK}/dup_{B}_ids.txt", "w").write("".join(f"{i}\n" for i in ids))
print(f"A {sa}: {hits[sa]} points, {len(in_a)} articles\nB {sb}: {hits[sb]} points\nto delete (article exists in A): {len(ids)}; kept (B-only articles): {keep}")
