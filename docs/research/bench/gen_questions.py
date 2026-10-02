import json, random, time, sys, re
from bench_lib import post_json
N_ART = int(sys.argv[1]) if len(sys.argv) > 1 else 3300
N_Q = int(sys.argv[2]) if len(sys.argv) > 2 else 300
rows = []
with open('/data/home/tmp/nomadindex/dataset/chunks_wikipedia.jsonl') as f:
    for line in f:
        try: o = json.loads(line)
        except Exception: break
        rows.append(o)
# first N_ART distinct articles (file order = random sample of articles)
arts = []; seen = set()
for o in rows:
    p = o['article_path']
    if p not in seen:
        seen.add(p); arts.append(p)
    if len(arts) >= N_ART: break
keep = set(arts[:N_ART])
corpus = [o for o in rows if o['article_path'] in keep]
# a chunk can be a query source if long enough
cand = [o for o in corpus if len(o['text']) >= 500]
rnd = random.Random(42); rnd.shuffle(cand)
base = "http://192.168.1.69:9292"
out = []
t0 = time.time()
for o in cand:
    if len(out) >= N_Q: break
    title = o.get('article_title'); sec = o.get('section_title')
    prompt = (f"Passage from the Wikipedia article \"{title}\" (section: {sec}):\n\n{o['text'][:1800]}\n\n"
              "Write ONE short, natural question (at most 20 words) that a person might type into a search box and that this passage answers. "
              "Do not copy more than three consecutive words from the passage. Do not mention 'the passage'. Output only the question.")
    body = {"model": "qwen3-vl:4b", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 60}
    try:
        d, dt = post_json(base + "/v1/chat/completions", body, timeout=120)
        q = d["choices"][0]["message"]["content"].strip().split("\n")[0].strip().strip('"')
    except Exception as e:
        print("err", str(e)[:100]); time.sleep(2); continue
    if len(q) < 15 or not q.endswith("?"): continue
    out.append({"qid": len(out), "chunk_i": o["i"], "article_path": o["article_path"], "question": q})
    if len(out) % 25 == 0: print(len(out), round(time.time() - t0), "s", q, flush=True)
json.dump({"corpus_i": [o["i"] for o in corpus], "questions": out}, open("nomadwiki_set.json", "w"))
print("done", len(out), "questions; corpus chunks", len(corpus), "articles", len(keep), "seconds", round(time.time() - t0))
