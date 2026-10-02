"""Pure GPU speed (llama-bench pp512/pp2048, ub 2048), per model; lock-guarded; ~20-40 s per model."""
import json, sys, time
import srv_locked as srv
from models_cfg import MODELS
FILES = ["nomic-embed-text-v1.5.Q8_0.gguf", "nomic-embed-text-v1.5.f32.gguf", "nomic-embed-text-v1.5.f16.gguf",
         "embeddinggemma-300M-Q8_0.gguf", "embeddinggemma-300M-F32.gguf", "v5-nano-retrieval-Q8_0.gguf",
         "granite-embedding-english-r2.Q8_0.gguf", "arctic-embed-m-v2-q8_0.gguf", "arctic-embed-l-v2-q8_0.gguf",
         "bge-m3-q8_0.gguf", "Qwen3-Embedding-0.6B-Q8_0.gguf", "nomic-embed-text-v2-moe.Q8_0.gguf"]
for rd in range(2):
    for f in (FILES if rd == 0 else list(reversed(FILES))):
        ql = srv.wait_quiet(max_load=8.0, max_wait=900)
        l0 = srv.load1()
        r = srv.bench(f, extra="-p 512,2048 -n 0 -ngl 99 -r 3 -b 2048 -ub 2048")
        l1 = srv.load1()
        rec = {"file": f, "round": rd, "load1_before": l0, "load1_after": l1, "provisional": max(l0, l1) >= 8, "result": r}
        print(json.dumps(rec)[:600], flush=True); open("exp6_llamabench.jsonl", "a").write(json.dumps(rec) + "\n")
