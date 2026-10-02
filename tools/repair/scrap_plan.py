#!/usr/bin/env python3
"""Plan the removal of "scrap" chunks from NOMAD's Qdrant collection. Reads only; deletes nothing.

Scrap = a chunk of MAXC characters or fewer (default 20) that is one of
  A  number-only or empty text   (vote and answer counts of StackExchange tag pages, page numbers)
  B  a tail fragment (chunk_index > 0) of a longer text ('media files.', timestamps); the overlap of the
     previous chunk already holds it
  C  a title-only stub: the text is exactly the article or section title (no information beyond the title)
Everything else that short is KEPT (class D): short real facts such as MedlinePlus drug brand names or
iFixit spec values. NOMAD's ingest filter (MIN_CHUNK_CHARS, see the entrypoint) uses the same rules.

Run on the Unraid host, inside Qdrant's network namespace, niced and under the heavy lock:
  flock /tmp/agents-heavy.lock nice -n 15 ionice -c3 python3 scrap_plan.py [MAXC]
Writes to $WORK (default ./scrap-work): scrap_ids.txt (A+B+C), scrap_rows.jsonl, scrap_summary.json.
"""
import collections, json, os, random, re, subprocess, sys, time

MAXC = int(sys.argv[1]) if len(sys.argv) > 1 else 20
WORK = os.environ.get("WORK", "scrap-work")
os.makedirs(WORK, exist_ok=True)
COL = "nomad_knowledge_base"
QP = subprocess.check_output("pgrep -x qdrant | head -1", shell=True).decode().strip()


def q(path, body):
    cmd = ["nsenter", "-t", QP, "-n", "curl", "-s", "-m", "600", "-H", "content-type: application/json",
           "-d", json.dumps(body), "http://127.0.0.1:6333" + path]
    return json.loads(subprocess.check_output(cmd))


INC = ["source", "char_count", "text", "article_title", "section_title", "article_path", "chunk_index", "total_chunks", "active"]
rows, off, t0 = [], None, time.time()
while True:
    body = {"limit": 5000, "with_payload": {"include": INC}, "with_vector": False,
            "filter": {"must": [{"key": "char_count", "range": {"lte": MAXC}}]}}
    if off is not None:
        body["offset"] = off
    r = q(f"/collections/{COL}/points/scroll", body)["result"]
    rows += [(p["id"], p["payload"]) for p in r["points"]]
    off = r.get("next_page_offset")
    if off is None:
        break
print(f"scanned {len(rows)} points with char_count <= {MAXC} in {time.time() - t0:.0f}s", flush=True)

NUMBER = re.compile(r"[\d.,%+\-\s]*")


def klass(pl):
    t = (pl.get("text") or "").strip()
    a, s = (pl.get("article_title") or "").strip().lower(), (pl.get("section_title") or "").strip().lower()
    if NUMBER.fullmatch(t):
        return "A number-only or empty"
    if (pl.get("chunk_index") or 0) > 0:
        return "B tail fragment of a longer text"
    if t.lower() in (a, s):
        return "C title-only stub"
    return "D short real text (kept)"


lib = lambda pl: os.path.basename(pl.get("source", "?"))
cls = [(i, pl, klass(pl)) for i, pl in rows]
by_class = collections.Counter(k for _, _, k in cls)
by_lib = {k: collections.Counter(lib(pl) for _, pl, kk in cls if kk == k).most_common() for k in by_class}
bucket = lambda n: "0" if n == 0 else "1-5" if n <= 5 else "6-10" if n <= 10 else "11-15" if n <= 15 else "16-20"
by_bucket = collections.Counter((k[0], bucket(pl.get("char_count") or 0)) for _, pl, k in cls)
random.seed(1)
samples = {}
for k in by_class:
    pool = [(i, pl) for i, pl, kk in cls if kk == k]
    samples[k] = [{"lib": lib(pl), "chars": pl.get("char_count"), "text": pl.get("text"), "article": pl.get("article_title"),
                   "section": pl.get("section_title"), "chunk": f"{pl.get('chunk_index')}/{pl.get('total_chunks')}"}
                  for _, pl in random.sample(pool, min(30, len(pool)))]
delete = [i for i, _, k in cls if not k.startswith("D")]
summary = {"max_chars": MAXC, "tiny_total": len(rows), "to_delete": len(delete), "kept_short_real_text": by_class["D short real text (kept)"],
           "by_class": dict(by_class), "by_length_bucket": {f"{a} {b}": c for (a, b), c in sorted(by_bucket.items())},
           "by_library": by_lib, "samples": samples}
json.dump(summary, open(f"{WORK}/scrap_summary.json", "w"), indent=1, ensure_ascii=False)
open(f"{WORK}/scrap_ids.txt", "w").write("".join(f"{i}\n" for i in delete))
with open(f"{WORK}/scrap_rows.jsonl", "w") as f:
    for i, pl, k in cls:
        f.write(json.dumps({"id": i, "class": k[0], **{x: pl.get(x) for x in INC}}, ensure_ascii=False) + "\n")
print(json.dumps({k: summary[k] for k in ("tiny_total", "to_delete", "kept_short_real_text", "by_class", "by_length_bucket")}, indent=1))
