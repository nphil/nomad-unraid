# NOMAD AI index: how big, how long, and is there a better embedding model?

Measured on BeastNAS on 2026-10-01 by NomadIndexAgent (with three helper agents). Plain-language answer first, tables and sources after.

> **Update, 2026-10-02 (same day).** The decision taken was to repair the existing nomic collection in place. It was repaired that afternoon: storage moved to NVMe, the lost id table of the big block recovered, 868,176 exact duplicates removed, int8 compression and the HNSW index built; searches now take about 3 ms. What happened, and the rules that follow from it, are in `qdrant-storage-and-recovery.md`. The measurements below are unchanged, but the statements about the search not working, the 4.11 M chunk count and "whether Qdrant starts cleanly on the old data" describe the situation before the repair. The granite model was tested separately on the live host afterwards: +4 to +5 nDCG points on BEIR but only +0.3 to +0.7 recall points on NOMAD-style questions (the agreed bar was +3), and 25 to 30 % slower, so nomic stays for now.

**Status of the numbers.** Sizes, counts and chunk statistics are measured and do not depend on how busy the machine is. **All speed numbers are PROVISIONAL**: every run happened while the host load average was 20 to 130 (valid: below 8). The runs that need a quiet host are listed in section 8; they will replace the provisional numbers.

Tags used below: **[M]** measured on this system, **[P]** read from production Qdrant/NOMAD logs, **[S]** sampled with NOMAD's own code, **[D]** documentation/source code (linked), **[I]** my inference (not measured), **[prov]** provisional speed.

---

## 1. The answers

1. **What is in the index today.** 4.11 million "chunks" (pieces of text of about 2,000 characters, each stored as a list of 768 numbers). It takes 42 GB on the array's spinning disks, but only about 21 GB is real data: about 20 GB is leftover garbage from a clean-up that failed at 05:59 today. About 0.85 million of the chunks are duplicates (the same text written twice by NOMAD's job chains), and only 0.26 million are Wikipedia. [M/P]
2. **The AI search is not working right now.** Three test searches against the live database ran into its 60-second limit and failed. Almost every chunk (3.99 M of 4.11 M) sits in one unindexed block on the spinning disks, so each search tries to read about 12 GB. More indexing will not fix this; the database layout has to change (section 6). [M]
3. **How big when everything is indexed?** NOMAD would create about **25.4 million chunks** from your 57 libraries: **140 GB** on disk the way NOMAD sets Qdrant up today (160 GB with the compact layout I recommend) and about 13 billion tokens (a token is a word piece) of text for the GPU. **78% of that is the full English Wikipedia alone**: 19.8 M chunks, 111 to 126 GB. Everything *except* the full Wikipedia is about **5.3 million chunks, 27 to 31 GB**. [S/P]
4. **Time.** The GPU is not what makes NOMAD slow; NOMAD's design is. For the full Wikipedia, NOMAD's job chain re-opens the 124 GB file for every 50 pages (99 s median) and re-reads the file from the start each time, which adds up to 193 days of opening alone plus years of walking: **it cannot finish, whatever model you use.** Even a perfect pipeline needs about 11 days of pure GPU time for Wikipedia (91 nights of a 3-hour window) at today's [prov] speed. The rest of your libraries need about 2.2 days of GPU time (17 nights); NOMAD as shipped would take 40 to 90 nights. [S/P/prov]
5. **Is there a better embedding model?** **Yes.** nomic-embed-text-v1.5 is the weakest of the 30 models compared on English retrieval: 47.97 against 55.7 to 58.8 for models of the same GPU cost and the same vector size (768). The best fit for NOMAD is **granite-embedding-english-r2** (56.43, Apache-2.0, 8k context, needs no prompt prefix); the quality leader of the same class is jina-embeddings-v5-text-nano (58.80, non-commercial licence). Speed on the P40 of these candidates is not measured validly yet (section 8). [L from the public MTEB results, see section 4]
6. **Recommendation (one decision).** Throw the old 4.1 M-point collection away and **build a fresh index on the NVMe disk with granite-embedding-english-r2, for all libraries except the full Wikipedia, plus the "best 50,000 Wikipedia articles" ZIM (`wikipedia_en_top_nopic`, 2.75 GB) for general knowledge.** Expected size about 6.7 M chunks, 41 GB on NVMe, 0.35 to 6.7 GB of RAM depending on layout; about 28 nights of the 3-hour window if the GPU were the only limit (about 4 weeks), more like 7 weeks (46 nights) with NOMAD's pipeline. Details, steps, downtime and the fallback ("nomic stays") are in section 6. Before the big re-index, a 1-hour acceptance test in the quiet window must confirm the new model (section 6.4).

**Next step for you:** decide "fresh index with a new model" (recommended) or "keep nomic, repair in place", and approve a quiet window of about 3 hours for the tests in section 8.

---

## 2. What I measured

### 2.1 How NOMAD builds the index (v1.35.0 source, all line numbers in `admin/app/...`)

- A ZIM is processed as a chain of jobs of **50 pages**; each job opens the archive, then walks `iterByPath()` from entry 0 and skips `startOffset` pages before it extracts 50 (`services/zim_extraction_service.ts` l.44-173; `constants/zim_extraction.ts`). Two jobs run at a time (`commands/queue/work.ts`).
- Chunking: a page is cut into sections only if it has at least two headed sections with 100+ characters; **on Wikipedia 100% of 13,008 sampled pages fail that test**, so the whole page text becomes one text that is cut into 3,000-character windows with 300 overlap (`services/rag_service.ts` l.388-396). [S]
- Every chunk is prefixed `search_document: `, embedded through `/v1/embeddings` (at most 8 per request, one request per page) and written with **one Qdrant upsert per page**, including the full text, a keyword string, archive metadata and the 768-number vector (l.349-532). Point ids are random, so a repeated job writes duplicates.
- The vector size (768), model name (`nomic-embed-text:v1.5`) and the two prefixes are constants in the code; the relevance floor (0.62) is a setting. Search asks Qdrant for 15 hits with score 0.3 or more (l.1030).
- Real pages versus NOMAD's progress bar: Wikipedia has **8,425,786 real pages**; the 18,982,214 that NOMAD divides by includes 10,556,428 redirects, so "0.5% done" is really **1.2% of the pages** (99,350). The bar is also wrong for ifixit (103,480 shown, 253,845 real, so 38.6% not 95%) and electronics (324,255 vs 352,283). [S]

### 2.2 What is in Qdrant (v1.16.3) today

| Item | Value | Tag |
|---|---|---|
| Collection | `nomad_knowledge_base`, 768-d Cosine, HNSW m16/ef100, no quantization, payload on disk, defaults for everything else | M |
| Points | 4,110,408 (4,110,669 a few minutes later) | M |
| Layout | 1 unindexed "plain" segment with 3,989,177 points (20.3 GB), 7 indexed segments of ~16.8k points, 1 growing segment of 3,257 | M |
| Health | status **red**: the clean-up cannot remove `*.deleted` ("Directory not empty"), no index build since 05:59; ~20 GB `temp_segments` leftover | M |
| Location | the Unraid user share `/mnt/user/Stash/Nomad/qdrant`, which exists on disk2 (3.5 GB), disk3 (38 GB) and an empty copy on disk5; array disks, same disk3 as the Wikipedia ZIM | M |
| Disk per chunk (big segment) | vector 3,072 B + stored payload 2,181 B + payload indexes 91 B + id 35 B + HNSW ~54 B = **~5.4 KB** (the README's "10 KB" counted the 20 GB garbage) | M |
| Payload | JSON 3,964 B per Wikipedia chunk (text 2,204; keywords 1,106; archive 181; titles 193; source 61; other 220); Qdrant stores it at 0.60 of that (compression) | S/M |
| RAM | Qdrant 5.05 GB heap (RssAnon) + 0.17 GB mapped + 0.3 GB swapped = ~1.4 KB of heap per point; the whole Nomad container 7.1 GB | M |
| Search | 3 of 3 NOMAD-style searches: HTTP 500 "Search timed out after 59.99 s" | M |
| Request latency (15 h telemetry) | upsert avg 426 ms (max 367 s, 100,460 calls); `setPayload` backfill avg 155 s (max 3,290 s, 507 calls); index creation avg 4.8 s (2,040 calls) | M |

Likely cause of the stuck clean-up (Lab, from Qdrant issues #3080/#6371): the data is reached through Unraid's `shfs` (FUSE) user share, which Qdrant's documentation says it does not support ("block-level storage with a POSIX file system"). Fix: use `/mnt/nvme/...` (direct) or one `/mnt/diskN`, never `/mnt/user`. [D, causal link is [I]]

**Warning:** a restart of the Nomad container restarts Qdrant. In v1.16.3 loading a collection with an undeletable `*.deleted` directory returns an error instead of continuing [D, source l.350-365]; I could not reproduce it. Do not restart before the plan in section 6 is executed.

### 2.3 Where NOMAD's time goes today (407 jobs in the last 12 h of `admin.log`) [P]

| Library | open archive (median) | skip + extract (median) | embed + upsert (median) | chunks/job |
|---|---:|---:|---:|---:|
| Wikipedia (124 GB) | **99 s** (mean 164) | 57 s | 22 s | ~203 |
| ifixit | 51 s | 24 s | 22 s | ~224 |
| wikibooks nopic / maxi | 11 s / 0.3 s | 32 s / 2 s | 21 s | ~90 |
| electronics SE | 0.2 s | 12 s | 24 s | ~199 |
| diy SE | 0.1 s | 9 s | 141 s | ~541 |
| Wikipedia medicine | 0.3 s | 22 s | 24 s | ~190 |

NOMAD's overall output today: about **2.4 chunks per second** (100,316 chunks in the 11.8 h covered by the log, 407 jobs), dropping to about 1.5 per second over the last 2.4 hours; embedding plus upsert costs about **0.2 s per chunk**, of which the GPU needs about 0.05 s. A cold `new Archive()` of the Wikipedia file measured 336 to 338 s (strace: libzim preloads ~1,500 dirent ranges with dependent random reads, plus a 217 MB table, on a 98%-busy array disk). [P/S/prov]

### 2.4 GPU speed (nomic-embed-text-v1.5 Q8_0 on the Tesla P40) [prov]

| Test | chunks/s | tokens/s | host load / GPU busy |
|---|---:|---:|---|
| Own container, 1 client, 1 chunk per request (what NOMAD does) | **21.3** | **11,400** | 45 / 27-83% |
| Own container, 4 clients x 8 | 17.0 | 8,900 | 43 / 92-97% |
| Own container, prod-like config, 8 clients x 8 | 23.2 | 12,100 | 57-61 / ~95% |
| Production endpoint via llama-swap, batch 1 to 64, 1 to 4 clients | 7 to 19 | 3,900 to 10,500 | 65-75 / 98% |
| llama-bench pp512 (pure GPU) | n/a | 9,155 +/- 629 | 60 |

Average NOMAD chunk = 520 to 545 tokens (nomic tokenizer; 4.0 characters per token). Larger batches did **not** help (the P40 is compute-bound at about 11k tokens/s with Scrypted and other tenants on it): the "proper batching" gain is about zero for the GPU part. VRAM: 400 MB (prod), 504-518 MB in my config. [prov]

---

## 3. Estimates

### 3.1 By library (NOMAD's chunking, nomic-class model)

Tags: S = sampled with NOMAD's exact code (confidence interval in the data files), P = production count of an already-finished library, H = heuristic by library type (to be sampled in the quiet window). Disk uses the compact layout (vector + int8 copy + stored payload + indexes).

| Library | real pages | chunks (est.) | tag | tokens/chunk | disk GB |
|---|---:|---:|:--:|---:|---:|
| wikipedia_en_all_maxi_2026-02 | 8,425,786 | **19,756,680** [19.27M-20.27M] | S | 545 | 126.4 |
| electronics.stackexchange | 352,283 | 1,031,459 [0.90M-1.16M] | S | 235 | 5.5 |
| diy.stackexchange | 177,225 | 414,694 [0.36M-0.47M] | S | 235 | 2.2 |
| wikibooks maxi (nopic is a twin: same text) | 102,193 | 363,167 [0.27M-0.47M] | S | 625 | 2.4 |
| ifixit | 253,845 | 347,634 [0.32M-0.38M] | S | 176 | 1.8 |
| wikipedia_en_medicine (a subset of Wikipedia) | 101,665 | 331,645 [0.28M-0.39M] | S | 612 | 2.2 |
| libretexts (9 books) | 323,783 | ~1,166,000 (0.9M-1.5M) | H | 625 | 7.5 |
| 9 small Stack Exchange sites | 388,000 | ~982,000 | P | 235 | 5.3 |
| wikiversity | 54,134 | 155,936 | P | 625 | 1.0 |
| gutenberg (2 files) | 2,720 | ~173,000 | S/P | 484 | 1.1 |
| medlineplus + nhs | 16,936 | ~131,000 | S/P | 141 | 0.7 |
| devdocs (9), cooking/hobby sites, prepper/survival sites | ~25,000 | ~200,000 | P/H | 400 | 1.2 |

Check of the method: my chunks-per-page numbers reproduce NOMAD's own production counters in 6 of 6 chains (within -8% to +10%). [S] Libretexts is the big unknown: its 9 books have only 0 to 150 points each in production, i.e. they were never really indexed (probably the "stops after the first sparse batch" bug fixed in NOMAD 1.35, issue #1240 [I]); they need a re-embed.

### 3.2 Totals

| Scenario | libraries | chunks | tokens | disk as NOMAD sets it up today | disk compact (int8) |
|---|---:|---:|---:|---:|---:|
| **A** everything NOMAD would index | 57 | 25.42 M [23.9-27.3] | 13.06 B | 140 GB | 160 GB |
| **B** all except the full Wikipedia, without the wikibooks twin | 55 | 5.30 M [4.35-6.57] | 2.07 B | 27 GB | 31 GB |
| Wikipedia alone | 1 | 19.76 M [19.27-20.27] | 10.76 B | 111 GB | 126 GB |
| Today in Qdrant (with ~0.85 M duplicates) | | 4.11 M | | ~21 GB real + ~20 GB garbage | |

### 3.3 Smaller Wikipedia versions (Kiwix catalog snapshot of 2026-10-01, research slice)

Same article text in `maxi` and `nopic` (nopic is only 42% of the download), so the **index** is the same size; only `mini` (introduction + infobox) and the `top` sets shrink it. `articleCount` includes redirects; real pages are `text/html` entries from the ZIM's own counter.

| Variant | download | real pages | chunks per page | chunks | tokens per chunk (nomic) | tag |
|---|---:|---:|---:|---:|---:|:--:|
| all_maxi 2026-02 (installed) | 124 GB | 8.43 M | 2.345 [2.29-2.41] | **19.76 M** [19.27-20.27] | 545 | S |
| all_nopic 2026-06 (same text) | 52.7 GB | 8.52 M | 2.35 | 19.97 M | 545 | I (extrapolated) |
| all_mini 2026-09 (intro + infobox) | 14.4 GB | 7.33 M | ~1.03 | **~7.5 M** [7.4-7.7] | ~134 | I (from the top1m_mini sample) |
| top1m (maxi/nopic), full text of the best 1,000,000 articles | 17.1 GB (nopic) | 1.77 M | **4.21** [3.84-4.62] | **7.47 M** [6.81-8.20] | 626 | S |
| top1m_mini | 3.0 GB | 1.77 M | 1.026 | 1.82 M | 134 | S |
| top (best 50,000), full text: the 50,002 selected pages | in top_nopic 2.75 GB | 50,002 | **17.59** [16.85-18.31] (median 14, p90 32) | **0.88 M** [0.84-0.92] | 716 | S |
| top_nopic / top_maxi (224,147 pages = the 50,002 + ~174k linked pages of unknown size) | 2.75 / 7.0 GB | 224,147 | | **~1.4 M** [1.2-1.6; if the extra pages look like the tail or like the best-1M sample] | ~670 | I |
| top_mini (best 50k, intro + infobox) | 0.30 GB | 50,002 | 1.25 | 62.5 k | 361 | S |
| wikipedia_en_100_mini (installed) | 4.5 MB | 1,301 | 1.08 | 1,402 | | P |

Measured by ZimStats on the mini ZIMs themselves (K=1,000 pages each) and, for the full-text rows, on the same pages looked up in the installed 2026-02 maxi ZIM (hit rate 99.4-99.9%). Pattern: chunks per page grow with how important the article is: uniform 2.35, best 1M 4.21, best 50k **17.6**, because popular articles are very long. So the best 50,000 articles in full are 0.88 M chunks (an 8x smaller index than the best 1 M), while all 7.3 M intros are 7.5 M chunks of only ~134 tokens each (1.0 B tokens: 1.6 times the GPU time of the best-50k articles in full).
Extrapolated rows (marked I) have not been sampled directly (all_mini 14.4 GB was not downloaded; the 174k extra pages of top_nopic are unknown).

### 3.4 What a chunk costs in Qdrant, by layout (disk, RAM)

Measured on a 10,000-point test collection of the same Qdrant version plus production numbers (Lab slice); sizes in bytes **per chunk**.

| Layout | disk | RAM that must be resident | meaning |
|---|---:|---:|---|
| V0: NOMAD defaults | 5.4 KB | 3.3 KB if searches are to be fast (vectors in page cache), **plus ~1.3 KB** extra heap seen in production | what runs today |
| V1: int8 copy in RAM, original vectors on disk | 6.2 KB | 1.0 KB | needs +768 B on disk |
| V2: V1 with the HNSW graph on disk | 6.2 KB | 0.95 KB | |
| **V3: everything on NVMe (int8 copy memory-mapped)** | 6.2 KB | **52 B** (plus whatever page cache is free) | recommended for this crowded host |

At 6.6 M chunks: V0 21.8 GB RAM (does not fit), V1 6.6 GB, V3 0.34 GB. At 25 M chunks: V0 84 GB, V1 25 GB, V3 1.3 GB. [M + D, scale runs pending]

NOMAD sends no quantization options, so with int8 Qdrant ranks by the approximate scores and does **not** re-check with the original vectors (rescoring is off by default for int8 in v1.16.3 [D]); the usual loss for int8 is below 1% [D]; I did not measure it on real vectors yet (section 8).

---

## 4. Embedding models (retrieval quality, cost, fit with NOMAD)

Quality = nDCG@10 x 100 averaged over the 10 retrieval tasks of MTEB(eng, v2), computed by the research slice from the public results repository (github.com/embeddings-benchmark/results, snapshot 2026-10-01, the data behind the Hugging Face leaderboard). Reproduces the Qwen3 card exactly (61.83). "Wiki5" = mean of five Wikipedia-based tasks (HotpotQA-HN, FEVER-HN, ClimateFEVER-HN, MIRACL-en, MLQA-en), the research slice's own aggregate. "Compute" = non-embedding parameters relative to nomic (rule of thumb for GPU cost per token). Full list of 32 models with sources: `research/models.md` in the working folder (`tmp/nomadindex` of the Cody workspace).

| Model | MTEB retrieval | Wiki5 | dim / shrinkable to | context | licence | compute | GGUF in our llama.cpp | NOMAD fit |
|---|---:|---:|---|---:|---|---:|---|---|
| nomic-embed-text-v1.5 (today) | **47.97** | 51.8 | 768 / 512, 256, 128, 64 | 2048 | Apache-2.0 | 1.00x | yes | native |
| **granite-embedding-english-r2** | **56.43** | n/a (HotpotQA 67.1, FEVER 88.9) | 768 / none | 8192 | Apache-2.0 | 0.97x | community Q8_0 160 MB | name alias + floor; stray prefix is noise (optional 2-line patch) |
| EmbeddingGemma-300M | 55.69 | 62.2 | 768 / 512, 256, 128 | 2048 | Gemma terms | 0.94x | official Q8_0 334 MB | needs prefix patch; **0.3% of Wikipedia chunks exceed 2,048 tokens** (up to 2,951) and the server then answers HTTP 400, which NOMAD does not treat as "too long" |
| jina-embeddings-v5-text-nano | **58.80** | 65.4 | 768 / 512, 256, 128, 64, 32 | 8192 | **CC-BY-NC-4.0** | 1.00x | official Q8_0 233 MB | needs prefix patch (`Query: `/`Document: `, last-token pooling); a llama.cpp batch-drift report exists (#26282, L2 0.025, CPU build) |
| snowflake-arctic-embed-l-v2.0 | 58.56 | 65.6 | 1024 / 256 | 8192 | Apache-2.0 | 2.67x | community Q8_0 635 MB | 1024-d: NOMAD width patch; 2.7x GPU cost |
| snowflake-arctic-embed-m-v2.0 | 58.41 | 66.1 | 768 / 256 | 8192 | Apache-2.0 | 1.00x | **no** (ONNX only) | not servable by llama-server |
| Qwen3-Embedding-0.6B | 61.83 | 64.5 | 1024 / 32..1024 | 32768 | Apache-2.0 | 3.89x | official Q8_0 639 MB | 1024-d; 3.9x GPU cost; needs 1.6-3.6 GB VRAM (measured, depends on batch size) |
| nomic-embed-text-v2-moe | 54.81 | 63.6 | 768 / 256 | **512** | Apache-2.0 | 1.00x | official | 64% of NOMAD chunks exceed 512 tokens: unsuitable |
| bge-m3 | n/a (only 6 of 10 tasks published) | 61.9 | 1024 / none | 8192 | MIT | 2.75x | official | only for cross-language questions |

Newer or larger models checked and not recommended for this box: jina-v5-small (60.07, 3.9x, NC), harrier-oss-v1-0.6b (58.43), pplx-embed-v1-0.6b (58.22), 3-4B models (VRAM), Yuan-embedding-2.0 (headline score not credible). No nomic-v3, EmbeddingGemma successor or Qwen3-Embedding successor exists as of 2026-10-01.

**What the quality gap means in practice:** +8.5 points for granite and +7.7 for EmbeddingGemma on average retrieval; on the Wikipedia-based tasks nomic is 6 to 17 points behind the others (HotpotQA-HN, FEVER-HN, ClimateFEVER-HN). Caveat from the research slice: many of these models were trained on parts of those Wikipedia benchmarks (declared training data), so the margin is partly an overfit; NOMAD's own small test (28 documents, 99 questions) showed all models within 1 question on English.

**Shrinking vectors (published, MRL):** EmbeddingGemma 768 to 256 costs 1.3 points (69.67 to 68.37); arctic-l 1024 to 256 about -2.3%; nomic v1.5 768 to 256 -1.2 points (MTEB mean). NOMAD hard-codes 768, so shorter vectors would need a patch; not recommended now.

**Speed and VRAM on the P40 (the part still missing).** Only nomic has a usable speed number (section 2.4). By parameter count the same-class models (granite, jina-nano, EmbeddingGemma) should run at 0.8 to 1.2 times nomic's speed [I], but tokens differ: Gemma's tokenizer produces 12% more tokens than nomic's on Wikipedia text, Qwen3's 16% more. One warning sign: in my first round, with the GPU 92-100% busy with other tenants and host load 54-74, single-chunk requests ran at nomic 21.3 chunks/s (GPU only 27% busy at the start of that run), EmbeddingGemma 9.9, bge-m3 5.1, Qwen3-0.6B 2.8. These are **not comparable** (different contention) but suggest the real cost ratios may be worse than the parameter ratios; do not rely on "same speed" until the quiet-window suite has run (section 8). VRAM measured with my llama-server settings (`-c 4096`): nomic 504-518 MB (400 MB in production), EmbeddingGemma Q8 636-688 MB, nomic-v2-moe 630-652 MB, bge-m3 614 MB, Qwen3-0.6B 1.6 GB (`-ub 1024`) to 2.4 GB (`-ub 2048`) to 3.6 GB (`-ub 4096`): its 152k-word output buffer grows with the batch size. granite and jina-nano are not yet loaded (the server binary does contain their architectures, modern-bert and eurobert; checked).

---

## 5. Options (size / RAM / time / quality)

Time columns use the provisional 11,000 tokens/s [prov] for any model of nomic's class; double the speed and every time halves. "NOMAD as shipped" = NOMAD's own job chain on NVMe-hosted Qdrant, quiet host [I]; "today's conditions" = what the logs show now.

| Option | chunks | disk | RAM (V1 / V3) | GPU-bound time (continuous, nights of 3 h) | NOMAD as shipped | MTEB retrieval |
|---|---:|---:|---|---|---|---:|
| **A** Everything incl. full Wikipedia, nomic, NOMAD defaults | 25.4 M | 140 GB | 84 GB **impossible** (V0) / 25 GB / 1.3 GB | 13.7 days, 110 nights | **never**: Wikipedia alone needs 193 days of opens and 18 days to 13 years of walking | 47.97 |
| **B** Everything except full Wikipedia, nomic | 5.3 M | 27-31 GB | 5.3 GB / 0.3 GB | 2.2 days, **17 nights** | 40 nights (NVMe, quiet) to 91 nights (today's conditions) | 47.97 |
| **C (recommended)** B + the best 50,000 Wikipedia articles in full (`top_nopic`), granite-r2 | ~6.7 M [0.88 M of it measured; the rest I] | ~41 GB | 6.7 GB / 0.35 GB | ~3.5 days, **~28 nights** (tokens +10% for granite's tokenizer [I]) | ~46 nights (NVMe, quiet) to ~97 (today's) | **56.43** |
| **D** B + all 7.3 M Wikipedia intros (`all_mini`), granite-r2 | ~12.8 M [I] | ~69 GB | 12.9 GB / 0.7 GB | ~3.6 days, ~29 nights (intros are short: 1.0 B tokens) | needs the seek patch (PR #1386) and still 146,636 jobs that each re-open the file: 100+ nights [I] | 56.43 |
| **C+** B + the best 1,000,000 articles in full (`top1m_nopic`, 17 GB), granite-r2 | ~12.8 M | ~81 GB | 12.8 GB / 0.7 GB | ~7.8 days, ~63 nights | needs the seek patch; ~70 nights on top [I] | 56.43 |
| **E** B + full Wikipedia, granite-r2 | 25.1 M | 157 GB | 25 GB / 1.3 GB | 14.8 days, 118 nights | impossible without a custom indexer | 56.43 |

The one-off full-speed alternative: running the GPU flat out for the whole of option C takes about 3.5 days (GPU-bound) to 6-7 days (NOMAD's pipeline), but it would hold the GPU 24 hours a day against Scrypted and the other tenants; the 3-hour nightly window is the safer way. Doubling the P40 speed (if the quiet-window runs show it) halves every time column.

---

## 6. Recommendation

### 6.1 The setup

| Item | Choice | Why |
|---|---|---|
| Model | **granite-embedding-english-r2**, Q8_0, 768 numbers per vector (fallback: keep nomic) | +8.5 retrieval points, same GPU class and vector width, Apache-2.0, 8k context (no chunk is rejected as too long), needs no prompt prefix (NOMAD's fixed `search_document:`/`search_query:` prefixes would only be noise: measured in the acceptance test) |
| Vector length | 768 (full) | NOMAD hard-codes it; Matryoshka shrinking saves little here and needs a patch |
| Qdrant layout | fresh collection on **NVMe**, vectors and graph on disk, int8 copy memory-mapped (V3), payload on disk | removes the shfs/HDD problem, keeps RAM use at 0.35 GB mandatory |
| Libraries | all except the full Wikipedia and except the wikibooks nopic twin, **plus `wikipedia_en_top_nopic_2026-09`** (2.75 GB download: the best 50,000 Wikipedia articles in full, 17.6 chunks each, plus ~174k linked pages) and the libretexts books re-embedded | Wikipedia's most-read articles at ~1.4 M chunks instead of 19.8 M |
| Schedule | the existing nightly gate, 02:00-05:00 | |
| Size | ~6.7 M chunks, ~41 GB NVMe, RAM 0.35 GB (V3) to 6.7 GB (V1) | |
| Finish | GPU-bound about 28 nights; with NOMAD's pipeline about 46 nights (up to ~97 under today's conditions); at the P40 speed of today: start night 1 on about Oct 6, finish between **Nov 2 and Dec 1** (later if the quiet-window runs disappoint) | the quiet-window speeds will narrow this |

Exact Qdrant call for the fresh collection (create it **before** NOMAD first touches it; NOMAD then only adds its four payload indexes). Layout V3, flags marked * are from the Qdrant documentation and not yet run by me:

```
PUT /collections/nomad_knowledge_base
{ "vectors": {"size": 768, "distance": "Cosine", "on_disk": true},
  "hnsw_config": {"m": 16, "ef_construct": 100, "on_disk": true, "max_indexing_threads": 2},      *
  "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": false}},
  "on_disk_payload": true,
  "optimizers_config": {"indexing_threshold": 20000, "max_optimization_threads": 2} }              *
```
If RAM turns out to be plentiful, switch to V1 later in place: `PATCH /collections/nomad_knowledge_base {"quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": true}}}` (no re-embedding).

### 6.2 Steps, downtime, resources (new model + fresh collection)

| # | Step | Downtime | Heavy? | Resources / duration |
|---|---|---|---|---|
| 0 | Acceptance test in the quiet window (section 6.4) | none | yes, GPU | ~1 h |
| 1 | Create `/mnt/nvme/appdata/nomad-qdrant`; download `wikipedia_en_top_nopic` into NOMAD's library folder | none | no | 2.75 GB download |
| 2 | Add one path to the Nomad container template: host `/mnt/nvme/appdata/nomad-qdrant` to container `/data/qdrant`; recreate the container; check that the inner Qdrant sees an empty folder (the bind is resolved inside the Nomad container, so this should work [I]) | **~3-5 min** (Nomad apps, Kiwix, Kolibri) | no | NOMAD's inner Qdrant bind-mount then resolves to NVMe; the old 42 GB stays hidden on the array until deleted |
| 3 | `PUT` the new collection (above); set NOMAD's relevance floor (setting `rag.minRelevance`, start at 0.30-0.45, calibrate on the acceptance questions); if a prefix patch is wanted, add it like `patch_embed_fallback` | none | no | seconds |
| 4 | llama-swap: serve granite under the name NOMAD asks for (`nomic-embed-text:v1.5` alias) with `-c 8192 -b 4096 -ub 4096` (owner: LlamaSwapAgent) | none | no | VRAM ~0.5-0.8 GB [I] |
| 5 | Queue the libraries, small and high-value first (devdocs, medline, SE sites, wikibooks, ifixit, gutenberg, top-nopic, libretexts); one heavy job at a time | search works on whatever is done (it is dead today) | yes, nightly | GPU ~0.05 s per chunk, Node ~15-50 ms CPU per page, Qdrant build ~2.5 CPU-ms per point [prov] = ~4.6 CPU-hours for 6.6 M, spread over the nights |
| 6 | After the new index passes a spot check, delete the old collection folder (frees 42 GB on the array) | none | no | |

Disk during the work: old 42 GB (array) + new up to 40 GB (NVMe). CPU/RAM of NOMAD itself: `nomad_admin` 1.2 GB (upstream reports growth to 15 GB after 5 days: watch it, restart weekly). Qdrant build uses at most 2 threads in the layout above.

Guard rails (from NOMAD's code, `rag_service.ts` l.2694-2760): the Knowledge Base panel's **Reset & Rebuild** drops the whole collection, recreates it with default settings and queues **every** file on disk, including the 124 GB Wikipedia. Do not press it; if it happens by accident, re-apply the `PUT`/`PATCH` settings above and run `nomad-embed exclude wikipedia_en_all_maxi` at once. Set the ingest policy to *Manual* so that a newly downloaded library is not queued by itself, and queue libraries from the panel in the order of step 5.

### 6.3 If the new model fails the test (nomic stays)

1. Pause the gate; stop the Nomad container (graceful, ~2 min).
2. Copy the real data (21 GB) from the array to NVMe **without** `temp_segments/` and the `*.deleted` folders; mount that folder at `/data/qdrant`; start. Loading the 12 GB of vectors from NVMe takes about a minute. Downtime ~30-45 min.
3. `PATCH /collections/nomad_knowledge_base {"vectors": {"": {"on_disk": true}}, "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": true}}}` (the empty key addresses the single unnamed vector), then `{"optimizers_config": {"indexing_threshold": 10000}}` for the HNSW build (only once the stuck optimizer state is gone, otherwise the call blocks): about 1-1.5 hours on 4 CPUs (2.5 CPU-ms per point) and +9 GB disk while it runs; search stays up (brute force on NVMe, a few seconds) and then drops to milliseconds. [provisional, Lab]
4. Delete the duplicates by filter (wikibooks nopic twin, the 0.85 M duplicate points) and keep indexing the same libraries (option B).
Cost of staying: nothing is re-embedded. Of the 5.3 M chunks of option B, about 2.7 M are already in the old collection and usable (the rest of its 4.1 M are duplicates, the wikibooks twin and Wikipedia); about 2.6 M are still to embed (libretexts 1.2 M, electronics 0.8 M, ifixit and diy 0.3 M, small sites 0.3 M) = 1.1 B tokens = about 28 GPU-hours, 9 nights if the GPU were the only limit.
Cost of switching (what "switching costs little" really means): the 2.7 M good chunks already embedded with nomic (about 1.0 B tokens, ~24 GPU-hours, ~8 nights) are embedded again with the new model; Wikipedia is only 0.2 M of them, so its 0.5% (really 1.2%) progress is not the cost - the other libraries are, and they are small.

### 6.4 Acceptance test in the quiet window (decision rule written down in advance)

Run B1-B3 of section 8 (about 1 hour). Switch to granite-embedding-english-r2 (or jina-v5-nano if Nitin accepts a non-commercial licence and a prefix patch) **only if**, with NOMAD's fixed `search_*` prefixes, recall@5 on the 300 NOMAD-style Wikipedia questions and the mean nDCG@10 on the three BEIR sets are each **at least 3 points better than nomic**, batch results match single results (cosine at least 0.999) and no chunk is rejected. Otherwise keep nomic and do section 6.3.

---

## 7. Why the model is not the bottleneck (and what is)

1. NOMAD's job chain: one job per 50 pages, archive re-opened and re-walked every time (upstream issue #1185 open; fix PR #1386 not merged). Wikipedia: 168,517 jobs, a mean of 9.4 M entries walked per job (1.58e12 in total).
2. One Qdrant upsert per page on array disks through a FUSE share: 426 ms average.
3. A setPayload and four index calls at the start of every job; telemetry shows 155 s and 4.8 s averages (stalls up to 55 minutes).
4. Two jobs at a time and one chain per library.
The GPU needs about 0.05 s per chunk; NOMAD spends about 0.2 s per chunk plus the per-job costs above.

## 8. What is still provisional and the quiet-window plan

One heavy job at a time under `flock /tmp/agents-heavy.lock`; load must be below 8 before and after. Commands are in `local://quiet-NomadIndexAgent.md` (mine), `local://quiet-NomadQdrantLab.md` and `local://quiet-NomadZimStats.md`.

| Order | Run | What it settles | Duration |
|---|---|---|---|
| 1 | A1 `exp6_llamabench.py` | GPU speed of 12 model files (Q8 vs F32/F16 too) | ~15 min |
| 2 | A2 `exp4_speed_suite.py 2` | end-to-end chunks/s and VRAM per candidate | ~35 min |
| 3 | B1 `exp7_consistency.py` | batch drift / Q8 numerics | ~5 min |
| 4 | B2 `exp5_nomadwiki.py` x4 | recall on 300 NOMAD-style questions, NOMAD prefix vs native prompts | ~40 min |
| 5 | B3 `exp3_quality.py` (BEIR) | the +points hold after Q8 and NOMAD's prefixes | ~60 min |
| 6 | Lab steps 1-3 | disk/RAM slope at 100k/300k, int8 recall on real vectors, in-place PATCH proof, anon-heap cause | ~2.5-3 h |
| 7 | ZimStats timing suite | open/walk/read speeds on a quiet host; sampling of the 48 remaining libraries and of the extra pages of `top_nopic`, `all_mini` | ~2 h |

**Not done:** per-library sampling of 48 libraries (heuristics used for libretexts and the small sites); direct sampling of `top_nopic` and `all_mini` (both extrapolated from measured neighbours); fidelity of int8 on real vectors; speed of all candidates; calibration of NOMAD's relevance floor for a new model; scale runs of Qdrant beyond 10,000 points; whether Qdrant starts cleanly on the old data (not tested, deliberately).

## 9. Sources

- NOMAD source v1.35.0 (read from `github.com/Crosstalk-Solutions/project-nomad`, tag v1.35.0); upstream: issue #1185 (O(n^2) re-scan, open), PR #1386 (seek fix, open), #1269/#1270 (stall locks, merged), #1129/#1135, #1240/#1242, #1366/PR #1367 (configurable embedding model, open), #947 (hybrid search roadmap). Notes: `research/nomad_upstream.md` in the working folder (`tmp/nomadindex` of the Cody workspace).
- MTEB results: `github.com/embeddings-benchmark/results` (snapshot ecd91ce, 2026-10-01); Hugging Face model cards: ibm-granite/granite-embedding-english-r2, google/embeddinggemma-300m, jinaai/jina-embeddings-v5-text-nano, Snowflake/snowflake-arctic-embed-l-v2.0, Qwen/Qwen3-Embedding-0.6B, nomic-ai/nomic-embed-text-v1.5 and v2-moe; llama.cpp issue #26282. Per-model sources: `research/models.md`.
- Kiwix catalog (`library.kiwix.org/catalog/v2/entries`) and each ZIM's own counter: `research/wikipedia_variants.md`; libzim `getArticleCount` semantics: `github.com/openzim/libzim/blob/master/include/zim/archive.h`.
- Qdrant: https://qdrant.tech/documentation/installation/ (block storage, no NFS), https://qdrant.tech/documentation/manage-data/quantization/ (rescoring defaults), https://qdrant.tech/documentation/guides/capacity-planning/ (formulas), issues #3080 and #6371 ("Directory not empty"), v1.16.3 source (`quantized_vectors.rs` default_rescoring, `local_shard/mod.rs` load). Lab report: `qdrantlab/results.md`.
- Raw data and scripts are in the Cody workspace under `tmp/nomadindex/` (`state`, `zimstats`, `research`, `qdrantlab`, `bench`, `dataset`, `repair`); ZIM statistics: `zimstats/zim_overview.csv`, `zim_sampling.csv`, `fixed_costs.md`.
