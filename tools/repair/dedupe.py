#!/usr/bin/env python3
"""Exact-duplicate cleanup for NOMAD's Qdrant collection (stdlib only). Run on the Unraid host inside Qdrant's netns, niced:
   nsenter -t <qdrant pid> -n nice -n 10 python3 dedupe.py scan | plan | apply
 scan : scroll all points (light payload), group by (source, article_path, section_title, chunk_index, char_count) -> dup_candidates.jsonl
 plan : fetch the texts of candidate members; exact key + text equality; keep the NEWEST created_at per exact group -> delete_ids.txt + summary
 apply: delete the planned ids (batches of 2000, wait=true)."""
import json, sys, time, hashlib, collections, urllib.request
BASE = "http://127.0.0.1:6333"; COL = "nomad_knowledge_base"
R = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair"
def call(path, body=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    for a in range(5):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers={"content-type": "application/json"}, method="POST" if body is not None else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
        except Exception as e:
            print("retry", a, path, str(e)[:150], flush=True); time.sleep(5 * (a + 1))
    raise RuntimeError("giving up on " + path)
INC = ["source", "article_path", "section_title", "chunk_index", "char_count", "created_at"]
def scan():
    t0 = time.time(); off = None; n = 0; first = {}; dup = collections.defaultdict(list)
    while True:
        r = call(f"/collections/{COL}/points/scroll", {"limit": 2000, "offset": off, "with_payload": {"include": INC}, "with_vector": False})["result"]
        for p in r["points"]:
            pl = p["payload"]
            k = hash((pl.get("source"), pl.get("article_path"), pl.get("section_title"), pl.get("chunk_index"), pl.get("char_count")))
            rec = (p["id"], pl.get("created_at") or 0)
            if k in first:
                if k not in dup: dup[k].append(first[k])
                dup[k].append(rec)
            else: first[k] = rec
        n += len(r["points"]); off = r.get("next_page_offset")
        if (n // 2000) % 100 == 0: print(f"scanned {n:,} points, candidate groups {len(dup):,}, {time.time()-t0:.0f}s", flush=True)
        if off is None: break
    with open(f"{R}/dup_candidates.jsonl", "w") as f:
        for g in dup.values(): f.write(json.dumps(g) + "\n")
    print(f"SCAN DONE: {n:,} points, {len(dup):,} candidate groups, {sum(len(g) for g in dup.values()):,} members, {time.time()-t0:.0f}s", flush=True)
def digest(pl):
    s = "\x1f".join(str(pl.get(k)) for k in ("source", "article_path", "section_title", "chunk_index")) + "\x1e" + (pl.get("text") or "")
    return hashlib.blake2b(s.encode(), digest_size=16).digest()
def plan():
    t0 = time.time(); groups = [json.loads(l) for l in open(f"{R}/dup_candidates.jsonl")]
    ids = [i for g in groups for i, _ in g]; dg = {}; src = {}
    for s in range(0, len(ids), 400):
        res = call(f"/collections/{COL}/points", {"ids": ids[s:s+400], "with_payload": {"include": ["text", "source", "article_path", "section_title", "chunk_index"]}, "with_vector": False})["result"]
        for p in res: dg[p["id"]] = digest(p["payload"]); src[p["id"]] = (p["payload"].get("source") or "").rsplit("/", 1)[-1]
        if (s // 400) % 250 == 0: print(f"fetched {s:,}/{len(ids):,} {time.time()-t0:.0f}s", flush=True)
    delete = []; per = collections.Counter(); mixed = 0; missing = 0
    for g in groups:
        sub = collections.defaultdict(list)
        for i, ca in g:
            if i not in dg: missing += 1; continue
            sub[dg[i]].append((-ca, i))
        if len(sub) > 1: mixed += 1
        for members in sub.values():
            if len(members) > 1:
                members.sort()
                for _, i in members[1:]: delete.append(i); per[src[i]] += 1
    open(f"{R}/delete_ids.txt", "w").write("\n".join(delete) + ("\n" if delete else ""))
    summ = {"candidate_groups": len(groups), "groups_with_different_texts_kept": mixed, "ids_missing_on_fetch": missing, "to_delete": len(delete), "by_source": per.most_common()}
    json.dump(summ, open(f"{R}/results/dedupe_plan.json", "w"), indent=1); print("PLAN DONE", json.dumps(summ)[:1500], f"{time.time()-t0:.0f}s", flush=True)
def apply():
    ids = [l.strip() for l in open(f"{R}/delete_ids.txt") if l.strip()]; t0 = time.time()
    before = call(f"/collections/{COL}/points/count", {"exact": True})["result"]["count"]
    for s in range(0, len(ids), 2000):
        call(f"/collections/{COL}/points/delete?wait=true", {"points": ids[s:s+2000]})
        if (s // 2000) % 50 == 0: print(f"deleted {min(s+2000, len(ids)):,}/{len(ids):,} {time.time()-t0:.0f}s", flush=True)
    after = call(f"/collections/{COL}/points/count", {"exact": True})["result"]["count"]
    print(f"APPLY DONE: points {before:,} -> {after:,} (planned {len(ids):,}), {time.time()-t0:.0f}s", flush=True)
if __name__ == "__main__":
    {"scan": scan, "plan": plan, "apply": apply}[sys.argv[1]]()
