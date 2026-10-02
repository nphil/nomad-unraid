# Embedding models for NOMAD on a Tesla P40 - research slice (2026-10-01)

Files: `models.md` (this), `models.json` (same data, machine readable), `wikipedia_variants.md/.json`, `nomad_upstream.md`. Raw inputs/scripts in `raw/`.

## Short answer (plain language)

- **Yes, there are clearly better models than nomic-embed-text-v1.5 that a P40 can run through llama-server.** v1.5 (Feb 2024) is now the weakest of the ~30 models checked on English retrieval: MTEB(eng,v2) retrieval nDCG@10 **47.97** versus 50-62 for the 2025-26 models, and on the Wikipedia-derived tasks 51.8 versus 56-66 (my "Wiki5" aggregate, defined below).
- **Three things decide the choice, not just the headline score:** (1) *cost per chunk* - models with ~110M "real" (non-embedding) parameters cost the same GPU time as nomic, 0.6B models cost ~3.9x; (2) *licence* - some of the best (jina v5) are non-commercial, EmbeddingGemma has Google's Gemma terms; (3) *what NOMAD hard-codes* - model name, 768 dimensions, the `search_document: `/`search_query: ` prefixes, the 0.62 relevance cut-off and 3,000-character chunks (~750 tokens, too long for 512-token models). Any other model needs a small NOMAD patch (upstream PR #1367 has the right structure) and a full re-index.
- **Numbers are English nDCG@10 x 100.** `[L]` = computed by me from the per-task JSON files of the MTEB results repo (the data behind the Hugging Face leaderboard, snapshot of 2026-10-01); `[S]` = self-reported on a model card/paper/vendor page. Where both exist the Qwen3 card matched my computation exactly (61.83), which validates the method.

- **What I did not do:** this slice was web research only (no GPU, no containers). "llama.cpp supported" means the architecture is on llama.cpp master (src/llama-arch.cpp, 2026-10-01) and I read the GGUF header (pooling, context, EOS flags) over HTTP range requests - I did not load any model in llama-server and I did not measure speed. Licence remarks are my reading, not legal advice.

## Ranked shortlist for this P40 / NOMAD use

Ranking logic: expected gain on English Wikipedia-style retrieval per unit of GPU time, subject to "servable by llama-server with an existing GGUF" and licence/risk. Throughput on the real P40 was NOT measured here (other workers do that) - re-rank with their numbers if speed turns out to dominate.

| rank | model | why | compute vs nomic | Q8_0 size | main risks |
|---|---|---|---:|---:|---|
| 1 | **jina-embeddings-v5-text-nano** | Best quality per unit of compute (proxy = non-embedding params): same class as nomic (EuroBERT-210M) but retrieval 58.80 vs 47.97 and Wiki5 65.4 vs 51.8; 768-d (same Qdrant width), 8k context, official GGUF. | 1.00x | 233 MB | CC-BY-NC-4.0 (personal use OK); needs llama.cpp build with `eurobert` (merged 2026-02-26); last-token pooling + `Query: `/`Document: ` prefixes; llama.cpp #26282 batch-drift report (use -np 1 or test). |
| 2 | **snowflake-arctic-embed-l-v2.0** | Best Apache-2.0 model for Wikipedia QA that llama.cpp can serve: NQ 63.7, FEVER 91.5, Wiki5 65.6, retrieval 58.56; MRL to 256-d costs ~2% BEIR (card). | 2.67x | 635 MB | 2.7x compute; 1024-d (new collection width); only community GGUFs (use HF, not the Ollama-registry blob); `query: ` prefix for queries only. |
| 3 | **EmbeddingGemma-300M** | Cheapest solid upgrade: 0.94x compute, 768-d drop-in width, retrieval 55.69 (+7.7), MIRACL-en 59.2 / MLQA 72.8, official ggml-org GGUFs incl. QAT Q8/Q4 (Q4_0 loses only 0.36 MTEB points per Google). | 0.94x | 334 MB | Gemma licence; 2048-token limit; never run F16 (overflow) - use Q8_0/F32; FEVER/ClimateFEVER weaker than arctic/jina; different prefixes. |
| 4 | **Qwen3-Embedding-0.6B** | Highest MTEB(eng,v2) retrieval among the credible, llama.cpp-servable, permissively licensed small models (61.83) with an official Q8_0 GGUF, 32k context and free MRL 32-1024. | 3.89x | 639 MB | 3.9x compute; NQ only 53.5 (below nomic v1.5's self-reported 59.7); needs the query instruction, last-token pooling + EOS (official GGUF handles it); 1024-d. |
| 5 | **granite-embedding-english-r2** | Clean-licence cheap option: Apache-2.0, trained only on permissively licensed data, 0.97x compute, 768-d, 8k context, no prefixes at all; retrieval 56.43 (+8.5). | 0.97x | 160 MB | Modest NQ (58.2); community GGUF only (modern-bert arch, supported); no MRL. |

Honourable mentions: **jina-embeddings-v5-text-small** (highest Wiki5 of the servable sub-1B models, 66.3, but 3.9x compute and non-commercial), **snowflake-arctic-embed-m-v2.0** (Wiki5 66.1 at nomic compute but *not supported by llama.cpp*; ONNX only), **snowflake-arctic-embed-m-v1.5** (2024; Wiki5 65.0 at 0.75x compute, 768-d, official 118 MB Q8_0 GGUF - but a 512-token limit means NOMAD chunks must shrink from 3,000 to ~1,500 characters, i.e. ~2x the vectors [inference]), **gte-modernbert-base** / **DenseOn** (BEIR 55.3 / 56.2 at ~150M, community GGUF, incomplete leaderboard coverage), **harrier-oss-v1-0.6b** and **pplx-embed-v1-0.6b** (best multilingual 0.6B models - MMTEB retrieval 70.4 / 65.1 - but only 3 of 10 English retrieval tasks are on the leaderboard and they are not ahead of Qwen3 on those 3).
Not recommended: **Yuan-embedding-2.0-en** (headline 70.69 is not credible, see its note), **nomic-embed-text-v2-moe** and **mxbai-embed-large-v1** (512-token limit vs NOMAD's 3,000-character chunks), **bge-m3** (only worthwhile for cross-language queries; NOMAD's own eval: 0.990 vs nomic 0.265 on translated questions), all 3-4B+ models (VRAM budget).

## What a model swap touches in NOMAD (from the lead's code notes + upstream PR #1367)

1. `EMBEDDING_MODEL_NAME` (`constants/ollama.ts`) and `EMBEDDING_DIMENSION = 768` (`rag_service.ts`): new width means a new Qdrant collection and a full re-index (NOMAD "Reset & Rebuild"); existing vectors from another model cannot be mixed.
2. Prefixes: `search_document: ` / `search_query: ` are constants; every model above needs its own pair (see the prefix column; PR #1367 stores them in an `EMBEDDING_MODELS` table).
3. Relevance cut-offs: `score_threshold` 0.3 in the Qdrant search and `RAG_MIN_FINAL_SCORE` 0.62 were tuned on nomic cosine scores; PR #1367 re-calibrated 0.30-0.44 for other models.
4. Chunk size: 3,000 characters (`TARGET_TOKENS_PER_CHUNK` 1500 x `CHAR_TO_TOKEN_RATIO` 2) with 300-character overlap, embedding inputs capped at 4,000 characters; models with 512-token context need a smaller chunk size.
5. Backend: NOMAD talks to an OpenAI-compatible `/v1/embeddings` (llama-swap -> llama-server); the server must run with the right `--pooling`, `-ub`, and (decoder models) EOS handling (Appendix D).

## What shrinking the vectors costs (Matryoshka, published numbers only)

Float32 storage per vector: 1,024-d = 4,096 B; 768-d = 3,072 B; 512-d = 2,048 B; 256-d = 1,024 B; 128-d = 512 B. Only models whose vendors published a quality-vs-dimension number are listed; all numbers are [S] (sources in the per-model notes).

| model | full dim -> 256 | published change | metric / source |
|---|---|---|---|
| EmbeddingGemma-300M | 768 -> 256 | 69.67 -> 68.37 (-1.30; 128d: 66.66) | MTEB(Eng,v2) mean of all tasks, Google card |
| snowflake-arctic-embed-l-v2.0 | 1024 -> 256 | 55.6 -> 54.3 BEIR(15) (-2.3%) | Snowflake card |
| snowflake-arctic-embed-m-v2.0 | 768 -> 256 | 55.4 -> 54.4 BEIR(15) (-1.8%) | Snowflake card |
| snowflake-arctic-embed-m-v1.5 | 768 -> 256 | 55.14 -> 54.2 MTEB retrieval (-1.7%) | Snowflake card |
| nomic-embed-text-v1.5 | 768 -> 256 | 62.28 -> 61.04 MTEB mean (-1.24; 128d: 59.34, 64d: 56.10) | Nomic docs |
| nomic-embed-text-v2-moe | 768 -> 256 | 52.86 -> 49.63 BEIR(15) (-6.1%; NQ 60.41 -> 56.12) | arXiv 2502.07972 Table 12 |
| jina-embeddings-v5 (small/nano) | 1024/768 -> 256 | "sizable decline below 256 dims" (figure only) | arXiv 2602.15547 Fig. 5 |
| Qwen3-Embedding-0.6B, F2LLM-v2, pplx-embed, voyage-4-nano, KaLM v2.5 | MRL claimed | no numeric table found | cards |

## Definitions and caveats

- **MTEB(eng,v2) retrieval** = mean nDCG@10 (x100) over its 10 retrieval tasks: ArguAna, CQADupstackGaming, CQADupstackUnix, ClimateFEVER-HardNegatives, FEVER-HardNegatives, FiQA2018, HotpotQA-HardNegatives, SCIDOCS, TRECCOVID, Touche2020.v3 (task list from `mteb/benchmarks/benchmarks/benchmarks.py`). NQ and DBPedia are **not** part of v2 - they belong to MTEB(eng,v1)/BEIR. Wikipedia-derived tasks inside v2: HotpotQA-HN, FEVER-HN, ClimateFEVER-HN.
- **Wiki5 / HN3 (my own aggregates, not leaderboard metrics):** Wiki5 = mean(HotpotQA-HN, FEVER-HN, ClimateFEVER-HN, MIRACL[en], MLQA[eng-eng]); HN3 = mean of the first three. All five tasks are built from Wikipedia text. They are saturating on some models, and several (NQ, HotpotQA, FEVER, MIRACL) appear in many models' *declared training data* (MTEB `training_datasets`), so scores there are not zero-shot; I list the overlap per model in `models.json` (`declared_training_overlap_with_wikipedia_tasks`).
- **BEIR(15)** = mean over the 15 MTEB v1 retrieval tasks (CQADupstack counted once as the mean of 12 forums). `[S]` BEIR numbers are model-card values; `[L, computed]` are my averages of results-repo files (for older models some v1 tasks are model-card values imported into the results repo as the "external" revision - flagged in `models.json`).
- **MMTEB retrieval** = mean over the 18 retrieval tasks of MTEB(Multilingual,v2) (AILAStatutes, ArguAna, BelebeleRetrieval, CovidRetrieval, HagridRetrieval, LEMBPasskeyRetrieval, LegalBenchCorporateLobbying, MIRACLRetrievalHardNegatives, MLQARetrieval, SCIDOCS, SpartQA, StatcanDialogueDatasetRetrieval, StackOverflowQA, TempReasonL1, TRECCOVID, TwitterHjerneRetrieval, WikipediaRetrievalMultilingual, WinoGrande). My computed values are within 0.1-0.4 of vendor numbers (Qwen3-0.6B 64.29 vs card 64.64; 4B 69.50 vs 69.60; bge-m3 54.3 vs 54.60), probably because of averaging details.
- **compute vs nomic** = non-embedding parameters / 113.3M (nomic-embed-text-v1.5). A rule of thumb for per-token GPU work; not measured.
- Leaderboard snapshot: <https://github.com/embeddings-benchmark/results> @ `ecd91ce5f259ee6a3efb5668afdcb1d208eded9d` (2026-10-01); per-model directories are linked in each note. Leaderboard UI: <https://huggingface.co/spaces/mteb/leaderboard>.

## Search log (what I queried to find newer/better models)

Web searches (via the search tool, then verified against Hugging Face / GitHub primary sources):
- `MTEB leaderboard embedding models 2026 open weights retrieval top`
- `jina-embeddings-v5 text small nano release MTEB retrieval GGUF`
- `pplx-embed Perplexity open-weight embedding model 0.6b 4b MTEB`
- `Octen-Embedding 0.6B 4B 8B Hugging Face MTEB`
- `Microsoft Harrier embedding model harrier-oss Hugging Face`
- `KaLM-Embedding-Gemma3-12B-2511 KaLM-Embedding-mini v2.5 Hugging Face MTEB`
- `F2LLM-v2 CodeFuse embedding model 0.6B 1.7B 4B MTEB`
- `voyage-4-nano open weights Hugging Face embedding Matryoshka license`
- `nomic-embed-text-v3 OR "nomic embed v3" release 2026 Nomic AI new embedding model`
- `Qwen embedding new release 2026 Qwen3.5 embedding OR "Qwen3-Embedding-2" OR "Qwen4-Embedding" Hugging Face`
- `EmbeddingGemma 2 OR "Gemma 4 embedding" OR "embeddinggemma-v2" Google new embedding model open weights 2026`
- `small embedding model under 1B parameters tops MTEB English v2 retrieval 2026 open weights Hugging Face new`
- `r/LocalLLaMA best embedding model 2026 llama.cpp GGUF embeddings Qwen3-Embedding vs EmbeddingGemma vs bge-m3`
- `nomic-embed-text-v1.5 Matryoshka MTEB score by dimension 768 512 256 128 64 table blog`
- `new open-weight text embedding model released September 2026 Hugging Face MTEB (recency=month)`
- `pplx-embed-v2-context-9b-preview Perplexity model card license size`
- `Hugging Face trending feature-extraction embedding models August 2026 EmbeddingGemma successor Qwen3-Embedding successor (recency=month)`
- `NVIDIA Tesla P40 datasheet INT8 47 TOPS FP32 12 TFLOPS FP16 1/64 rate GP102 compute capability 6.1`

Data-source scans (API queries):
- MTEB results repo (github.com/embeddings-benchmark/results @ ecd91ce, 2026-10-01): enumerated all 702 model directories, computed MTEB(eng,v2) 10-task retrieval average (133 models have all 10 tasks), MMTEB 18-task retrieval average, BEIR(15) and Wikipedia tasks from the per-task JSON files
- HF API https://huggingface.co/api/models?pipeline_tag={feature-extraction,sentence-similarity}&sort={trendingScore,downloads,likes}&limit=100 (428 distinct models, 149 created since 2025-07-01) - raw/hf_trending_scan.json
- HF API https://huggingface.co/api/models?search=<name>&filter=gguf for: snowflake-arctic-embed-{l,m}-v2, granite-embedding, gte-modernbert, mxbai-embed-large, harrier-oss, pplx-embed, Octen-Embedding, KaLM-embedding, F2LLM, voyage-4-nano, LFM2.5-Embedding, Nemotron-3-Embed, BidirLM, geevec, jina-embeddings-v3, bge-m3, Yuan-embedding, mdbr-leaf, DenseOn
- GitHub API: llama.cpp master src/llama-arch.cpp architecture list; llama.cpp issues #14234, #14018, #18532, #26282, #24898/#25210, PR #19826; llama-server README

## Comparison table (one row per model)

Legend: [L] leaderboard (results repo, computed), [S] self-reported, [L+S] mixed. "HN" = hard-negative variants used in MTEB(eng,v2). CF = ClimateFEVER, Hot = HotpotQA, DBP = DBPedia, FEV = FEVER. "compute" = non-embedding params relative to nomic v1.5. GGUF sizes are file sizes in MB (decimal) from the Hugging Face API.

| # | model (HF id) | params total / non-emb (compute) | dim / MRL | ctx | licence | prefixes (query / doc) | MTEB(eng,v2) retrieval | Wikipedia-based retrieval | BEIR(15) | MMTEB retrieval | llama.cpp / GGUF |
|---|---|---|---|---:|---|---|---|---|---|---|---|
| 1 | **nomic-embed-text-v1.5**<br>`nomic-ai/nomic-embed-text-v1.5`<br>_baseline (what NOMAD uses)_ | 137M<br>non-emb 113M = 1.00x | 768<br>MRL: 768/512/256/128/64 | 2048 | Apache-2.0 | q: `search_query: `<br>d: `search_document: ` | **47.97** [L+S] | NQ 59.7 / Hot 72.6 / DBP 43.9 / FEV 86.3 / CF 41.3 [S]<br>HN: Hot 60.6 / FEV 71.2 / CF 29.2 [L]<br>MIRACL-en 37.9 / MLQA-en 60.0 [L]<br>**Wiki5 51.8** | 53.01 [S]<br>51.89 [L, computed] | 33.86 [L] | **yes** (nomic-bert)<br>official: `nomic-ai/nomic-embed-text-v1.5-GGUF`<br>Q8_0 146 / Q4 84 / F16 274 MB |
| 2 | **nomic-embed-text-v2-moe**<br>`nomic-ai/nomic-embed-text-v2-moe`<br>_required_ | 475M (active 305M)<br>non-emb 113M = 1.00x | 768<br>MRL: 768/256 | 512 | Apache-2.0 | q: `search_query: `<br>d: `search_document: ` | **54.81** [L] | NQ 60.4 / Hot 68.5 / DBP 41.4 / FEV 87.2 / CF 33.4 [S]<br>HN: Hot 68.5 / FEV 87.0 / CF 33.8 [L]<br>MIRACL-en 55.6 / MLQA-en 72.9 [L]<br>**Wiki5 63.6** | 52.86 [S] | 56.71 [L] | **yes** (nomic-bert-moe)<br>official: `nomic-ai/nomic-embed-text-v2-moe-GGUF`<br>Q8_0 512 / Q4 344 / F16 958 MB |
| 3 | **EmbeddingGemma-300M**<br>`google/embeddinggemma-300m`<br>_required_ | 308M<br>non-emb 106M = 0.94x | 768<br>MRL: 768/512/256/128 | 2048 | Gemma Terms of Use | q: `task: search result \| query: `<br>d: `title: none \| text: ` | **55.69** [L] | HN: Hot 71.5 / FEV 80.8 / CF 26.7 [L]<br>MIRACL-en 59.2 / MLQA-en 72.8 [L]<br>**Wiki5 62.2** | - | 62.19 [L] | **yes** (gemma-embedding)<br>official: `ggml-org/embeddinggemma-300M-GGUF`<br>Q8_0 334 MB |
| 4 | **Qwen3-Embedding-0.6B**<br>`Qwen/Qwen3-Embedding-0.6B`<br>_required_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: any 32..1024 (card: "user-defined out... | 32768 | Apache-2.0 | q: `Instruct: Given a web search query, retriev...`<br>d: `(none)` | **61.83** [L] (card 61.83 [S]) | NQ 53.5 / Hot 65.7 / DBP 39.5 / FEV 88.2 / CF 42.1 [L]<br>HN: Hot 67.7 / FEV 88.9 / CF 43.6 [L]<br>MIRACL-en 51.8 / MLQA-en 70.6 [L]<br>**Wiki5 64.5** | 55.52 [L, computed] | 64.29 [L]<br>64.64 [S] | **yes** (qwen3)<br>official: `Qwen/Qwen3-Embedding-0.6B-GGUF`<br>Q8_0 639 / F16 1198 MB |
| 5 | **Qwen3-Embedding-4B (reference)**<br>`Qwen/Qwen3-Embedding-4B`<br>_reference (too large for <=1.5 GB budget)_ | 4022M<br>non-emb 3634M = 32.07x | 2560<br>MRL: 32..2560 | 40960 | Apache-2.0 | q: `Instruct: {task}\nQuery:{query}`<br>d: `(none)` | **68.46** [L] (card 68.46 [S]) | NQ 63.1 / Hot 74.7 / DBP 48.2 / FEV 91.6 / CF 47.4 [L]<br>HN: Hot 75.2 / FEV 92.5 / CF 48.5 [L]<br>MIRACL-en 59.5 / MLQA-en 75.8 [L]<br>**Wiki5 70.3** | 61.58 [L, computed] | 69.5 [L]<br>69.6 [S] | **yes** (qwen3)<br>official: `Qwen/Qwen3-Embedding-4B-GGUF`<br>Q8_0 4280 / Q4 2497 / F16 8050 MB |
| 6 | **snowflake-arctic-embed-l-v2.0**<br>`Snowflake/snowflake-arctic-embed-l-v2.0`<br>_required_ | 568M<br>non-emb 303M = 2.67x | 1024<br>MRL: 1024/256 | 8192 | Apache-2.0 | q: `query: `<br>d: `(none)` | **58.56** [L] | NQ 63.7 / Hot 68.2 / DBP 43.4 / FEV 91.5 / CF 41.8 [L]<br>HN: Hot 68.4 / FEV 92.2 / CF 42.8 [L]<br>MIRACL-en 54.3 / MLQA-en 70.4 [L]<br>**Wiki5 65.6** | 55.6 [S]<br>55.22 [L, computed] | 57.99 [L] | **yes** (bert)<br>community: `Casual-Autopsy/snowflake-arctic-embed-l-v2.0-gguf`<br>Q8_0 635 / Q4 438 / F16 1158 MB |
| 7 | **snowflake-arctic-embed-m-v2.0**<br>`Snowflake/snowflake-arctic-embed-m-v2.0`<br>_required_ | 305M<br>non-emb 113M = 1.00x | 768<br>MRL: 768/256 | 8192 | Apache-2.0 | q: `query: `<br>d: `(none)` | **58.41** [L] | NQ 64.7 / Hot 72.4 / DBP 43.9 / FEV 91.7 / CF 38.0 [L]<br>HN: Hot 71.9 / FEV 92.3 / CF 38.7 [L]<br>MIRACL-en 56.8 / MLQA-en 70.7 [L]<br>**Wiki5 66.1** | 55.4 [S]<br>55.49 [L, computed] | 54.37 [L] | **no** (GteModel)<br>ONNX only: model_int8.onnx 311 MB, model_fp16.onnx 613 MB, model.onnx 1226 MB |
| 8 | **snowflake-arctic-embed-m-v1.5 (older, relevant)**<br>`Snowflake/snowflake-arctic-embed-m-v1.5`<br>_older (2024-07) but relevant: official GGUF_ | 109M<br>non-emb 86M = 0.75x | 768<br>MRL: 768/256 | 512 | Apache-2.0 | q: `Represent this sentence for searching relev...`<br>d: `(none)` | **58.05** [L+S] | NQ 62.5 / Hot 72.2 / DBP 45.5 / FEV 88.4 / CF 36.9 [S]<br>HN: Hot 72.4 / FEV 88.7 / CF 37.3 [L]<br>MIRACL-en 56.7 / MLQA-en 70.1 [L]<br>**Wiki5 65.0** | 55.14 [S]<br>55.16 [L, computed] | 38.51 [L] | **yes** (bert)<br>official: `Snowflake/snowflake-arctic-embed-m-v1.5`<br>Q8_0 118 / F16 220 MB |
| 9 | **bge-m3**<br>`BAAI/bge-m3`<br>_required_ | 568M<br>non-emb 312M = 2.75x | 1024<br>MRL: none | 8192 | MIT | q: `(none)`<br>d: `(none)` | n/a (6/10 tasks; 3-task mean 41.69 [L]) | HN: Hot 69.5 / FEV 81.7 / CF 29.9 [L]<br>MIRACL-en 57.7 / MLQA-en 70.7 [L]<br>**Wiki5 61.9** | 48.8 [S] | 54.27 [L]<br>54.6 [S] | **yes** (bert)<br>official: `ggml-org/bge-m3-Q8_0-GGUF`<br>Q8_0 635 MB |
| 10 | **jina-embeddings-v3**<br>`jinaai/jina-embeddings-v3`<br>_required_ | 572M<br>non-emb 316M = 2.79x | 1024<br>MRL: 32/64/128/256/512/768/1024 | 8192 | CC-BY-NC-4.0 | q: `task adapter retrieval.query (LoRA; no text...`<br>d: `task adapter retrieval.passage` | **54.29** [L+S] | NQ 64.2 / Hot 64.7 / DBP 41.0 / FEV 89.0 / CF 42.4 [S]<br>HN: Hot 64.7 / FEV 89.9 / CF 43.1 [L]<br>MIRACL-en 52.0 / MLQA-en 64.7 [L]<br>**Wiki5 62.9** | 53.17 [L, computed] | 55.34 [L] | **yes** (jina-bert-v3)<br>community: `second-state/jina-embeddings-v3-GGUF`<br>Q8_0 601 / Q4 410 / F16 1124 MB |
| 11 | **jina-embeddings-v4 (reference)**<br>`jinaai/jina-embeddings-v4`<br>_reference (3.8B, too large)_ | 3755M | 2048<br>MRL: 128/256/512/1024/2048 | 32768 | Qwen Research License | q: `Query: `<br>d: `Passage: ` | **56.15** [L] | NQ 61.7 / Hot - / DBP 43.9 / FEV - / CF 35.1 [L]<br>HN: Hot 69.0 / FEV 87.7 / CF 34.6 [L]<br>MIRACL-en - / MLQA-en 67.5 [L]<br>HN3 63.8 | - | partial 66.83 (15/18 tasks) | **yes** (qwen2vl)<br>official: `jinaai/jina-embeddings-v4-text-retrieval-GGUF`<br>Q8_0 3286 / Q4 1930 / F16 6178 MB |
| 12 | **jina-embeddings-v5-text-small**<br>`jinaai/jina-embeddings-v5-text-small`<br>_required_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: 32/64/128/256/512/768/1024 | 32768 | CC-BY-NC-4.0 | q: `Query: `<br>d: `Document: ` | **60.07** [L] | NQ 64.0 / Hot 69.8 / DBP 44.4 / FEV 90.0 / CF 41.5 [L]<br>HN: Hot 69.9 / FEV 90.5 / CF 41.8 [L]<br>MIRACL-en 56.9 / MLQA-en 72.5 [L]<br>**Wiki5 66.3** | 56.67 [L, computed] | 64.62 [L] | **yes** (qwen3)<br>official: `jinaai/jina-embeddings-v5-text-small-retrieval-GGUF`<br>Q8_0 639 / Q4 397 / F16 1198 MB |
| 13 | **jina-embeddings-v5-text-nano**<br>`jinaai/jina-embeddings-v5-text-nano`<br>_required_ | 212M<br>non-emb 113M = 1.00x | 768<br>MRL: 32/64/128/256/512/768 | 8192 | CC-BY-NC-4.0 | q: `Query: `<br>d: `Document: ` | **58.80** [L] | NQ 63.4 / Hot 69.1 / DBP 45.3 / FEV 89.5 / CF 39.6 [L]<br>HN: Hot 69.3 / FEV 89.8 / CF 40.0 [L]<br>MIRACL-en 56.1 / MLQA-en 71.7 [L]<br>**Wiki5 65.4** | 56.06 [L, computed] | 63.03 [L] | **yes** (eurobert)<br>official: `jinaai/jina-embeddings-v5-text-nano-retrieval-GGUF`<br>Q8_0 233 / Q4 157 / F16 431 MB |
| 14 | **granite-embedding-english-r2**<br>`ibm-granite/granite-embedding-english-r2`<br>_required_ | 149M<br>non-emb 110M = 0.97x | 768<br>MRL: none | 8192 | Apache-2.0 | q: `(none)`<br>d: `(none)` | **56.43** [L] (card 56.4 [S]) | NQ 58.2 / Hot 67.4 / DBP 39.6 / FEV 88.0 / CF 35.8 [L]<br>HN: Hot 67.1 / FEV 88.9 / CF 36.0 [L]<br>MIRACL-en 45.2 / MLQA-en - [L]<br>HN3 64.0 | 53.1 [S] | partial 53.69 (7/18 tasks) | **yes** (modern-bert)<br>community: `mradermacher/granite-embedding-english-r2-GGUF`<br>Q8_0 160 / Q4 106 / F16 300 MB |
| 15 | **granite-embedding-small-english-r2**<br>`ibm-granite/granite-embedding-small-english-r2`<br>_required_ | 48M<br>non-emb 28M = 0.25x | 384<br>MRL: none | 8192 | Apache-2.0 | q: `(none)`<br>d: `(none)` | **53.93** [L] | NQ 55.4 / Hot 65.7 / DBP 37.9 / FEV 86.5 / CF 31.6 [L]<br>HN: Hot 66.2 / FEV 87.6 / CF 31.7 [L]<br>MIRACL-en 44.6 / MLQA-en - [L]<br>HN3 61.8 | 50.9 [S] | partial 50.49 (7/18 tasks) | **yes** (modern-bert)<br>community: `mradermacher/granite-embedding-small-english-r2-GGUF`<br>Q8_0 52 / Q4 42 / F16 97 MB |
| 16 | **granite-embedding-311m-multilingual-r2**<br>`ibm-granite/granite-embedding-311m-multilingual-r2`<br>_required_ | 312M<br>non-emb 110M = 0.97x | 768<br>MRL: 768/512/384/256/128 | 32768 | Apache-2.0 | q: `(none)`<br>d: `(none)` | **52.55** [L] | NQ 55.8 / Hot 62.4 / DBP 34.4 / FEV 82.2 / CF 29.9 [L]<br>HN: Hot 63.8 / FEV 83.7 / CF 30.5 [L]<br>MIRACL-en 45.5 / MLQA-en 63.4 [L]<br>**Wiki5 57.4** | 49.25 [L, computed] | 64.56 [L] | **yes** (modern-bert)<br>community: `mykor/granite-embedding-311m-multilingual-r2-GGUF`<br>Q8_0 347 / Q4 253 / F16 639 MB |
| 17 | **granite-embedding-97m-multilingual-r2**<br>`ibm-granite/granite-embedding-97m-multilingual-r2`<br>_required_ | 97M<br>non-emb 28M = 0.25x | 384<br>MRL: none | 32768 | Apache-2.0 | q: `(none)`<br>d: `(none)` | **50.09** [L] | NQ 51.4 / Hot 60.8 / DBP 31.9 / FEV 84.3 / CF 27.8 [L]<br>HN: Hot 61.7 / FEV 85.6 / CF 28.0 [L]<br>MIRACL-en 45.4 / MLQA-en 61.5 [L]<br>**Wiki5 56.4** | 47.34 [L, computed] | 59.62 [L] | **yes** (modern-bert)<br>community: `mykor/granite-embedding-97m-multilingual-r2-GGUF`<br>Q8_0 115 / Q4 106 / F16 206 MB |
| 18 | **granite-embedding-125m-english (R1)**<br>`ibm-granite/granite-embedding-125m-english`<br>_required (older "english")_ | 125M<br>non-emb 86M = 0.76x | 768<br>MRL: none | 512 | Apache-2.0 | q: `(none)`<br>d: `(none)` | **55.65** [L] | NQ 58.0 / Hot 67.8 / DBP 39.4 / FEV 88.2 / CF 33.1 [L]<br>HN: Hot 68.1 / FEV 90.0 / CF 33.1 [L]<br>MIRACL-en 43.6 / MLQA-en 64.8 [L]<br>**Wiki5 59.9** | 52.3 [S]<br>52.26 [L, computed] | 38.96 [L] | **yes** (bert)<br>community: `bartowski/granite-embedding-125m-english-GGUF`<br>Q8_0 135 / Q4 88 / F16 251 MB |
| 19 | **mxbai-embed-large-v1**<br>`mixedbread-ai/mxbai-embed-large-v1`<br>_required_ | 335M<br>non-emb 304M = 2.68x | 1024<br>MRL: MRL supported (truncate_dim example 5... | 512 | Apache-2.0 | q: `Represent this sentence for searching relev...`<br>d: `(none)` | **55.40** [L] | NQ 55.8 / Hot 72.0 / DBP 44.5 / FEV 86.9 / CF 36.1 [L]<br>HN: Hot 72.5 / FEV 86.5 / CF 36.2 [L]<br>MIRACL-en 51.9 / MLQA-en 66.6 [L]<br>**Wiki5 62.8** | 56.16 [L, computed] | 40.02 [L] | **yes** (bert)<br>community: `ChristianAzinn/mxbai-embed-large-v1-gguf`<br>Q8_0 358 / Q4 216 / F16 670 MB |
| 20 | **gte-modernbert-base**<br>`Alibaba-NLP/gte-modernbert-base`<br>_required_ | 149M<br>non-emb 110M = 0.97x | 768<br>MRL: none | 8192 | Apache-2.0 | q: `(none)`<br>d: `(none)` | 57.0 [S]; leaderboard 6/10 tasks only | NQ 56.1 / Hot 70.4 / DBP 41.4 / FEV 94.0 / CF 45.9 [L] | 55.33 [S]<br>55.26 [L, computed] | partial 65.4 (4/18 tasks) | **yes** (modern-bert)<br>community: `keisuke-miyako/gte-modernbert-base-gguf`<br>Q8_0 160 / Q4 106 / F16 300 MB |
| 21 | **harrier-oss-v1-0.6b**<br>`microsoft/harrier-oss-v1-0.6b`<br>_newer (2026-03)_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: none | 32768 | MIT | q: `Instruct: Given a web search query, retriev...`<br>d: `(none)` | n/a (3/10 tasks; 3-task mean 58.43 [L]) | MIRACL-en 56.5 / MLQA-en 70.7 [L] | - | 70.45 [L] | **yes** (qwen3)<br>community: `mradermacher/harrier-oss-v1-0.6b-GGUF`<br>Q8_0 639 / Q4 397 / F16 1198 MB |
| 22 | **harrier-oss-v1-270m**<br>`microsoft/harrier-oss-v1-270m`<br>_newer (2026-03)_ | 268M<br>non-emb 100M = 0.89x | 640<br>MRL: none | 32768 | MIT | q: `Instruct: Given a web search query, retriev...`<br>d: `(none)` | n/a (3/10 tasks; 3-task mean 55.73 [L]) | MIRACL-en 52.4 / MLQA-en 65.8 [L] | - | 65.93 [L] | **yes** (gemma3)<br>community: `mykor/harrier-oss-v1-270m-GGUF`<br>Q8_0 292 / Q4 253 / F16 543 MB |
| 23 | **pplx-embed-v1-0.6b**<br>`perplexity-ai/pplx-embed-v1-0.6b`<br>_newer (2026-01)_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: MRL: Yes (dims not listed in the card) | 32768 | MIT | q: `(none - "no instruction")`<br>d: `(none)` | n/a (3/10 tasks; 3-task mean 58.22 [L]) | MIRACL-en 57.5 / MLQA-en 73.4 [L] | - | 65.05 [L] | **yes** (qwen3 with attention.causal=false)<br>community: `mykor/pplx-embed-v1-0.6b-GGUF`<br>Q8_0 639 / Q4 397 / F16 1198 MB |
| 24 | **Octen-Embedding-0.6B**<br>`Octen/Octen-Embedding-0.6B`<br>_newer (2026-01)_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: none | 32768 | Apache-2.0 | q: `Instruct: Given a web search query, retriev...`<br>d: `(single space in the sentence-transformers ...` | n/a (not on the leaderboard for these tasks) | MIRACL-en 51.1 / MLQA-en - [L] | - | partial 80.51 (4/18 tasks) | **yes** (qwen3)<br>community: `mradermacher/Octen-Embedding-0.6B-GGUF`<br>Q8_0 639 / Q4 396 / F16 1198 MB |
| 25 | **KaLM-embedding-multilingual-mini-instruct-v2.5**<br>`KaLM-Embedding/KaLM-embedding-multilingual-mini-instruct-v2.5`<br>_newer (2025-09)_ | 494M<br>non-emb 358M = 3.16x | 896<br>MRL: 896/512/256/128/64 | 512 | Apache-2.0 | q: `Instruct: Given a query, retrieve documents...`<br>d: `(none)` | **58.46** [L] | NQ 58.6 / Hot 71.8 / DBP 42.6 / FEV 87.9 / CF 34.5 [L]<br>HN: Hot 71.8 / FEV 88.2 / CF 35.1 [L]<br>HN3 65.0 | 55.0 [L, computed] | partial 62.08 (4/18 tasks) | **yes** (qwen2)<br>community: `mradermacher/KaLM-embedding-multilingual-mini-instruct-v2.5-GGUF`<br>Q8_0 531 / Q4 398 / F16 994 MB |
| 26 | **F2LLM-v2-0.6B**<br>`codefuse-ai/F2LLM-v2-0.6B`<br>_newer (2026-03)_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: MRL trained (truncate to first d dims... | 40960 | Apache-2.0 | q: `Instruct: Given a question, retrieve passag...`<br>d: `(none)` | **54.31** [L] | NQ 60.9 / Hot 65.2 / DBP 41.4 / FEV 90.8 / CF 41.6 [L]<br>HN: Hot 65.6 / FEV 91.3 / CF 41.8 [L]<br>MIRACL-en 52.0 / MLQA-en 68.8 [L]<br>**Wiki5 63.9** | 51.37 [L, computed] | 58.99 [L] | **yes** (qwen3)<br>community: `mradermacher/F2LLM-v2-0.6B-GGUF`<br>Q8_0 639 / Q4 397 / F16 1198 MB |
| 27 | **voyage-4-nano**<br>`voyageai/voyage-4-nano`<br>_newer (2026-01)_ | 346M<br>non-emb 191M = 1.68x | 2048<br>MRL: 2048/1024/512/256 | 32000 | Apache-2.0 | q: `Represent the query for retrieving supporti...`<br>d: `(none)` | n/a (not on the leaderboard for these tasks) |  | - | partial 82.57 (2/18 tasks) | **unverified** (qwen3)<br>community: `jsonMartin/voyage-4-nano-gguf`<br>Q8_0 372 / F16 695 MB |
| 28 | **LFM2.5-Embedding-350M**<br>`LiquidAI/LFM2.5-Embedding-350M`<br>_newer (2026-05)_ | 354M<br>non-emb 287M = 2.54x | 1024<br>MRL: none | 512 | LFM Open License v1.0 | q: `query: `<br>d: `document: ` | n/a (not on the leaderboard for these tasks) |  | - | - | **yes** (lfm2)<br>official: `LiquidAI/LFM2.5-Embedding-350M-GGUF`<br>Q8_0 379 / Q4 229 / F16 712 MB |
| 29 | **DenseOn (LightOn)**<br>`lightonai/DenseOn`<br>_newer (2026-03)_ | 149M<br>non-emb 110M = 0.97x | 768<br>MRL: none | 8192 | Apache-2.0 | q: `query: `<br>d: `document: ` | n/a (6/10 tasks; 3-task mean 53.11 [L]) | NQ 59.2 / Hot 74.5 / DBP 44.6 / FEV 90.7 / CF 37.5 [L] | 56.2 [S]<br>56.2 [L, computed] | partial 53.11 (3/18 tasks) | **yes** (modern-bert)<br>community: `mradermacher/DenseOn-GGUF`<br>Q8_0 160 / Q4 106 / F16 300 MB |
| 30 | **Nemotron-3-Embed-1B**<br>`nvidia/Nemotron-3-Embed-1B-BF16`<br>_newer, borderline size (2026-07)_ | 1141M<br>non-emb 872M = 7.70x | 2048<br>MRL: none | 32768 | OpenMDW-1.1 | q: `not checked`<br>d: `not checked` | n/a (not on the leaderboard for these tasks) | MIRACL-en 57.6 / MLQA-en - [L] | - | partial 77.95 (4/18 tasks) | **unverified** (mistral3)<br>community: `nanoandrew4/Nemotron-3-Embed-1B-GGUF`<br>Q8_0 1220 / F16 2290 MB |
| 31 | **Yuan-embedding-2.0-en (flagged)**<br>`IEITYuan/Yuan-embedding-2.0-en`<br>_flagged: implausible scores_ | 596M<br>non-emb 440M = 3.89x | 1024<br>MRL: none | 2048 | Apache-2.0 | q: `instruction-based (custom loader)`<br>d: `-` | **70.69** [L] | HN: Hot 68.8 / FEV 77.2 / CF 59.0 [L]<br>HN3 68.3 | - | partial 75.96 (5/18 tasks) | **unverified** (qwen3)<br>community: `NikosKprl/Yuan-embedding-2.0-en-Q8_0-GGUF` |
| 32 | **geevec-embeddings-1.0-lite (not servable)**<br>`geevec-ai/geevec-embeddings-1.0-lite`<br>_not llama.cpp-servable_ | 366M<br>non-emb 211M = 1.86x | 4096<br>MRL: none | 40960 | Apache-2.0 | q: `instruction-based (custom loader)`<br>d: `-` | **62.23** [L] | HN: Hot 76.8 / FEV 92.3 / CF 43.7 [L]<br>MIRACL-en 54.5 / MLQA-en 73.2 [L]<br>**Wiki5 68.1** | - | 70.55 [L] | **no** (qwen3_pseudo_moe) |

## Per-model notes (every quality number with its source)

### 1. nomic-embed-text-v1.5  (`nomic-ai/nomic-embed-text-v1.5`)
- **Tier:** baseline (what NOMAD uses). **Licence:** Apache-2.0. **Params:** 137M, non-emb 113M = 1.00x; native dim 768; context 2048 tokens - HF config max_position_embeddings=2048 and official GGUF context_length=2048; Nomic docs advertise 8192 via RoPE scaling (needs extra setup); Ollama/NOMAD run it at 2048 (NOMAD #1268).
- **Prefixes / pooling:** query `'search_query: '`; document `'search_document: '`; pooling mean (GGUF pooling_type=1).
- **Matryoshka (MRL):** dims [768, 512, 256, 128, 64]. MTEB (v1, 56 tasks) average: 768d 62.28 | 512d 61.96 | 256d 61.04 | 128d 59.34 | 64d 56.10 [self-reported, Nomic docs https://docs.nomic.ai/atlas/embeddings-and-retrieval/text-embedding]. Recipe: layer_norm -> truncate -> L2-normalise (model card).
- **Quantisation claims:** No QAT/binary claim. Official GGUF Q8_0/Q4_K_M/F16.
- **MTEB(eng,v2) retrieval:** 47.97 - mixed: 9 tasks [leaderboard] + 1 task [self-reported model-card value] (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nomic-ai__nomic-embed-text-v1.5/b0753ae76394dd36bcfb912a46018088bca48be0>; per task: ArguAna 52.02, CQADupstackGamingRetrieval 57.48, CQADupstackUnixRetrieval 36.8, ClimateFEVERHardNegatives 29.18, FEVERHardNegatives 71.23, FiQA2018 37.46, HotpotQAHardNegatives 60.56, SCIDOCS 17.63, TRECCOVID 63.44, Touche2020Retrieval.v3 53.88
- **Wikipedia-based tasks:** v1: NQ 59.72 [S], HotpotQA 72.62 [S], DBPedia 43.9 [S], FEVER 86.34 [S], ClimateFEVER 41.28 [S]; v2 hard-negatives [L]: HotpotQAHardNegatives 60.56, FEVERHardNegatives 71.23, ClimateFEVERHardNegatives 29.18; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 90.91, MIRACLRetrievalHardNegatives[en] 37.91, MLQARetrieval[eng-eng] 59.96; Wiki5 51.77, HN3 53.66. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 53.01 [self-reported] <https://huggingface.co/Alibaba-NLP/gte-modernbert-base>; computed from results repo 51.89 (leaderboard (v1 tasks; mix with model-card values where marked))
- **MMTEB retrieval:** computed 33.86 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, MSMARCO, MSMARCOHardNegatives, NQ, NQ-NL, NQ-PL, NQHardNegatives, NanoNQRetrieval, WikipediaRerankingMultilingual, WikipediaRetrievalMultilingual
- **llama.cpp:** yes - arch nomic-bert. Evidence: official GGUF header (read 2026-10-01): nomic-bert, pooling_type=1 (mean), context_length=2048, causal=false.
  - GGUF (official): <https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF> - Q8_0: `nomic-embed-text-v1.5.Q8_0.gguf` 146.1 MB; Q4: `nomic-embed-text-v1.5.Q4_K_M.gguf` 84.1 MB; F16: `nomic-embed-text-v1.5.f16.gguf` 274.3 MB
- Note: Baseline. Self-reported v1 task numbers come from the model card (results repo "external" revision); v2 hard-negative tasks and ArguAna/SCIDOCS/TRECCOVID are leaderboard runs.
- Note: FiQA2018 (1 of the 10 MTEB(eng,v2) retrieval tasks) is missing from the leaderboard revision; the card value (37.46) was substituted, so the 47.97 average mixes 9 leaderboard + 1 self-reported task.
- Pitfall: Prefixes are mandatory (NOMAD hard-codes them).
- Pitfall: GGUF context is 2048 tokens.
- Pitfall: MRL truncation needs layer_norm before slicing if used.
- Sources: <https://huggingface.co/nomic-ai/nomic-embed-text-v1.5> | <https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF> | <https://docs.nomic.ai/atlas/embeddings-and-retrieval/text-embedding> | <https://huggingface.co/api/models/nomic-ai/nomic-embed-text-v1.5-GGUF?blobs=true> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nomic-ai__nomic-embed-text-v1.5/b0753ae76394dd36bcfb912a46018088bca48be0>

### 2. nomic-embed-text-v2-moe  (`nomic-ai/nomic-embed-text-v2-moe`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 475M (active 305M), non-emb 113M = 1.00x; native dim 768; context 512 tokens - card: "Maximum Sequence Length: 512 tokens"; GGUF context_length=512.
- **Prefixes / pooling:** query `'search_query: '`; document `'search_document: '`; pooling mean (GGUF pooling_type=1).
- **Matryoshka (MRL):** dims [768, 256]. BEIR(15) average 52.86 @768d -> 49.63 @256d (-6.1%); NQ 60.41->56.12, HotpotQA 68.53->63.67, FEVER 87.17->84.64, DBPedia 41.44->37.51, ClimateFEVER 33.38->29.58 [self-reported, paper https://arxiv.org/html/2502.07972 Table 12].
- **Quantisation claims:** No QAT/binary claim. Official GGUF Q8_0/Q4_K_M/F16.
- **MTEB(eng,v2) retrieval:** 54.81 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nomic-ai__nomic-embed-text-v2-moe/1066b6599d099fbb93dfcb64f9c37a7c9e503e85>; per task: ArguAna 55.76, CQADupstackGamingRetrieval 61.26, CQADupstackUnixRetrieval 42.74, ClimateFEVERHardNegatives 33.8, FEVERHardNegatives 86.96, FiQA2018 38.68, HotpotQAHardNegatives 68.52, SCIDOCS 19.25, TRECCOVID 78.74, Touche2020Retrieval.v3 62.37
- **Wikipedia-based tasks:** v1: NQ 60.41 [S], HotpotQA 68.53 [S], DBPedia 41.44 [S], FEVER 87.17 [S], ClimateFEVER 33.38 [S]; v2 hard-negatives [L]: HotpotQAHardNegatives 68.52, FEVERHardNegatives 86.96, ClimateFEVERHardNegatives 33.8; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.19, MIRACLRetrievalHardNegatives[en] 55.63, MLQARetrieval[eng-eng] 72.9; Wiki5 63.56, HN3 63.09. Sources: leaderboard dir above; self-reported v1 values from <https://arxiv.org/html/2502.07972 (Appendix C, Table 12, BEIR @768d)>.
- **BEIR(15):** 52.86 [self-reported] <https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe>
- **MMTEB retrieval:** computed 56.71 [L]
- **llama.cpp:** yes - arch nomic-bert-moe. Evidence: official GGUF header: nomic-bert-moe, expert_count=8, expert_used_count=2, pooling mean, context_length=512.
  - GGUF (official): <https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe-GGUF> - Q8_0: `nomic-embed-text-v2-moe.Q8_0.gguf` 512.2 MB; Q4: `nomic-embed-text-v2-moe.Q4_K_M.gguf` 344.1 MB; F16: `nomic-embed-text-v2-moe.f16.gguf` 957.7 MB
- Note: 475M total / 305M active parameters (8 experts, top-2). ~192M of the parameters are the 250k-token vocabulary embedding, so per-token compute is about the same as v1.5 (~113M non-embedding) [computed].
- Pitfall: 512-token limit: NOMAD chunks are 3,000 characters (~700-800 tokens) so chunk size would have to shrink (~1,500 chars) -> more vectors [inference].
- Pitfall: All 475M parameters must be resident although only 305M are used per token.
- Sources: <https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe> | <https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe-GGUF> | <https://arxiv.org/html/2502.07972> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nomic-ai__nomic-embed-text-v2-moe/1066b6599d099fbb93dfcb64f9c37a7c9e503e85>

### 3. EmbeddingGemma-300M  (`google/embeddinggemma-300m`)
- **Tier:** required. **Licence:** Gemma Terms of Use (HF licence tag "gemma"; not OSI open source) - https://ai.google.dev/gemma/terms. **Params:** 308M, non-emb 106M = 0.94x; native dim 768; context 2048 tokens - model card: "Maximum input context length of 2K"; GGUF context_length=2048.
- **Prefixes / pooling:** query `'task: search result | query: '`; document `'title: none | text: '`; pooling mean (GGUF pooling_type=1; BOS+EOS added).
- **Matryoshka (MRL):** dims [768, 512, 256, 128]. MTEB(Eng,v2) Mean(Task): 768d 69.67 | 512d 69.18 | 256d 68.37 | 128d 66.66; MTEB(Multi,v2): 61.15 | 60.71 | 59.68 | 58.23 [self-reported, Google model card https://ai.google.dev/gemma/docs/embeddinggemma/model_card]. (Overall tasks mean, not retrieval-only.)
- **Quantisation claims:** QAT checkpoints (evaluated after quantisation) MTEB(Eng,v2) Mean(Task): Q8_0 69.49, Q4_0 69.31, mixed-precision (int4 emb/FFN/proj + int8 attention) 69.32 vs 69.67 full precision [self-reported, https://ai.google.dev/gemma/docs/embeddinggemma/model_card].
- **MTEB(eng,v2) retrieval:** 55.69 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/google__embeddinggemma-300m/64614b0b8b64f0c6c1e52b07e4e9a4e8fe4d2da2>; per task: ArguAna 71.54, CQADupstackGamingRetrieval 59.52, CQADupstackUnixRetrieval 41.52, ClimateFEVERHardNegatives 26.71, FEVERHardNegatives 80.75, FiQA2018 47.74, HotpotQAHardNegatives 71.48, SCIDOCS 18.43, TRECCOVID 80.35, Touche2020Retrieval.v3 58.9
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: HotpotQAHardNegatives 71.48, FEVERHardNegatives 80.75, ClimateFEVERHardNegatives 26.71; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 95.07, MIRACLRetrievalHardNegatives[en] 59.22, MLQARetrieval[eng-eng] 72.81; Wiki5 62.19, HN3 59.65. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** computed 62.19 [L]
- **Declared training overlap (MTEB model_meta):** FEVERHardNegatives, HotpotQAHardNegatives, MIRACLRetrievalHardNegatives, NQHardNegatives
- **llama.cpp:** yes - arch gemma-embedding. Evidence: official ggml-org GGUF header (read 2026-10-01): gemma-embedding, pooling_type=1, context_length=2048, add_bos/add_eos=true.
  - GGUF (official): <https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF> - Q8_0: `embeddinggemma-300M-Q8_0.gguf` 333.6 MB; extra: QAT Q8_0: `ggml-org/embeddinggemma-300m-qat-q8_0-GGUF/embeddinggemma-300m-qat-Q8_0.gguf` 328.6 MB; QAT Q4_0: `ggml-org/embeddinggemma-300m-qat-q4_0-GGUF/embeddinggemma-300M-qat-Q4_0.gguf` 277.9 MB; BF16 (no F16 offered): `unsloth/embeddinggemma-300m-GGUF/embeddinggemma-300M-BF16.gguf` 612.4 MB; F32: `unsloth/embeddinggemma-300m-GGUF/embeddinggemma-300M-F32.gguf` 1218.0 MB
- Note: QAT variants: Google publishes full-precision QAT checkpoints `google/embeddinggemma-300m-qat-q4_0-unquantized` and `google/embeddinggemma-300m-qat-q8_0-unquantized` (302.9M F32 params each; you quantise them yourself) and ggml-org published ready GGUFs of both (listed under GGUF below).
- Note: ONNX export (no GGUF needed): `onnx-community/embeddinggemma-300m-ONNX` (q4, q4f16, fp16, quantized variants; transformers.js).
- Note: Google reports 308M parameters (307.6M incl. the two Dense projection layers; the main safetensors file holds 302.9M); ~201M of them are the 262k-token vocabulary embedding, leaving ~106M of compute (about 0.94x nomic-v1.5) [computed: MTEB model_meta n_parameters 307,581,696 - n_embedding_parameters 201,326,592].
- Note: Declared training data (MTEB model_meta): FEVER-HardNegatives, NQ-HardNegatives, HotpotQA-HardNegatives, MIRACL-HardNegatives -> the HN task scores listed for this model are not zero-shot.
- Pitfall: "EmbeddingGemma activations do not support float16. Please use float32 or bfloat16" (HF model card, mirrored in unsloth GGUF README) -> never use an F16 GGUF; Q8_0/Q4_0/F32 are fine (on a P40 prefer Q8_0 [inference]).
- Pitfall: 2048-token context.
- Pitfall: llama-server crashed with --parallel not a power of 2 (llama.cpp #18532, fixed 2026-01-03, reported again 2026-08-17).
- Pitfall: Gemma licence terms apply.
- Sources: <https://ai.google.dev/gemma/docs/embeddinggemma/model_card> | <https://huggingface.co/onnx-community/embeddinggemma-300m-ONNX> | <https://huggingface.co/google/embeddinggemma-300m> | <https://huggingface.co/google/embeddinggemma-300m-qat-q4_0-unquantized> | <https://huggingface.co/google/embeddinggemma-300m-qat-q8_0-unquantized> | <https://huggingface.co/ggml-org/embeddinggemma-300M-GGUF> | <https://huggingface.co/ggml-org/embeddinggemma-300m-qat-q8_0-GGUF> | <https://huggingface.co/ggml-org/embeddinggemma-300m-qat-q4_0-GGUF> | <https://huggingface.co/unsloth/embeddinggemma-300m-GGUF> | <https://arxiv.org/abs/2509.20354> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/google__embeddinggemma-300m/64614b0b8b64f0c6c1e52b07e4e9a4e8fe4d2da2>

### 4. Qwen3-Embedding-0.6B  (`Qwen/Qwen3-Embedding-0.6B`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 32768 tokens - card: "Context Length: 32k"; GGUF context_length=32768.
- **Prefixes / pooling:** query `'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:{query}'`; document `'(none)'`; pooling last token (+EOS) - official GGUF has pooling_type=3 and tokenizer.ggml.add_eos_token=true.
- **Matryoshka (MRL):** dims any 32..1024 (card: "user-defined output dimensions ranging from 32 to 1024"). No quality-vs-dimension table published in the card (none found).
- **Quantisation claims:** No QAT/binary claim. Official GGUF Q8_0 and f16 only.
- **MTEB(eng,v2) retrieval:** 61.83 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Qwen__Qwen3-Embedding-0.6B/b22da495047858cce924d27d76261e96be6febc0>; per task: ArguAna 70.97, CQADupstackGamingRetrieval 64.14, CQADupstackUnixRetrieval 51.49, ClimateFEVERHardNegatives 43.62, FEVERHardNegatives 88.94, FiQA2018 46.61, HotpotQAHardNegatives 67.69, SCIDOCS 24.41, TRECCOVID 90.52, Touche2020Retrieval.v3 69.9
  - card value 61.83 [self-reported]: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- **Wikipedia-based tasks:** v1: NQ 53.46 [L], HotpotQA 65.74 [L], DBPedia 39.48 [L], FEVER 88.15 [L], ClimateFEVER 42.11 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 67.69, FEVERHardNegatives 88.94, ClimateFEVERHardNegatives 43.62; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.53, MIRACLRetrievalHardNegatives[en] 51.8, MLQARetrieval[eng-eng] 70.59; Wiki5 64.53, HN3 66.75. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 55.52 (leaderboard)
- **MMTEB retrieval:** computed 64.29 [L]; 64.64 [S] <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQA, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch qwen3. Evidence: official GGUF header (read 2026-10-01): qwen3, pooling_type=3 (last), add_eos_token=true, context_length=32768.
  - GGUF (official): <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF> - Q8_0: `Qwen3-Embedding-0.6B-Q8_0.gguf` 639.2 MB; F16: `Qwen3-Embedding-0.6B-f16.gguf` 1197.6 MB
- Note: Computed MTEB(eng,v2) retrieval 61.83 equals the card value exactly (validates my aggregation). Declared training data includes NQ, HotpotQA, FEVER, MSMARCO, MIRACL (model_meta) -> NQ/HotpotQA/FEVER are not zero-shot.
- Note: Official repo has no Q4; community Q4_K_M GGUFs exist for derivatives.
- Pitfall: Self-converted GGUFs need `<|endoftext|>` appended manually (llama.cpp #14234) - the official GGUF already sets add_eos_token=true.
- Pitfall: Card runs llama-server with `--embedding --pooling last -ub 8192`.
- Pitfall: Queries need the instruction (card: 1-5% retrieval drop without it); NOMAD would need a per-model prefix table (cf. NOMAD PR #1367).
- Pitfall: ~3.9x the per-token compute of nomic-v1.5 [computed].
- Sources: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B> | <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF> | <https://github.com/ggml-org/llama.cpp/issues/14234> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Qwen__Qwen3-Embedding-0.6B/b22da495047858cce924d27d76261e96be6febc0>

### 5. Qwen3-Embedding-4B (reference)  (`Qwen/Qwen3-Embedding-4B`)
- **Tier:** reference (too large for <=1.5 GB budget). **Licence:** Apache-2.0. **Params:** 4022M, non-emb 3634M = 32.07x; native dim 2560; context 40960 tokens - HF config max_position_embeddings=40960 (card says 32k).
- **Prefixes / pooling:** query `'Instruct: {task}\nQuery:{query}'`; document `'(none)'`; pooling last token (+EOS).
- **Matryoshka (MRL):** dims 32..2560. none published
- **Quantisation claims:** -
- **MTEB(eng,v2) retrieval:** 68.46 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Qwen__Qwen3-Embedding-4B/636cd9bf47d976946cdbb2b0c3ca0cb2f8eea5ff>; per task: ArguAna 75.64, CQADupstackGamingRetrieval 71.51, CQADupstackUnixRetrieval 59.6, ClimateFEVERHardNegatives 48.48, FEVERHardNegatives 92.47, FiQA2018 62.65, HotpotQAHardNegatives 75.22, SCIDOCS 31.44, TRECCOVID 92.92, Touche2020Retrieval.v3 74.65
  - card value 68.46 [self-reported]: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- **Wikipedia-based tasks:** v1: NQ 63.13 [L], HotpotQA 74.72 [L], DBPedia 48.23 [L], FEVER 91.6 [L], ClimateFEVER 47.43 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 75.22, FEVERHardNegatives 92.47, ClimateFEVERHardNegatives 48.48; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 94.66, MIRACLRetrievalHardNegatives[en] 59.55, MLQARetrieval[eng-eng] 75.82; Wiki5 70.31, HN3 72.06. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 61.58 (leaderboard)
- **MMTEB retrieval:** computed 69.5 [L]; 69.6 [S] <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQA, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch qwen3. Evidence: official GGUF repo, arch qwen3.
  - GGUF (official): <https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF> - Q8_0: `Qwen3-Embedding-4B-Q8_0.gguf` 4279.7 MB; Q4: `Qwen3-Embedding-4B-Q4_K_M.gguf` 2496.7 MB; F16: `Qwen3-Embedding-4B-f16.gguf` 8049.9 MB
- Note: Reference only: Q8_0 is 4.28 GB, ~32x nomic-v1.5 per-token compute [computed].
- Sources: <https://huggingface.co/Qwen/Qwen3-Embedding-4B> | <https://huggingface.co/Qwen/Qwen3-Embedding-4B-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Qwen__Qwen3-Embedding-4B/636cd9bf47d976946cdbb2b0c3ca0cb2f8eea5ff>

### 6. snowflake-arctic-embed-l-v2.0  (`Snowflake/snowflake-arctic-embed-l-v2.0`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 568M, non-emb 303M = 2.67x; native dim 1024; context 8192 tokens - card: built on BAAI/bge-m3-retromae, up to 8192 via RoPE.
- **Prefixes / pooling:** query `'query: '`; document `'(none)'`; pooling CLS (card: "use the CLS token").
- **Matryoshka (MRL):** dims [1024, 256]. BEIR(15) nDCG@10 55.6 @1024d -> 54.3 @256d; MIRACL 55.8 -> 54.3; CLEF 52.9 -> 51.9 [self-reported, https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0]; card text: "vector truncation via MRL to decrease vector size by 4x with less than 3% degradation"; MRL is 256 dims only.
- **Quantisation claims:** "Quantization-aware embedding training": 128 bytes/vector via MRL(256d)+4-bit quantisation (FAISS pq256x4fs) [card].
- **MTEB(eng,v2) retrieval:** 58.56 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-l-v2.0/edc2df7b6c25794b340229ca082e7c78782e6374>; per task: ArguAna 59.11, CQADupstackGamingRetrieval 63.18, CQADupstackUnixRetrieval 46.57, ClimateFEVERHardNegatives 42.83, FEVERHardNegatives 92.21, FiQA2018 45.35, HotpotQAHardNegatives 68.4, SCIDOCS 20.28, TRECCOVID 83.63, Touche2020Retrieval.v3 64.05
- **Wikipedia-based tasks:** v1: NQ 63.67 [L], HotpotQA 68.15 [L], DBPedia 43.4 [L], FEVER 91.54 [L], ClimateFEVER 41.82 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 68.4, FEVERHardNegatives 92.21, ClimateFEVERHardNegatives 42.83; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 93.21, MIRACLRetrievalHardNegatives[en] 54.34, MLQARetrieval[eng-eng] 70.43; Wiki5 65.64, HN3 67.81. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 55.6 [self-reported] <https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0>; computed from results repo 55.22 (leaderboard (v1 tasks; mix with model-card values where marked))
- **MMTEB retrieval:** computed 57.99 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, MIRACLRetrieval, MIRACLRetrievalHardNegatives, NQ, NQ-NL, NQ-PL, NQHardNegatives
- **llama.cpp:** yes - arch bert (XLM-RoBERTa large, same as bge-m3). Evidence: community GGUF header (Casual-Autopsy): arch bert, context_length 8192; HF config model_type xlm-roberta.
  - GGUF (community): <https://huggingface.co/Casual-Autopsy/snowflake-arctic-embed-l-v2.0-gguf> - Q8_0: `snowflake-arctic-embed-l-v2.0-q8_0.gguf` 634.6 MB; Q4: `snowflake-arctic-embed-l-v2.0-q4_k_m.gguf` 437.8 MB; F16: `snowflake-arctic-embed-l-v2.0-f16.gguf` 1157.7 MB
- Note: No Snowflake-published GGUF for the v2.0 models (HF API author=Snowflake&filter=gguf returns only snowflake-arctic-embed-m-v1.5); community GGUFs exist. It is in the Ollama library as `snowflake-arctic-embed2` (used by NOMAD PR #1367).
- Pitfall: The Ollama-registry GGUF had invalid `tokenizer.ggml.precompiled_charsmap` metadata (llama.cpp #14018, 2025-06) - use a Hugging Face GGUF.
- Pitfall: ~2.7x nomic-v1.5 per-token compute (303M non-embedding) [computed].
- Pitfall: 1024-d vectors: Qdrant collection must be recreated; NOMAD hard-codes 768.
- Sources: <https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0> | <https://huggingface.co/Casual-Autopsy/snowflake-arctic-embed-l-v2.0-gguf> | <https://github.com/ggml-org/llama.cpp/issues/14018> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-l-v2.0/edc2df7b6c25794b340229ca082e7c78782e6374>

### 7. snowflake-arctic-embed-m-v2.0  (`Snowflake/snowflake-arctic-embed-m-v2.0`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 305M, non-emb 113M = 1.00x; native dim 768; context 8192 tokens - card: built on GTE-multilingual-base, 8192 via RoPE.
- **Prefixes / pooling:** query `'query: '`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims [768, 256]. BEIR(15) 55.4 @768d -> 54.4 @256d (-1.81%); MIRACL 55.2 -> 54.0; CLEF 51.7 -> 50.6 [self-reported, https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0].
- **Quantisation claims:** Same "quantization-aware" 128-byte claim as the l-v2.0 card.
- **MTEB(eng,v2) retrieval:** 58.41 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-m-v2.0/f2a7d59d80dfda5b1d14f096f3ce88bb6bf9ebdc>; per task: ArguAna 57.88, CQADupstackGamingRetrieval 65.32, CQADupstackUnixRetrieval 47.79, ClimateFEVERHardNegatives 38.68, FEVERHardNegatives 92.26, FiQA2018 44.17, HotpotQAHardNegatives 71.91, SCIDOCS 20.32, TRECCOVID 80.34, Touche2020Retrieval.v3 65.41
- **Wikipedia-based tasks:** v1: NQ 64.65 [L], HotpotQA 72.42 [L], DBPedia 43.94 [L], FEVER 91.67 [L], ClimateFEVER 38.05 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 71.91, FEVERHardNegatives 92.26, ClimateFEVERHardNegatives 38.68; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 93.76, MIRACLRetrievalHardNegatives[en] 56.77, MLQARetrieval[eng-eng] 70.7; Wiki5 66.06, HN3 67.62. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 55.4 [self-reported] <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0>; computed from results repo 55.49 (leaderboard (v1 tasks; mix with model-card values where marked))
- **MMTEB retrieval:** computed 54.37 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, NQ, NQHardNegatives
- **llama.cpp:** no - arch GteModel (Alibaba GTE / "NewModel"). Evidence: HF config model_type "gte"; llama.cpp master LLM_ARCH_NAMES (2026-10-01) has no gte/new architecture; the only GGUF is for the separate embeddings.cpp project.
  - ONNX: <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0> - onnx/model_int8.onnx 310.9 MB, onnx/model_fp16.onnx 613.3 MB, onnx/model.onnx 1226.1 MB
- Note: Best English-Wikipedia-QA numbers among sub-400M models here (NQ 64.7, FEVER 91.7) but not servable by llama-server; ONNX int8/fp16 exports exist in the official repo (would need a different server).
- Pitfall: Not supported by llama.cpp -> out of the llama-server path.
- Pitfall: Needs trust_remote_code in HF.
- Sources: <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v2.0> | <https://huggingface.co/chux0519/snowflake-arctic-embed-m-v2.0-gguf-embeddings-cpp> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-m-v2.0/f2a7d59d80dfda5b1d14f096f3ce88bb6bf9ebdc>

### 8. snowflake-arctic-embed-m-v1.5 (older, relevant)  (`Snowflake/snowflake-arctic-embed-m-v1.5`)
- **Tier:** older (2024-07) but relevant: official GGUF. **Licence:** Apache-2.0. **Params:** 109M, non-emb 86M = 0.75x; native dim 768; context 512 tokens - BERT-base, 512 positions; official GGUF context_length=512.
- **Prefixes / pooling:** query `'Represent this sentence for searching relevant passages: '`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims [768, 256]. MTEB retrieval (v1, 15 tasks) 55.14 @768d vs 54.2 @256d, vs nomic-embed-text-v1.5 50.8 and OpenAI text-embedding-3-large 51.7 at 256d [self-reported, https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5]; "retains most of its quality down to 128 bytes per vector" (MRL + uniform scalar quantisation).
- **Quantisation claims:** MRL(256d) + uniform scalar quantisation to 128 bytes/vector (card).
- **MTEB(eng,v2) retrieval:** 58.05 - mixed: 7 tasks [leaderboard] + 3 task [self-reported model-card value] (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-m-v1.5/97eab2e17fcb7ccb8bb94d6e547898fa1a6a0f47>; per task: ArguAna 59.53, CQADupstackGamingRetrieval 62.69, CQADupstackUnixRetrieval 46.54, ClimateFEVERHardNegatives 37.26, FEVERHardNegatives 88.65, FiQA2018 42.4, HotpotQAHardNegatives 72.37, SCIDOCS 21.49, TRECCOVID 84.63, Touche2020Retrieval.v3 64.98
- **Wikipedia-based tasks:** v1: NQ 62.46 [S], HotpotQA 72.21 [S], DBPedia 45.55 [S], FEVER 88.41 [S], ClimateFEVER 36.85 [S]; v2 hard-negatives [L]: HotpotQAHardNegatives 72.37, FEVERHardNegatives 88.65, ClimateFEVERHardNegatives 37.26; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.52, MIRACLRetrievalHardNegatives[en] 56.7, MLQARetrieval[eng-eng] 70.1; Wiki5 65.02, HN3 66.09. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 55.14 [self-reported] <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5>; computed from results repo 55.16 (leaderboard (v1 tasks; mix with model-card values where marked))
- **MMTEB retrieval:** computed 38.51 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, NQ, NQ-NL, NQ-PL, NQHardNegatives
- **llama.cpp:** yes - arch bert. Evidence: official GGUF in the model repo (gguf/ folder): bert, context_length 512 (HF API); Snowflake publishes GGUFs only for this model, not for the v2.0 models.
  - GGUF (official): <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5> - Q8_0: `gguf/snowflake-arctic-embed-m-v1.5-q8_0.gguf` 117.9 MB; F16: `gguf/snowflake-arctic-embed-m-v1.5-f16.gguf` 219.5 MB
- Note: Dark horse: a 109M BERT-base model whose English Wikipedia-task scores are close to the 2026 models (Wiki5 65.0) at 0.75x nomic compute, same 768-d width, 118 MB Q8_0 official GGUF.
- Note: Its MTEB(eng,v2) retrieval average mixes 7 leaderboard tasks with 3 model-card values (CQADupstackGaming, CQADupstackUnix, FiQA2018).
- Pitfall: 512-token context: NOMAD's 3,000-character chunks would have to shrink to ~1,500 characters, which doubles the number of vectors for the same text [inference].
- Pitfall: Query prefix required (long English instruction).
- Sources: <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5> | <https://huggingface.co/Snowflake/snowflake-arctic-embed-m-v1.5/raw/main/config_sentence_transformers.json> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Snowflake__snowflake-arctic-embed-m-v1.5/97eab2e17fcb7ccb8bb94d6e547898fa1a6a0f47>

### 9. bge-m3  (`BAAI/bge-m3`)
- **Tier:** required. **Licence:** MIT. **Params:** 568M, non-emb 312M = 2.75x; native dim 1024; context 8192 tokens - card: up to 8192 tokens; GGUF context_length=8192.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS (GGUF pooling_type=2).
- **Matryoshka (MRL):** dims none. No MRL (llama.cpp PR #24898 text lists bge-m3 as "not supported").
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 6/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/BAAI__bge-m3/5617a9f61b028005a4858fdac845db406aefb181>); covered tasks: ArguAna 54.04, ClimateFEVERHardNegatives 29.85, FEVERHardNegatives 81.72, HotpotQAHardNegatives 69.49, SCIDOCS 16.31, TRECCOVID 54.72
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: HotpotQAHardNegatives 69.49, FEVERHardNegatives 81.72, ClimateFEVERHardNegatives 29.85; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.58, MIRACLRetrievalHardNegatives[en] 57.72, MLQARetrieval[eng-eng] 70.71; Wiki5 61.9, HN3 60.35. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 48.8 [self-reported] <https://huggingface.co/Snowflake/snowflake-arctic-embed-l-v2.0>
- **MMTEB retrieval:** computed 54.27 [L]; 54.6 [S] <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- **Declared training overlap (MTEB model_meta):** HotpotQA, HotpotQA-NL, HotpotQAHardNegatives, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MSMARCO, MSMARCOHardNegatives, MrTidyRetrieval, NQ, NQ-NL, NQ-PL, NQHardNegatives, NanoNQRetrieval
- **llama.cpp:** yes - arch bert (XLM-RoBERTa large). Evidence: ggml-org GGUF header (2026-10-01): bert, pooling_type=2 (CLS), context_length=8192, tokenizer t5.
  - GGUF (official): <https://huggingface.co/ggml-org/bge-m3-Q8_0-GGUF> - Q8_0: `bge-m3-q8_0.gguf` 634.6 MB; extra: Q4_K_M: `gpustack/bge-m3-GGUF/bge-m3-Q4_K_M.gguf` 437.8 MB; FP16: `gpustack/bge-m3-GGUF/bge-m3-FP16.gguf` 1157.7 MB
- Note: Card: "The only difference is that the BGE-M3 model no longer requires adding instructions to the queries."
- Note: Only the dense vector is available through llama.cpp (sparse and ColBERT outputs are not).
- Note: NOMAD PR #1367 eval (28-doc corpus): English recall@5 0.995, cross-language 0.990 (best of the five).
- Pitfall: English MTEB(eng,v2) retrieval is incomplete in the results repo (6/10 tasks) so no 10-task average is shown.
- Pitfall: ~2.75x nomic-v1.5 compute; 1024-d.
- Sources: <https://huggingface.co/BAAI/bge-m3> | <https://huggingface.co/ggml-org/bge-m3-Q8_0-GGUF> | <https://huggingface.co/gpustack/bge-m3-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/BAAI__bge-m3/5617a9f61b028005a4858fdac845db406aefb181>

### 10. jina-embeddings-v3  (`jinaai/jina-embeddings-v3`)
- **Tier:** required. **Licence:** CC-BY-NC-4.0 (non-commercial). **Params:** 572M, non-emb 316M = 2.79x; native dim 1024; context 8192 tokens - card: RoPE, up to 8192 tokens.
- **Prefixes / pooling:** query `'task adapter retrieval.query (LoRA; no text prefix)'`; document `'task adapter retrieval.passage'`; pooling mean.
- **Matryoshka (MRL):** dims [32, 64, 128, 256, 512, 768, 1024]. Dims listed in the card; no table. Card note: an earlier encode() truncated after normalisation (fixed, HF discussion #60).
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 54.29 - mixed: 7 tasks [leaderboard] + 3 task [self-reported model-card value] (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v3/215a6e121fa0183376388ac6b1ae230326bfeaed>; per task: ArguAna 43.29, CQADupstackGamingRetrieval 58.02, CQADupstackUnixRetrieval 43.52, ClimateFEVERHardNegatives 43.14, FEVERHardNegatives 89.9, FiQA2018 47.35, HotpotQAHardNegatives 64.7, SCIDOCS 19.92, TRECCOVID 77.74, Touche2020Retrieval.v3 55.28
- **Wikipedia-based tasks:** v1: NQ 64.23 [S], HotpotQA 64.67 [S], DBPedia 41.0 [S], FEVER 89.05 [S], ClimateFEVER 42.36 [S]; v2 hard-negatives [L]: HotpotQAHardNegatives 64.7, FEVERHardNegatives 89.9, ClimateFEVERHardNegatives 43.14; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 91.85, MIRACLRetrievalHardNegatives[en] 52.01, MLQARetrieval[eng-eng] 64.67; Wiki5 62.88, HN3 65.91. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 53.17 (leaderboard (v1 tasks; mix with model-card values where marked))
- **MMTEB retrieval:** computed 55.34 [L]
- **Declared training overlap (MTEB model_meta):** MSMARCO, MSMARCOHardNegatives, NQ, NQ-NL, NQ-PL, NQHardNegatives, NanoNQRetrieval
- **llama.cpp:** yes - arch jina-bert-v3. Evidence: community GGUF (second-state) header: jina-bert-v3, context 8192; LoRA adapters as separate GGUF files.
  - GGUF (community): <https://huggingface.co/second-state/jina-embeddings-v3-GGUF> - Q8_0: `jina-embeddings-v3-Q8_0.gguf` 601.0 MB; Q4: `jina-embeddings-v3-Q4_K_M.gguf` 410.4 MB; F16: `jina-embeddings-v3-f16.gguf` 1124.1 MB
- Note: Task LoRAs are separate 10.3 MB GGUFs (lora-retrieval.query/.passage) that must be loaded with --lora.
- Pitfall: Non-commercial licence.
- Pitfall: LoRA handling in llama-server is extra work.
- Sources: <https://huggingface.co/jinaai/jina-embeddings-v3> | <https://huggingface.co/second-state/jina-embeddings-v3-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v3/215a6e121fa0183376388ac6b1ae230326bfeaed>

### 11. jina-embeddings-v4 (reference)  (`jinaai/jina-embeddings-v4`)
- **Tier:** reference (3.8B, too large). **Licence:** Qwen Research License (card: "The correct license is the Qwen Research License"; MTEB metadata says cc-by-nc-4.0). **Params:** 3755M; native dim 2048; context 32768 tokens - card: Max Sequence Length 32768.
- **Prefixes / pooling:** query `'Query: '`; document `'Passage: '`; pooling mean.
- **Matryoshka (MRL):** dims [128, 256, 512, 1024, 2048]. "can be truncated to as low as 128 with minimal performance degradation" (card); no table.
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 56.15 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v4/26239889730c735ed7e9a4db9180c8935faf4ba0>; per task: ArguAna 66.96, CQADupstackGamingRetrieval 57.59, CQADupstackUnixRetrieval 42.95, ClimateFEVERHardNegatives 34.57, FEVERHardNegatives 87.69, FiQA2018 48.49, HotpotQAHardNegatives 69.01, SCIDOCS 21.48, TRECCOVID 80.36, Touche2020Retrieval.v3 52.41
- **Wikipedia-based tasks:** v1: NQ 61.68 [L], DBPedia 43.94 [L], ClimateFEVER 35.06 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 69.01, FEVERHardNegatives 87.69, ClimateFEVERHardNegatives 34.57; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.75, MLQARetrieval[eng-eng] 67.46; Wiki5 None, HN3 63.76. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** partial 66.83 (15/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** MSMARCO, MSMARCOHardNegatives, NQ, NQ-NL, NQ-PL, NQHardNegatives, NanoNQRetrieval
- **llama.cpp:** yes - arch qwen2vl (text-only GGUF). Evidence: official text-retrieval GGUF repo, arch qwen2vl.
  - GGUF (official): <https://huggingface.co/jinaai/jina-embeddings-v4-text-retrieval-GGUF> - Q8_0: `jina-embeddings-v4-text-retrieval-Q8_0.gguf` 3285.5 MB; Q4: `jina-embeddings-v4-text-retrieval-Q4_K_M.gguf` 1929.9 MB; F16: `jina-embeddings-v4-text-retrieval-F16.gguf` 6178.3 MB
- Note: Reference only (3.09B text-only GGUF, Q8_0 3.29 GB).
- Pitfall: Prefixes must be added by hand in llama-server (Jina blog).
- Sources: <https://huggingface.co/jinaai/jina-embeddings-v4> | <https://huggingface.co/jinaai/jina-embeddings-v4-text-retrieval-GGUF> | <https://jina.ai/news/optimizing-ggufs-for-decoder-only-embedding-models> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v4/26239889730c735ed7e9a4db9180c8935faf4ba0>

### 12. jina-embeddings-v5-text-small  (`jinaai/jina-embeddings-v5-text-small`)
- **Tier:** required. **Licence:** CC-BY-NC-4.0 ("For commercial use, please contact us" - GGUF card). **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 32768 tokens - card: Max Sequence Length 32768 (GGUF header 40960).
- **Prefixes / pooling:** query `'Query: '`; document `'Document: '`; pooling last token (GGUF pooling_type=3).
- **Matryoshka (MRL):** dims [32, 64, 128, 256, 512, 768, 1024]. Paper (https://arxiv.org/abs/2602.15547, Fig. 5): MMTEB retrieval average vs dimension - "sizable decline ... when the embedding dimensions fall below 256"; no table in text. Card/blog: robust under truncation and binary quantisation (GOR regulariser).
- **Quantisation claims:** "Robust under truncation and binary quantization"; GOR regularisation makes binary quantisation "nearly lossless" (Jina blog).
- **MTEB(eng,v2) retrieval:** 60.07 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v5-text-small/46ed7da5b47e4bca710b756313fafaf4110c6bd1>; per task: ArguAna 65.07, CQADupstackGamingRetrieval 62.16, CQADupstackUnixRetrieval 49.61, ClimateFEVERHardNegatives 41.75, FEVERHardNegatives 90.46, FiQA2018 49.63, HotpotQAHardNegatives 69.94, SCIDOCS 23.04, TRECCOVID 78.49, Touche2020Retrieval.v3 70.59
- **Wikipedia-based tasks:** v1: NQ 64.04 [L], HotpotQA 69.76 [L], DBPedia 44.38 [L], FEVER 89.99 [L], ClimateFEVER 41.5 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 69.94, FEVERHardNegatives 90.46, ClimateFEVERHardNegatives 41.75; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 94.06, MIRACLRetrievalHardNegatives[en] 56.93, MLQARetrieval[eng-eng] 72.45; Wiki5 66.31, HN3 67.38. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 56.67 (leaderboard)
- **MMTEB retrieval:** computed 64.62 [L]
- **Vendor overall claims [S]:** MTEB(eng,v2) overall mean 71.7, MMTEB overall 67.7 - <https://huggingface.co/jinaai/jina-embeddings-v5-text-small>
- **llama.cpp:** yes - arch qwen3. Evidence: official GGUF header (2026-10-01): qwen3, pooling_type=3, rope_freq_base 3.5M.
  - GGUF (official): <https://huggingface.co/jinaai/jina-embeddings-v5-text-small-retrieval-GGUF> - Q8_0: `v5-small-retrieval-Q8_0.gguf` 639.4 MB; Q4: `v5-small-retrieval-Q4_K_M.gguf` 396.7 MB; F16: `v5-small-retrieval-F16.gguf` 1198.2 MB
- Note: Task-specific retrieval checkpoint merged with the retrieval adapter (596M weights; "677M" in the card includes four LoRA adapters).
- Note: Distilled from Qwen3-Embedding-4B (card).
- Pitfall: Non-commercial licence (personal use is fine; flag for any redistribution).
- Pitfall: llama.cpp #26282: batched requests with --parallel>1 returned vectors drifting by L2~0.02 for jina-v5 (nano/small) retrieval GGUFs on a CPU build; closed by the stale bot 2026-09-13 without a fix -> run a determinism test before bulk indexing with -np>1.
- Sources: <https://huggingface.co/jinaai/jina-embeddings-v5-text-small> | <https://huggingface.co/jinaai/jina-embeddings-v5-text-small-retrieval-GGUF> | <https://huggingface.co/jinaai/jina-embeddings-v5-text-small-retrieval/raw/main/config_sentence_transformers.json> | <https://arxiv.org/abs/2602.15547> | <https://jina.ai/news/jina-embeddings-v5-text-distilling-4b-quality-into-sub-1b-multilingual-embeddings/> | <https://github.com/ggml-org/llama.cpp/issues/26282> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v5-text-small/46ed7da5b47e4bca710b756313fafaf4110c6bd1>

### 13. jina-embeddings-v5-text-nano  (`jinaai/jina-embeddings-v5-text-nano`)
- **Tier:** required. **Licence:** CC-BY-NC-4.0. **Params:** 212M, non-emb 113M = 1.00x; native dim 768; context 8192 tokens - card: Max Sequence Length 8192.
- **Prefixes / pooling:** query `'Query: '`; document `'Document: '`; pooling last token (GGUF pooling_type=3).
- **Matryoshka (MRL):** dims [32, 64, 128, 256, 512, 768]. Same paper figure as small (decline below 256 dims); no table.
- **Quantisation claims:** Same GOR / binary-robustness claim as small.
- **MTEB(eng,v2) retrieval:** 58.80 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v5-text-nano/4c1f9846bb85490df1d9e535834cf00ceb33823b>; per task: ArguAna 65.7, CQADupstackGamingRetrieval 61.6, CQADupstackUnixRetrieval 47.4, ClimateFEVERHardNegatives 40.03, FEVERHardNegatives 89.82, FiQA2018 47.85, HotpotQAHardNegatives 69.28, SCIDOCS 22.6, TRECCOVID 77.6, Touche2020Retrieval.v3 66.12
- **Wikipedia-based tasks:** v1: NQ 63.38 [L], HotpotQA 69.07 [L], DBPedia 45.26 [L], FEVER 89.51 [L], ClimateFEVER 39.6 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 69.28, FEVERHardNegatives 89.82, ClimateFEVERHardNegatives 40.03; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 93.59, MIRACLRetrievalHardNegatives[en] 56.11, MLQARetrieval[eng-eng] 71.71; Wiki5 65.39, HN3 66.38. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 56.06 (leaderboard)
- **MMTEB retrieval:** computed 63.03 [L]
- **Vendor overall claims [S]:** MTEB(eng,v2) overall mean 71.0, MMTEB overall 65.5 - <https://huggingface.co/jinaai/jina-embeddings-v5-text-nano>
- **llama.cpp:** yes - arch eurobert. Evidence: EuroBERT support merged into llama.cpp on 2026-02-26 (PR #19826); `eurobert` is in LLM_ARCH_NAMES on master; official GGUF header: eurobert, pooling_type=3, add_eos_token=true. (Model card still says "not yet supported ... use our branch" - stale.).
  - GGUF (official): <https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval-GGUF> - Q8_0: `v5-nano-retrieval-Q8_0.gguf` 232.9 MB; Q4: `v5-nano-retrieval-Q4_K_M.gguf` 157.0 MB; F16: `v5-nano-retrieval-F16.gguf` 431.4 MB
- Note: Built on EuroBERT-210M (212M weights in the merged retrieval checkpoint, "239M" in the card incl. adapters). Same per-token compute class as nomic-v1.5 (~113M non-embedding) [computed] - the best quality-per-FLOP entry in this survey.
- Pitfall: Non-commercial licence.
- Pitfall: Needs a llama.cpp build that contains the eurobert architecture (>= Feb 2026).
- Pitfall: llama.cpp #26282 batch-drift report (see small).
- Sources: <https://huggingface.co/jinaai/jina-embeddings-v5-text-nano> | <https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval-GGUF> | <https://github.com/ggml-org/llama.cpp/pull/19826> | <https://github.com/ggml-org/llama.cpp/issues/26282> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/jinaai__jina-embeddings-v5-text-nano/4c1f9846bb85490df1d9e535834cf00ceb33823b>

### 14. granite-embedding-english-r2  (`ibm-granite/granite-embedding-english-r2`)
- **Tier:** required. **Licence:** Apache-2.0 (trained only on permissively licensed open data, per card). **Params:** 149M, non-emb 110M = 0.97x; native dim 768; context 8192 tokens - card: context length up to 8192.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS; vectors are unnormalised -> normalise.
- **Matryoshka (MRL):** dims none. none claimed for the English R2 models.
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 56.43 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-english-r2/6e7b8ce0e76270394ac4669ba4bbd7133b60b7f9>; per task: ArguAna 59.21, CQADupstackGamingRetrieval 65.05, CQADupstackUnixRetrieval 52.85, ClimateFEVERHardNegatives 35.97, FEVERHardNegatives 88.92, FiQA2018 46.32, HotpotQAHardNegatives 67.08, SCIDOCS 24.95, TRECCOVID 70.56, Touche2020Retrieval.v3 53.43
  - card value 56.4 [self-reported]: <https://huggingface.co/ibm-granite/granite-embedding-english-r2>
- **Wikipedia-based tasks:** v1: NQ 58.22 [L], HotpotQA 67.36 [L], DBPedia 39.6 [L], FEVER 88.04 [L], ClimateFEVER 35.82 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 67.08, FEVERHardNegatives 88.92, ClimateFEVERHardNegatives 35.97; MMTEB English subsets [L]: MIRACLRetrievalHardNegatives[en] 45.17; Wiki5 None, HN3 63.99. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 53.1 [self-reported] <https://huggingface.co/ibm-granite/granite-embedding-english-r2>
- **MMTEB retrieval:** partial 53.69 (7/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MrTidyRetrieval, NQ, NQ-NL, NQHardNegatives, WikipediaRerankingMultilingual, WikipediaRetrievalMultilingual
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF header (mradermacher): modern-bert, context_length 8192; llama.cpp has modern-bert.
  - GGUF (community): <https://huggingface.co/mradermacher/granite-embedding-english-r2-GGUF> - Q8_0: `granite-embedding-english-r2.Q8_0.gguf` 160.2 MB; Q4: `granite-embedding-english-r2.Q4_K_M.gguf` 106.3 MB; F16: `granite-embedding-english-r2.f16.gguf` 299.9 MB
- Note: ModernBERT-base class (22 layers, 768 wide, ~110M non-embedding) so compute is about 1x nomic-v1.5 [computed].
- Note: IBM card table also lists gte-modernbert-base at MTEB-v2 Retrieval(10) 57.0 and arctic-embed-m-v2.0 at 58.4 (third-party numbers).
- Pitfall: Output not normalised by the model (llama-server normalises with L2 by default).
- Pitfall: Community GGUF only.
- Sources: <https://huggingface.co/ibm-granite/granite-embedding-english-r2> | <https://huggingface.co/mradermacher/granite-embedding-english-r2-GGUF> | <https://arxiv.org/abs/2508.21085> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-english-r2/6e7b8ce0e76270394ac4669ba4bbd7133b60b7f9>

### 15. granite-embedding-small-english-r2  (`ibm-granite/granite-embedding-small-english-r2`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 48M, non-emb 28M = 0.25x; native dim 384; context 8192 tokens - card: 8192.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 53.93 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-small-english-r2/54a8d2616a0844355a5164432d3f6dafb37b17a3>; per task: ArguAna 54.4, CQADupstackGamingRetrieval 62.44, CQADupstackUnixRetrieval 51.13, ClimateFEVERHardNegatives 31.69, FEVERHardNegatives 87.58, FiQA2018 40.81, HotpotQAHardNegatives 66.23, SCIDOCS 24.06, TRECCOVID 64.67, Touche2020Retrieval.v3 56.25
- **Wikipedia-based tasks:** v1: NQ 55.37 [L], HotpotQA 65.65 [L], DBPedia 37.85 [L], FEVER 86.48 [L], ClimateFEVER 31.56 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 66.23, FEVERHardNegatives 87.58, ClimateFEVERHardNegatives 31.69; MMTEB English subsets [L]: MIRACLRetrievalHardNegatives[en] 44.58; Wiki5 None, HN3 61.83. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 50.9 [self-reported] <https://huggingface.co/ibm-granite/granite-embedding-small-english-r2>
- **MMTEB retrieval:** partial 50.49 (7/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MrTidyRetrieval, NQ, NQ-NL, NQHardNegatives, WikipediaRerankingMultilingual, WikipediaRetrievalMultilingual
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF: modern-bert.
  - GGUF (community): <https://huggingface.co/mradermacher/granite-embedding-small-english-r2-GGUF> - Q8_0: `granite-embedding-small-english-r2.Q8_0.gguf` 52.4 MB; Q4: `granite-embedding-small-english-r2.Q4_K_M.gguf` 42.2 MB; F16: `granite-embedding-small-english-r2.f16.gguf` 97.1 MB
- Note: 47M parameters, 384-d: the cheapest model here (~0.25x nomic compute, half the vector size) but retrieval 53.9 on MTEB(eng,v2) (+6 over nomic-v1.5).
- Sources: <https://huggingface.co/ibm-granite/granite-embedding-small-english-r2> | <https://huggingface.co/mradermacher/granite-embedding-small-english-r2-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-small-english-r2/54a8d2616a0844355a5164432d3f6dafb37b17a3>

### 16. granite-embedding-311m-multilingual-r2  (`ibm-granite/granite-embedding-311m-multilingual-r2`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 312M, non-emb 110M = 0.97x; native dim 768; context 32768 tokens - card: context length up to 32,768 tokens.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims [768, 512, 384, 256, 128]. "graceful degradation" claimed, no table in card.
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 52.55 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-311m-multilingual-r2/dba7b0ee9d789f330fecfb85df57699f9e7d9c42>; per task: ArguAna 57.11, CQADupstackGamingRetrieval 58.64, CQADupstackUnixRetrieval 45.5, ClimateFEVERHardNegatives 30.5, FEVERHardNegatives 83.7, FiQA2018 39.88, HotpotQAHardNegatives 63.82, SCIDOCS 21.86, TRECCOVID 68.44, Touche2020Retrieval.v3 56.05
- **Wikipedia-based tasks:** v1: NQ 55.83 [L], HotpotQA 62.35 [L], DBPedia 34.44 [L], FEVER 82.23 [L], ClimateFEVER 29.92 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 63.82, FEVERHardNegatives 83.7, ClimateFEVERHardNegatives 30.5; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 91.99, MIRACLRetrievalHardNegatives[en] 45.46, MLQARetrieval[eng-eng] 63.36; Wiki5 57.37, HN3 59.34. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 49.25 (leaderboard)
- **MMTEB retrieval:** computed 64.56 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVERHardNegatives, HotPotQA, HotpotQAHardNegatives, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MrTidyRetrieval, NQ, NQHardNegatives
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF (mykor): modern-bert, context_length 8192 in header.
  - GGUF (community): <https://huggingface.co/mykor/granite-embedding-311m-multilingual-r2-GGUF> - Q8_0: `granite-embedding-311M-multilingual-r2-Q8_0.gguf` 347.0 MB; Q4: `granite-embedding-311M-multilingual-r2-Q4_K_M.gguf` 253.4 MB; F16: `granite-embedding-311M-multilingual-r2-BF16.gguf` 639.2 MB
- Note: Released 2026-04-29; ~201M of 312M parameters are vocabulary embeddings, so compute ~1x nomic-v1.5.
- Sources: <https://huggingface.co/ibm-granite/granite-embedding-311m-multilingual-r2> | <https://huggingface.co/mykor/granite-embedding-311m-multilingual-r2-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-311m-multilingual-r2/dba7b0ee9d789f330fecfb85df57699f9e7d9c42>

### 17. granite-embedding-97m-multilingual-r2  (`ibm-granite/granite-embedding-97m-multilingual-r2`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 97M, non-emb 28M = 0.25x; native dim 384; context 32768 tokens - HF config max_position_embeddings=32768.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims none. not checked
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 50.09 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-97m-multilingual-r2/c61e626a6255c490879d0af885078b61929d51f6>; per task: ArguAna 53.09, CQADupstackGamingRetrieval 55.87, CQADupstackUnixRetrieval 41.77, ClimateFEVERHardNegatives 28.01, FEVERHardNegatives 85.6, FiQA2018 34.4, HotpotQAHardNegatives 61.7, SCIDOCS 20.36, TRECCOVID 66.27, Touche2020Retrieval.v3 53.89
- **Wikipedia-based tasks:** v1: NQ 51.44 [L], HotpotQA 60.75 [L], DBPedia 31.95 [L], FEVER 84.28 [L], ClimateFEVER 27.77 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 61.7, FEVERHardNegatives 85.6, ClimateFEVERHardNegatives 28.01; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 90.39, MIRACLRetrievalHardNegatives[en] 45.39, MLQARetrieval[eng-eng] 61.52; Wiki5 56.44, HN3 58.44. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 47.34 (leaderboard)
- **MMTEB retrieval:** computed 59.62 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVERHardNegatives, HotPotQA, HotpotQAHardNegatives, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MrTidyRetrieval, NQ, NQHardNegatives
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF (mykor): modern-bert.
  - GGUF (community): <https://huggingface.co/mykor/granite-embedding-97m-multilingual-r2-GGUF> - Q8_0: `granite-embedding-97M-multilingual-r2-Q8_0.gguf` 115.1 MB; Q4: `granite-embedding-97M-multilingual-r2-Q4_K_M.gguf` 105.5 MB; F16: `granite-embedding-97M-multilingual-r2-BF16.gguf` 206.4 MB
- Note: Tiny multilingual model (384-d); English retrieval 50.1 on MTEB(eng,v2).
- Sources: <https://huggingface.co/ibm-granite/granite-embedding-97m-multilingual-r2> | <https://huggingface.co/mykor/granite-embedding-97m-multilingual-r2-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-97m-multilingual-r2/c61e626a6255c490879d0af885078b61929d51f6>

### 18. granite-embedding-125m-english (R1)  (`ibm-granite/granite-embedding-125m-english`)
- **Tier:** required (older "english"). **Licence:** Apache-2.0. **Params:** 125M, non-emb 86M = 0.76x; native dim 768; context 512 tokens - RoBERTa-based, 512 positions.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 55.65 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-125m-english/e48d3a5b47eaa18e3fe07d4676e187fd80f32730>; per task: ArguAna 58.4, CQADupstackGamingRetrieval 63.64, CQADupstackUnixRetrieval 51.3, ClimateFEVERHardNegatives 33.09, FEVERHardNegatives 90.03, FiQA2018 44.93, HotpotQAHardNegatives 68.14, SCIDOCS 24.15, TRECCOVID 69.26, Touche2020Retrieval.v3 53.59
- **Wikipedia-based tasks:** v1: NQ 58.04 [L], HotpotQA 67.78 [L], DBPedia 39.41 [L], FEVER 88.23 [L], ClimateFEVER 33.15 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 68.14, FEVERHardNegatives 90.03, ClimateFEVERHardNegatives 33.09; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.33, MIRACLRetrievalHardNegatives[en] 43.58, MLQARetrieval[eng-eng] 64.79; Wiki5 59.93, HN3 63.75. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 52.3 [self-reported] <https://huggingface.co/ibm-granite/granite-embedding-english-r2>; computed from results repo 52.26 (leaderboard)
- **MMTEB retrieval:** computed 38.96 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotPotQA, HotPotQA-PL, HotPotQAHardNegatives, HotpotQA-NL, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MrTidyRetrieval, NQ, NQ-NL, NQHardNegatives, WikipediaRerankingMultilingual, WikipediaRetrievalMultilingual
- **llama.cpp:** yes - arch bert (RoBERTa). Evidence: bartowski GGUF: bert, context 512.
  - GGUF (community): <https://huggingface.co/bartowski/granite-embedding-125m-english-GGUF> - Q8_0: `granite-embedding-125m-english-Q8_0.gguf` 135.1 MB; Q4: `granite-embedding-125m-english-Q4_K_M.gguf` 87.8 MB; F16: `granite-embedding-125m-english-f16.gguf` 250.9 MB
- Note: Superseded by english-r2 (same dim, longer context, +0.7 BEIR / +0.8 retrieval).
- Pitfall: 512-token context.
- Sources: <https://huggingface.co/ibm-granite/granite-embedding-125m-english> | <https://huggingface.co/bartowski/granite-embedding-125m-english-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/ibm-granite__granite-embedding-125m-english/e48d3a5b47eaa18e3fe07d4676e187fd80f32730>

### 19. mxbai-embed-large-v1  (`mixedbread-ai/mxbai-embed-large-v1`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 335M, non-emb 304M = 2.68x; native dim 1024; context 512 tokens - BERT-large, max_position_embeddings=512; GGUF context_length=512.
- **Prefixes / pooling:** query `'Represent this sentence for searching relevant passages: '`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims MRL supported (truncate_dim example 512); exact dim list not published in card. no table in card
- **Quantisation claims:** card shows int8 and binary (ubinary) quantisation helpers; no numbers quoted here
- **MTEB(eng,v2) retrieval:** 55.40 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/mixedbread-ai__mxbai-embed-large-v1/990580e27d329c7408b3741ecff85876e128e203>; per task: ArguAna 65.47, CQADupstackGamingRetrieval 58.94, CQADupstackUnixRetrieval 41.77, ClimateFEVERHardNegatives 36.23, FEVERHardNegatives 86.54, FiQA2018 45.27, HotpotQAHardNegatives 72.5, SCIDOCS 23.1, TRECCOVID 75.53, Touche2020Retrieval.v3 48.6
- **Wikipedia-based tasks:** v1: NQ 55.8 [L], HotpotQA 72.04 [L], DBPedia 44.52 [L], FEVER 86.92 [L], ClimateFEVER 36.1 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 72.5, FEVERHardNegatives 86.54, ClimateFEVERHardNegatives 36.23; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 91.98, MIRACLRetrievalHardNegatives[en] 51.89, MLQARetrieval[eng-eng] 66.6; Wiki5 62.75, HN3 65.09. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 56.16 (leaderboard)
- **MMTEB retrieval:** computed 40.02 [L]
- **Declared training overlap (MTEB model_meta):** MSMARCO
- **llama.cpp:** yes - arch bert. Evidence: ChristianAzinn GGUF header: bert, context_length 512.
  - GGUF (community): <https://huggingface.co/ChristianAzinn/mxbai-embed-large-v1-gguf> - Q8_0: `mxbai-embed-large-v1.Q8_0.gguf` 358.2 MB; Q4: `mxbai-embed-large-v1.Q4_K_M.gguf` 215.9 MB; F16: `mxbai-embed-large-v1_fp16.gguf` 669.6 MB
- Note: March 2024 model; strong on BEIR (56.2 computed) but old, 512-token limit.
- Pitfall: 512-token context vs NOMAD 3,000-char chunks.
- Pitfall: ~2.7x nomic compute.
- Sources: <https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1> | <https://huggingface.co/ChristianAzinn/mxbai-embed-large-v1-gguf> | <https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1/raw/main/config_sentence_transformers.json> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/mixedbread-ai__mxbai-embed-large-v1/990580e27d329c7408b3741ecff85876e128e203>

### 20. gte-modernbert-base  (`Alibaba-NLP/gte-modernbert-base`)
- **Tier:** required. **Licence:** Apache-2.0. **Params:** 149M, non-emb 110M = 0.97x; native dim 768; context 8192 tokens - card: Max Seq. Length 8192.
- **Prefixes / pooling:** query `'(none)'`; document `'(none)'`; pooling CLS.
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 6/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Alibaba-NLP__gte-modernbert-base/7ca8b4ca700621b67618669f5378fe5f5820b8e4>); covered tasks: ArguAna 74.56, CQADupstackGamingRetrieval 60.4, CQADupstackUnixRetrieval 43.43, FiQA2018 49.54, SCIDOCS 20.44, TRECCOVID 75.75; 57.0 [self-reported] <https://huggingface.co/ibm-granite/granite-embedding-english-r2>
- **Wikipedia-based tasks:** v1: NQ 56.1 [L], HotpotQA 70.39 [L], DBPedia 41.39 [L], FEVER 93.97 [L], ClimateFEVER 45.9 [L]; v2 hard-negatives [L]: -; MMTEB English subsets [L]: -; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 55.33 [self-reported] <https://huggingface.co/Alibaba-NLP/gte-modernbert-base>; computed from results repo 55.26 (leaderboard)
- **MMTEB retrieval:** partial 65.4 (4/18 tasks) [L]
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF (keisuke-miyako) header: modern-bert, context 8192.
  - GGUF (community): <https://huggingface.co/keisuke-miyako/gte-modernbert-base-gguf> - Q8_0: `gte-modernbert-base-Q8_0.gguf` 160.2 MB; Q4: `gte-modernbert-base-Q4_k_m.gguf` 106.3 MB; F16: `gte-modernbert-base-F16.gguf` 299.9 MB
- Note: Leaderboard revision has only 6/10 MTEB(eng,v2) retrieval tasks, so the table shows IBM-reported 57.0 [self-reported, third party] instead; the v1 tasks (BEIR 15/15) are full leaderboard runs: FEVER 94.0 is the highest of all models here, HotpotQA 70.4, NQ 56.1.
- Pitfall: Community GGUF only (a second repo, cstr/gte-modernbert-base-GGUF, carries arch "bert" with a custom conversion - avoid).
- Sources: <https://huggingface.co/Alibaba-NLP/gte-modernbert-base> | <https://huggingface.co/keisuke-miyako/gte-modernbert-base-gguf> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Alibaba-NLP__gte-modernbert-base/7ca8b4ca700621b67618669f5378fe5f5820b8e4>

### 21. harrier-oss-v1-0.6b  (`microsoft/harrier-oss-v1-0.6b`)
- **Tier:** newer (2026-03). **Licence:** MIT. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 32768 tokens - card: Max Tokens 32,768.
- **Prefixes / pooling:** query `'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: '`; document `'(none)'`; pooling last token (GGUF pooling_type=3, add_eos).
- **Matryoshka (MRL):** dims none. no MRL claim in card
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 3/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/microsoft__harrier-oss-v1-0.6b/f9b9dc8d367d443f2479d27aa5d8d2850c0774ee>); covered tasks: ArguAna 64.99, SCIDOCS 23.36, TRECCOVID 86.95
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.58, MIRACLRetrievalHardNegatives[en] 56.5, MLQARetrieval[eng-eng] 70.74; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** computed 70.45 [L]
- **Vendor overall claims [S]:** MTEB(eng,v2) overall mean None, MMTEB overall 69.0 - <https://huggingface.co/microsoft/harrier-oss-v1-0.6b>
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQAHardNegatives, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch qwen3. Evidence: community GGUF (mradermacher) header: qwen3, pooling_type=3, add_eos_token=true.
  - GGUF (community): <https://huggingface.co/mradermacher/harrier-oss-v1-0.6b-GGUF> - Q8_0: `harrier-oss-v1-0.6b.Q8_0.gguf` 639.4 MB; Q4: `harrier-oss-v1-0.6b.Q4_K_M.gguf` 396.7 MB; F16: `harrier-oss-v1-0.6b.f16.gguf` 1198.2 MB
- Note: Multilingual specialist (MMTEB retrieval 70.4 computed, highest of the 0.6B class) but the results repo has only 3 of 10 English retrieval tasks; on those 3 (ArguAna/SCIDOCS/TRECCOVID) it averages 58.43 vs 61.97 for Qwen3-Embedding-0.6B -> no evidence it beats Qwen3 on English.
- Pitfall: Community GGUF only.
- Sources: <https://huggingface.co/microsoft/harrier-oss-v1-0.6b> | <https://huggingface.co/mradermacher/harrier-oss-v1-0.6b-GGUF> | <https://the-decoder.com/microsofts-bing-team-open-sources-harrier-embedding-model/> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/microsoft__harrier-oss-v1-0.6b/f9b9dc8d367d443f2479d27aa5d8d2850c0774ee>

### 22. harrier-oss-v1-270m  (`microsoft/harrier-oss-v1-270m`)
- **Tier:** newer (2026-03). **Licence:** MIT. **Params:** 268M, non-emb 100M = 0.89x; native dim 640; context 32768 tokens - card: 32,768 (sliding_window 512 in config).
- **Prefixes / pooling:** query `'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: '`; document `'(none)'`; pooling last token.
- **Matryoshka (MRL):** dims none. no MRL claim
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 3/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/microsoft__harrier-oss-v1-270m/31de22b673913c7d658c0f03f792d77c2dcf8ebd>); covered tasks: ArguAna 63.63, SCIDOCS 21.47, TRECCOVID 82.1
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 91.11, MIRACLRetrievalHardNegatives[en] 52.37, MLQARetrieval[eng-eng] 65.84; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** computed 65.93 [L]
- **Vendor overall claims [S]:** MTEB(eng,v2) overall mean None, MMTEB overall 66.5 - <https://huggingface.co/microsoft/harrier-oss-v1-270m>
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQAHardNegatives, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch gemma3. Evidence: community GGUF (mykor) header: gemma3, pooling_type=3.
  - GGUF (community): <https://huggingface.co/mykor/harrier-oss-v1-270m-GGUF> - Q8_0: `harrier-oss-v1-270M-Q8_0.gguf` 291.5 MB; Q4: `harrier-oss-v1-270M-Q4_K_M.gguf` 253.1 MB; F16: `harrier-oss-v1-270M-BF16.gguf` 542.8 MB
- Note: Gemma-3-270M based, 640-d; MMTEB retrieval 65.9 computed; English evidence thin (3 tasks).
- Pitfall: 640-d output.
- Sources: <https://huggingface.co/microsoft/harrier-oss-v1-270m> | <https://huggingface.co/mykor/harrier-oss-v1-270m-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/microsoft__harrier-oss-v1-270m/31de22b673913c7d658c0f03f792d77c2dcf8ebd>

### 23. pplx-embed-v1-0.6b  (`perplexity-ai/pplx-embed-v1-0.6b`)
- **Tier:** newer (2026-01). **Licence:** MIT. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 32768 tokens - card: 32K.
- **Prefixes / pooling:** query `'(none - "no instruction")'`; document `'(none)'`; pooling mean (bidirectional attention).
- **Matryoshka (MRL):** dims MRL: Yes (dims not listed in the card). none
- **Quantisation claims:** natively outputs unnormalised INT8 or BINARY embeddings (up to 32x smaller); compare with cosine
- **MTEB(eng,v2) retrieval:** not computable - only 3/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/perplexity-ai__pplx-embed-v1-0.6b/1dc2ea99a948a2f17b103949ad02b0194a20c0a8>); covered tasks: ArguAna 65.94, SCIDOCS 22.83, TRECCOVID 85.9
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 94.31, MIRACLRetrievalHardNegatives[en] 57.52, MLQARetrieval[eng-eng] 73.39; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** computed 65.05 [L]
- **llama.cpp:** yes (community GGUF) - arch qwen3 with attention.causal=false. Evidence: community GGUF header (mykor): qwen3, attention.causal=false, pooling_type=1 (mean).
  - GGUF (community): <https://huggingface.co/mykor/pplx-embed-v1-0.6b-GGUF> - Q8_0: `pplx-embed-v1-0.6B-Q8_0.gguf` 639.4 MB; Q4: `pplx-embed-v1-0.6B-Q4_K_M.gguf` 396.7 MB; F16: `pplx-embed-v1-0.6B-F16.gguf` 1198.2 MB
- Note: Diffusion-pretrained bidirectional Qwen3. Card claims (self-reported via press): pplx-embed-v1-4B MMTEB retrieval nDCG@10 69.66; no instruction prefix needed. Computed MMTEB retrieval for 0.6B: 65.1.
- Pitfall: Only 3/10 English retrieval tasks in the results repo.
- Pitfall: Community GGUF must keep attention.causal=false or the vectors are wrong.
- Sources: <https://huggingface.co/perplexity-ai/pplx-embed-v1-0.6b> | <https://huggingface.co/mykor/pplx-embed-v1-0.6b-GGUF> | <https://the-decoder.com/perplexity-open-sources-embedding-models-that-match-google-and-alibaba-at-a-fraction-of-the-memory-cost/> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/perplexity-ai__pplx-embed-v1-0.6b/1dc2ea99a948a2f17b103949ad02b0194a20c0a8>

### 24. Octen-Embedding-0.6B  (`Octen/Octen-Embedding-0.6B`)
- **Tier:** newer (2026-01). **Licence:** Apache-2.0. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 32768 tokens - card: 32,768.
- **Prefixes / pooling:** query `'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:'`; document `'(single space in the sentence-transformers config)'`; pooling last token (Qwen3-Embedding derivative).
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 0/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Octen__Octen-Embedding-0.6B/1a00a4e837bd788f6f8d91bc43201a5e52cf8ef8>); covered tasks: none
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: MIRACLRetrievalHardNegatives[en] 51.12; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** partial 80.51 (4/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQA, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch qwen3. Evidence: community GGUF (mradermacher) arch qwen3.
  - GGUF (community): <https://huggingface.co/mradermacher/Octen-Embedding-0.6B-GGUF> - Q8_0: `Octen-Embedding-0.6B.Q8_0.gguf` 639.2 MB; Q4: `Octen-Embedding-0.6B.Q4_K_M.gguf` 396.5 MB; F16: `Octen-Embedding-0.6B.f16.gguf` 1197.6 MB
- Note: LoRA fine-tune of Qwen3-Embedding-0.6B tuned for RTEB (legal/finance/healthcare/code); card reports RTEB Mean(Public) 0.7241 [self-reported]. No MTEB(eng,v2) results beyond 3 tasks; Octen-8B tops RTEB. Same compute as Qwen3-0.6B.
- Pitfall: No English-Wikipedia evidence; domain-tuned.
- Sources: <https://huggingface.co/Octen/Octen-Embedding-0.6B> | <https://huggingface.co/mradermacher/Octen-Embedding-0.6B-GGUF> | <https://octen-team.github.io/octen_blog/posts/octen-rteb-first-place/> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/Octen__Octen-Embedding-0.6B/1a00a4e837bd788f6f8d91bc43201a5e52cf8ef8>

### 25. KaLM-embedding-multilingual-mini-instruct-v2.5  (`KaLM-Embedding/KaLM-embedding-multilingual-mini-instruct-v2.5`)
- **Tier:** newer (2025-09). **Licence:** Apache-2.0. **Params:** 494M, non-emb 358M = 3.16x; native dim 896; context 512 tokens - HF config says 131072 positions (Qwen2) but the card sets model.max_seq_length = 512 and MTEB metadata lists 512.
- **Prefixes / pooling:** query `'Instruct: Given a query, retrieve documents that answer the query \n Query: '`; document `'(none)'`; pooling mean.
- **Matryoshka (MRL):** dims [896, 512, 256, 128, 64]. card shows an MRL evaluation figure (image); no table in text
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 58.46 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/KaLM-Embedding__KaLM-embedding-multilingual-mini-instruct-v2.5/6a4cfc1084cb459ebd4729b53a8656a61448c720>; per task: ArguAna 60.15, CQADupstackGamingRetrieval 65.52, CQADupstackUnixRetrieval 48.87, ClimateFEVERHardNegatives 35.06, FEVERHardNegatives 88.23, FiQA2018 47.1, HotpotQAHardNegatives 71.79, SCIDOCS 21.62, TRECCOVID 82.98, Touche2020Retrieval.v3 63.22
- **Wikipedia-based tasks:** v1: NQ 58.61 [L], HotpotQA 71.76 [L], DBPedia 42.62 [L], FEVER 87.89 [L], ClimateFEVER 34.5 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 71.79, FEVERHardNegatives 88.23, ClimateFEVERHardNegatives 35.06; MMTEB English subsets [L]: -; Wiki5 None, HN3 65.03. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 55.0 (leaderboard)
- **MMTEB retrieval:** partial 62.08 (4/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** FEVER, FEVER-NL, FEVERHardNegatives, HotpotQA-NL, HotpotQAHardNegatives, MIRACLRetrieval, MIRACLRetrievalHardNegatives, MSMARCO, MSMARCOHardNegatives, MrTidyRetrieval, NQ, NQ-NL, NQ-PL, NQHardNegatives, NanoNQRetrieval
- **llama.cpp:** yes - arch qwen2. Evidence: community GGUF (mradermacher) arch qwen2; official HIT-TMG GGUFs exist only for v1/v1.5.
  - GGUF (community): <https://huggingface.co/mradermacher/KaLM-embedding-multilingual-mini-instruct-v2.5-GGUF> - Q8_0: `KaLM-embedding-multilingual-mini-instruct-v2.5.Q8_0.gguf` 531.1 MB; Q4: `KaLM-embedding-multilingual-mini-instruct-v2.5.Q4_K_M.gguf` 397.8 MB; F16: `KaLM-embedding-multilingual-mini-instruct-v2.5.f16.gguf` 994.2 MB
- Note: 494M parameters; strong English retrieval (58.46 on 10/10 tasks) but 512-token evaluation length.
- Pitfall: 512-token practical limit; ~3.2x nomic compute.
- Sources: <https://huggingface.co/KaLM-Embedding/KaLM-embedding-multilingual-mini-instruct-v2.5> | <https://huggingface.co/mradermacher/KaLM-embedding-multilingual-mini-instruct-v2.5-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/KaLM-Embedding__KaLM-embedding-multilingual-mini-instruct-v2.5/6a4cfc1084cb459ebd4729b53a8656a61448c720>

### 26. F2LLM-v2-0.6B  (`codefuse-ai/F2LLM-v2-0.6B`)
- **Tier:** newer (2026-03). **Licence:** Apache-2.0. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 40960 tokens - HF config max_position_embeddings=40960.
- **Prefixes / pooling:** query `'Instruct: Given a question, retrieve passages that can help answer the question.\nQuery: '`; document `'(none)'`; pooling last token at EOS.
- **Matryoshka (MRL):** dims MRL trained (truncate to first d dims); figure only. card shows an MRL results image; no table in text
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** 54.31 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/codefuse-ai__F2LLM-v2-0.6B/54b4e2dc74e01be7126d4cf5f016af6b21edc563>; per task: ArguAna 59.25, CQADupstackGamingRetrieval 58.74, CQADupstackUnixRetrieval 48.26, ClimateFEVERHardNegatives 41.77, FEVERHardNegatives 91.31, FiQA2018 48.25, HotpotQAHardNegatives 65.56, SCIDOCS 22.19, TRECCOVID 49.82, Touche2020Retrieval.v3 57.92
- **Wikipedia-based tasks:** v1: NQ 60.9 [L], HotpotQA 65.22 [L], DBPedia 41.42 [L], FEVER 90.75 [L], ClimateFEVER 41.62 [L]; v2 hard-negatives [L]: HotpotQAHardNegatives 65.56, FEVERHardNegatives 91.31, ClimateFEVERHardNegatives 41.77; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 92.54, MIRACLRetrievalHardNegatives[en] 52.04, MLQARetrieval[eng-eng] 68.79; Wiki5 63.89, HN3 66.21. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** ; computed from results repo 51.37 (leaderboard)
- **MMTEB retrieval:** computed 58.99 [L]
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQA, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** yes - arch qwen3. Evidence: community GGUF (mradermacher) arch qwen3.
  - GGUF (community): <https://huggingface.co/mradermacher/F2LLM-v2-0.6B-GGUF> - Q8_0: `F2LLM-v2-0.6B.Q8_0.gguf` 639.4 MB; Q4: `F2LLM-v2-0.6B.Q4_K_M.gguf` 396.7 MB; F16: `F2LLM-v2-0.6B.f16.gguf` 1198.2 MB
- Note: Open data+code family (80M..14B). English retrieval 54.31 (10/10) is below Qwen3-0.6B (61.83) and nomic-v2-moe; the 330M sibling scores 53.34.
- Sources: <https://huggingface.co/codefuse-ai/F2LLM-v2-0.6B> | <https://huggingface.co/mradermacher/F2LLM-v2-0.6B-GGUF> | <https://arxiv.org/abs/2603.19223> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/codefuse-ai__F2LLM-v2-0.6B/54b4e2dc74e01be7126d4cf5f016af6b21edc563>

### 27. voyage-4-nano  (`voyageai/voyage-4-nano`)
- **Tier:** newer (2026-01). **Licence:** Apache-2.0. **Params:** 346M, non-emb 191M = 1.68x; native dim 2048; context 32000 tokens - card: Context Length 32000.
- **Prefixes / pooling:** query `'Represent the query for retrieving supporting documents: '`; document `'(none)'`; pooling mean (bidirectional Qwen3).
- **Matryoshka (MRL):** dims [2048, 1024, 512, 256]. no quality table in card
- **Quantisation claims:** quantisation-aware training: float32, int8, uint8 and binary outputs (card)
- **MTEB(eng,v2) retrieval:** not computable - only 0/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/mongodb__voyage-4-nano/29e841f72aa70c2802a92aff8c6eeb23229591b0>); covered tasks: none
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: -; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** partial 82.57 (2/18 tasks) [L]
- **llama.cpp:** unverified (community GGUF) - arch qwen3 (bidirectional). Evidence: community GGUF (jsonMartin) arch qwen3, ctx 40960; correctness needs attention.causal=false [not checked].
  - GGUF (community): <https://huggingface.co/jsonMartin/voyage-4-nano-gguf> - Q8_0: `voyage-4-nano-q8_0.gguf` 371.9 MB; F16: `voyage-4-nano-f16.gguf` 694.7 MB
- Note: 340M parameters (180M non-embedding + 160M embedding), shares its embedding space with the closed Voyage-4 models; native dimension 2048 (8 KB per float32 vector) - use MRL 256/512 to shrink.
- Note: Results repo has no MTEB(eng,v2)/MMTEB retrieval tasks for it (only 2-3 tasks).
- Pitfall: Largest native vector in the survey; community GGUF unverified for bidirectional attention.
- Sources: <https://huggingface.co/voyageai/voyage-4-nano> | <https://huggingface.co/jsonMartin/voyage-4-nano-gguf> | <https://blog.voyageai.com/2026/01/15/voyage-4/> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/mongodb__voyage-4-nano/29e841f72aa70c2802a92aff8c6eeb23229591b0>

### 28. LFM2.5-Embedding-350M  (`LiquidAI/LFM2.5-Embedding-350M`)
- **Tier:** newer (2026-05). **Licence:** LFM Open License v1.0 (HF tag "other"). **Params:** 354M, non-emb 287M = 2.54x; native dim 1024; context 512 tokens - card: "Document length: 512 tokens" (config 128000).
- **Prefixes / pooling:** query `'query: '`; document `'document: '`; pooling CLS.
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 0/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/LiquidAI__LFM2.5-Embedding-350M/85a23d142ff20a1204f4103ca0d4c86be06a9cfe>); covered tasks: none
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: -; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **llama.cpp:** yes - arch lfm2. Evidence: official GGUF repo (LiquidAI), arch lfm2 present in llama.cpp.
  - GGUF (official): <https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M-GGUF> - Q8_0: `LFM2.5-Embedding-350M-Q8_0.gguf` 379.2 MB; Q4: `LFM2.5-Embedding-350M-Q4_K_M.gguf` 229.3 MB; F16: `LFM2.5-Embedding-350M-F16.gguf` 711.5 MB
- Note: 11 languages; no results in the MTEB results repo -> no independent number.
- Pitfall: 512-token documents; non-OSI licence.
- Sources: <https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M> | <https://huggingface.co/LiquidAI/LFM2.5-Embedding-350M-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/LiquidAI__LFM2.5-Embedding-350M/85a23d142ff20a1204f4103ca0d4c86be06a9cfe>

### 29. DenseOn (LightOn)  (`lightonai/DenseOn`)
- **Tier:** newer (2026-03). **Licence:** Apache-2.0. **Params:** 149M, non-emb 110M = 0.97x; native dim 768; context 8192 tokens - ModernBERT config 8192; sentence-transformers default max_seq_length 512.
- **Prefixes / pooling:** query `'query: '`; document `'document: '`; pooling CLS.
- **Matryoshka (MRL):** dims none. none
- **Quantisation claims:** none
- **MTEB(eng,v2) retrieval:** not computable - only 6/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/lightonai__DenseOn/ec27cc88bc0899adbf4edf76e81ca4d2c9e390de>); covered tasks: ArguAna 54.65, CQADupstackGamingRetrieval 65.21, CQADupstackUnixRetrieval 47.52, FiQA2018 53.86, SCIDOCS 22.35, TRECCOVID 82.33
- **Wikipedia-based tasks:** v1: NQ 59.25 [L], HotpotQA 74.51 [L], DBPedia 44.65 [L], FEVER 90.69 [L], ClimateFEVER 37.49 [L]; v2 hard-negatives [L]: -; MMTEB English subsets [L]: -; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **BEIR(15):** 56.2 [self-reported] <https://huggingface.co/lightonai/DenseOn>; computed from results repo 56.2 (leaderboard)
- **MMTEB retrieval:** partial 53.11 (3/18 tasks) [L]
- **llama.cpp:** yes - arch modern-bert. Evidence: community GGUF (mradermacher) header: modern-bert, context 8192.
  - GGUF (community): <https://huggingface.co/mradermacher/DenseOn-GGUF> - Q8_0: `DenseOn.Q8_0.gguf` 160.2 MB; Q4: `DenseOn.Q4_K_M.gguf` 106.0 MB; F16: `DenseOn.f16.gguf` 299.9 MB
- Note: 149M ModernBERT dense retriever trained on an Apache-2.0-compatible dataset; best BEIR(15) of the ~150M class (56.2) incl. strong HotpotQA 74.5; results repo has only 6/10 MTEB(eng,v2) retrieval tasks.
- Pitfall: Community GGUF only; no MRL.
- Sources: <https://huggingface.co/lightonai/DenseOn> | <https://huggingface.co/mradermacher/DenseOn-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/lightonai__DenseOn/ec27cc88bc0899adbf4edf76e81ca4d2c9e390de>

### 30. Nemotron-3-Embed-1B  (`nvidia/Nemotron-3-Embed-1B-BF16`)
- **Tier:** newer, borderline size (2026-07). **Licence:** OpenMDW-1.1 (+ Apache-2.0 for code per card). **Params:** 1141M, non-emb 872M = 7.70x; native dim 2048; context 32768 tokens - card: max sequence length 32768.
- **Prefixes / pooling:** query `'not checked'`; document `'not checked'`; pooling mean (bidirectional).
- **Matryoshka (MRL):** dims none. not checked
- **Quantisation claims:** NVFP4 sibling repo exists
- **MTEB(eng,v2) retrieval:** not computable - only 0/10 of the 10 tasks are in the results repo (<https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nvidia__Nemotron-3-Embed-1B-BF16/f880174635613cff04033875fc6a69296cb72006>); covered tasks: none
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: -; MMTEB English subsets [L]: MIRACLRetrievalHardNegatives[en] 57.56; Wiki5 None, HN3 None. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** partial 77.95 (4/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** FEVER, HotpotQA, MIRACLRetrieval, NQ
- **llama.cpp:** unverified (community GGUF, arch mistral3) - arch mistral3 (Ministral-3 pruned). Evidence: community GGUF (nanoandrew4) arch mistral3; Q8_0 1.22 GB.
  - GGUF (community): <https://huggingface.co/nanoandrew4/Nemotron-3-Embed-1B-GGUF> - Q8_0: `model-Q8_0.gguf` 1220.3 MB; F16: `model-BF16.gguf` 2289.8 MB
- Note: 1.14B parameters pruned+distilled from Ministral-3-3B / Nemotron-3-Embed-8B; 2048-d. Only 4 MMTEB retrieval tasks in the results repo -> no comparable English number.
- Pitfall: Q8_0 alone is 1.22 GB (leaves almost nothing of a 1.5 GB budget); ~7.7x nomic compute [computed].
- Sources: <https://huggingface.co/nvidia/Nemotron-3-Embed-1B-BF16> | <https://huggingface.co/nanoandrew4/Nemotron-3-Embed-1B-GGUF> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/nvidia__Nemotron-3-Embed-1B-BF16/f880174635613cff04033875fc6a69296cb72006>

### 31. Yuan-embedding-2.0-en (flagged)  (`IEITYuan/Yuan-embedding-2.0-en`)
- **Tier:** flagged: implausible scores. **Licence:** Apache-2.0. **Params:** 596M, non-emb 440M = 3.89x; native dim 1024; context 2048 tokens - MTEB metadata max_tokens=2048.
- **Prefixes / pooling:** query `'instruction-based (custom loader)'`; document `'-'`; pooling -.
- **Matryoshka (MRL):** dims none. -
- **Quantisation claims:** -
- **MTEB(eng,v2) retrieval:** 70.69 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/IEITYuan__Yuan-embedding-2.0-en/b2fd15da3bcae3473c8529593825c15068f09fce>; per task: ArguAna 69.17, CQADupstackGamingRetrieval 81.61, CQADupstackUnixRetrieval 68.85, ClimateFEVERHardNegatives 59.05, FEVERHardNegatives 77.25, FiQA2018 59.41, HotpotQAHardNegatives 68.75, SCIDOCS 59.86, TRECCOVID 98.33, Touche2020Retrieval.v3 64.64
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: HotpotQAHardNegatives 68.75, FEVERHardNegatives 77.25, ClimateFEVERHardNegatives 59.05; MMTEB English subsets [L]: -; Wiki5 None, HN3 68.35. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** partial 75.96 (5/18 tasks) [L]
- **Declared training overlap (MTEB model_meta):** HotpotQA, MIRACLRetrieval, MSMARCO, MrTidyRetrieval, NQ
- **llama.cpp:** unverified (Qwen3 architecture; one community Q8_0 GGUF with 42 downloads) - arch qwen3. Evidence: HF config Qwen3ForCausalLM.
  - GGUF (community): <https://huggingface.co/NikosKprl/Yuan-embedding-2.0-en-Q8_0-GGUF> - 
- Note: Listed first on the MTEB(eng,v2) retrieval scan (70.69) but per-task numbers are not credible: SCIDOCS 59.86 (best known models 24-33), TRECCOVID 98.33, CQADupstackGaming 81.6, ClimateFEVER-HN 59.05 (Qwen3-8B: 49.0). Strong evidence of training on/near benchmark data -> ignore.
- Pitfall: Do not use the headline number.
- Sources: <https://huggingface.co/IEITYuan/Yuan-embedding-2.0-en> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/IEITYuan__Yuan-embedding-2.0-en> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/IEITYuan__Yuan-embedding-2.0-en/b2fd15da3bcae3473c8529593825c15068f09fce>

### 32. geevec-embeddings-1.0-lite (not servable)  (`geevec-ai/geevec-embeddings-1.0-lite`)
- **Tier:** not llama.cpp-servable. **Licence:** Apache-2.0. **Params:** 366M, non-emb 211M = 1.86x; native dim 4096; context 40960 tokens - HF config.
- **Prefixes / pooling:** query `'instruction-based (custom loader)'`; document `'-'`; pooling -.
- **Matryoshka (MRL):** dims none. -
- **Quantisation claims:** -
- **MTEB(eng,v2) retrieval:** 62.23 - leaderboard (10/10 tasks) - source dir <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/geevec-ai__geevec-embeddings-1.0-lite/e62d287818e2da9d647c77d6eb2e13c50e50f9eb>; per task: ArguAna 82.71, CQADupstackGamingRetrieval 62.82, CQADupstackUnixRetrieval 47.93, ClimateFEVERHardNegatives 43.71, FEVERHardNegatives 92.31, FiQA2018 54.25, HotpotQAHardNegatives 76.81, SCIDOCS 23.46, TRECCOVID 80.82, Touche2020Retrieval.v3 57.44
- **Wikipedia-based tasks:** v1: not in results repo; v2 hard-negatives [L]: HotpotQAHardNegatives 76.81, FEVERHardNegatives 92.31, ClimateFEVERHardNegatives 43.71; MMTEB English subsets [L]: WikipediaRetrievalMultilingual[en] 94.91, MIRACLRetrievalHardNegatives[en] 54.49, MLQARetrieval[eng-eng] 73.22; Wiki5 68.11, HN3 70.94. Sources: leaderboard dir above; v1 [S] values (if any) are the model-card metadata imported into the results repo (`external` revision of the same directory).
- **MMTEB retrieval:** computed 70.55 [L]
- **llama.cpp:** no - arch qwen3_pseudo_moe (custom code). Evidence: HF config model_type qwen3_pseudo_moe, custom modeling code; no GGUF found.
- Note: MTEB(eng,v2) retrieval 62.23 (10/10) at 366M parameters and 4096-d output; custom architecture, no GGUF, 16 KB per vector.
- Pitfall: 4096-d vectors; custom code.
- Sources: <https://huggingface.co/geevec-ai/geevec-embeddings-1.0-lite> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/geevec-ai__geevec-embeddings-1.0-lite> | <https://github.com/embeddings-benchmark/results/tree/ecd91ce5f259ee6a3efb5668afdcb1d208eded9d/results/geevec-ai__geevec-embeddings-1.0-lite/e62d287818e2da9d647c77d6eb2e13c50e50f9eb>

## Appendix A - leaderboard scan: open-weight models <= 1.8B parameters with all 10 MTEB(eng,v2) retrieval tasks (top 30 of 148)

Computed from the results repo [L]; sorted by retrieval average; `*` = some of the 10 tasks are model-card values imported into the results repo (self-reported). Flags are mine.

| rank | model | retrieval | params | dim | max tokens | licence | released | flag |
|---|---|---:|---:|---:|---:|---|---|---|
| 1 | `IEITYuan/Yuan-embedding-2.0-en` | 70.69 | 596M | 1024 | 2048 | apache-2.0 | 2025-11-27 | implausible (SCIDOCS 59.9, TRECCOVID 98.3) - ignore |
| 2 | `infgrad/Jasper-Token-Compression-600M` | 66.19 | 596M | 2048 | 32768 | mit | 2025-11-14 | custom architecture, no GGUF |
| 3 | `geevec-ai/geevec-embeddings-1.0-lite` | 62.23 | 366M | 4096 | 32768.0 | apache-2.0 | 2026-04-02 | custom architecture, 4096-d, no GGUF |
| 4 | `Qwen/Qwen3-Embedding-0.6B` | 61.83 | 596M | 1024 | 32768.0 | apache-2.0 | 2025-06-05 | shortlist #4 |
| 5 | `infly/inf-retriever-v1-1.5b` | 60.83 | 1543M | 1536 | 32768.0 | apache-2.0 | 2025-02-08 | 1.5B |
| 6 | `jinaai/jina-embeddings-v5-omni-small` | 60.07 | 1626M | 1024 | 32768.0 | cc-by-nc-4.0 | 2026-04-01 |  |
| 7 | `jinaai/jina-embeddings-v5-text-small` | 60.07 | 596M | 1024 | 32768.0 | cc-by-nc-4.0 | 2026-01-22 | NC licence; honourable mention |
| 8 | `Snowflake/snowflake-arctic-embed-l` | 59.04* | 335M | 1024 | 512.0 | apache-2.0 | 2024-04-12 |  |
| 9 | `jinaai/jina-embeddings-v5-omni-nano` | 58.80 | 986M | 768 | 8192.0 | cc-by-nc-4.0 | 2026-04-01 |  |
| 10 | `jinaai/jina-embeddings-v5-text-nano` | 58.80 | 212M | 768 | 8192.0 | cc-by-nc-4.0 | 2026-02-17 | shortlist #1 |
| 11 | `Snowflake/snowflake-arctic-embed-l-v2.0` | 58.56 | 568M | 1024 | 8192.0 | apache-2.0 | 2024-12-04 | shortlist #2 |
| 12 | `KaLM-Embedding/KaLM-embedding-multilingual-mini-instruct-v2.5` | 58.46 | 494M | 896 | 512.0 | apache-2.0 | 2025-09-30 | 512 eval ctx |
| 13 | `Snowflake/snowflake-arctic-embed-m-v2.0` | 58.41 | 305M | 768 | 8192.0 | apache-2.0 | 2024-12-04 | no llama.cpp support |
| 14 | `Snowflake/snowflake-arctic-embed-m-v1.5` | 58.05* | 109M | 768 | 512.0 | apache-2.0 | 2024-07-08 |  |
| 15 | `codefuse-ai/F2LLM-1.7B` | 57.83 | 1721M | 2560 | 8192.0 | apache-2.0 | 2025-09-18 |  |
| 16 | `Snowflake/snowflake-arctic-embed-m` | 57.53* | 109M | 768 | 512.0 | apache-2.0 | 2024-04-12 |  |
| 17 | `Snowflake/snowflake-arctic-embed-m-long` | 57.02* | 137M | 768 | 2048.0 | apache-2.0 | 2024-04-12 |  |
| 18 | `codefuse-ai/F2LLM-v2-1.7B` | 56.65 | 1721M | 2048 | 40960.0 | apache-2.0 | 2026-03-09 |  |
| 19 | `ibm-granite/granite-embedding-english-r2` | 56.43 | 149M | 768 | 8192.0 | apache-2.0 | 2025-08-15 | shortlist #5 |
| 20 | `ai-sage/Giga-Embeddings-instruct-480M-0826` | 56.30 | 484M | 1024 | 8192 | mit | 2026-08-10 | custom arch (qwen3_bidirec) |
| 21 | `WhereIsAI/UAE-Large-V1` | 55.91* | 335M | 1024 | 512.0 | mit | 2023-12-04 |  |
| 22 | `codefuse-ai/F2LLM-0.6B` | 55.70 | 596M | 1024 | 8192.0 | apache-2.0 | 2025-09-18 |  |
| 23 | `google/embeddinggemma-300m` | 55.69 | 308M | 768 | 2048.0 | gemma | 2025-09-04 | shortlist #3 |
| 24 | `ibm-granite/granite-embedding-125m-english` | 55.65 | 125M | 768 | 512.0 | apache-2.0 | 2024-12-18 |  |
| 25 | `BAAI/bge-large-en-v1.5` | 55.44* | 335M | 1024 | 512.0 | mit | 2023-09-12 |  |
| 26 | `mixedbread-ai/mxbai-embed-large-v1` | 55.40 | 335M | 1024 | 512.0 | apache-2.0 | 2024-03-07 | 512 ctx |
| 27 | `Tarka-AIR/Tarka-Embedding-350M-V1` | 55.15 | 354M | 1024 | 128000.0 | None | 2025-11-11 | licence unspecified |
| 28 | `Snowflake/snowflake-arctic-embed-s` | 54.85* | 32M | 384 | 512.0 | apache-2.0 | 2024-04-12 |  |
| 29 | `nomic-ai/nomic-embed-text-v2-moe` | 54.81 | 475M | 768 | 512.0 | apache-2.0 | 2025-02-07 | 512 ctx |
| 30 | `BAAI/bge-base-en-v1.5` | 54.75* | 109M | 768 | 512.0 | mit | 2023-09-11 |  |

(nomic-ai/nomic-embed-text-v1.5 is not in the full-coverage scan because FiQA2018 is missing from its leaderboard revision; mixed value 47.97 shown in the main table.)

## Appendix B - oversized references (not for a <= 1.5 GB budget)

| model | params | dim | licence | MTEB(eng,v2) retrieval | MMTEB retrieval |
|---|---:|---:|---|---|---|
| Qwen3-Embedding-8B | 7.57B | 4096 | apache-2.0 | 69.44 [L] | 70.74 [L] |
| llama-embed-nemotron-8b | 7.5B | 4096 | https://huggingface.co/nvidia/llama-embed-nemotron-8b/blob/main/LICENSE | partial 64.01 (3/10 tasks) [L] | 68.44 [L] |
| Nemotron-3-Embed-8B | 7.95B | 4096 | https://huggingface.co/nvidia/Nemotron-3-Embed-8B-BF16/blob/main/LICENSE | n/a [L] | partial 80.25 (4/18) [L] |
| KaLM-Embedding-Gemma3-12B-2511 | 11.77B | 3840 | tencent-kalm-embedding-community (custom, HF tag "other") | partial 59.63 (3/10 tasks) [L] | 75.47 [L] |
| harrier-oss-v1-27b | 27.01B | 5376 | mit | partial 61.85 (3/10 tasks) [L] | 78.11 [L] |
| pplx-embed-v1-4b | 4.02B | 2560 | mit | partial 59.82 (3/10 tasks) [L] | 69.35 [L] |
| Octen-Embedding-8B | 7.57B | 4096 | apache-2.0 | partial 67.12 (3/10 tasks) [L] | partial 70.5 (16/18) [L] |
| Octen-Embedding-4B | 4.02B | 2560 | apache-2.0 | n/a [L] | partial 83.91 (4/18) [L] |

Also seen but not evaluated further: **pplx-embed-v2-context-9b-preview** (released 2026-09-25..30, 8.4B parameters, MIT, contextual chunk embeddings, <https://huggingface.co/perplexity-ai/pplx-embed-v2-context-9b-preview>), **topk-embed-v1-xsmall/small** (0.85B/2.2B, Apache-2.0, 2026-09-23), **Desearch-Embedding-4B/8B** (2026-09-26/27), **Qwen3-VL-Embedding-2B/8B** (multimodal), **Nemotron-3-Embed-8B**, **nvidia/llama-nemotron-embed-1b-v2** (1.24B parameters, 8192 tokens, MRL, NVIDIA Open Model License, <https://huggingface.co/nvidia/llama-nemotron-embed-1b-v2>; ~8.6x nomic compute, no English MTEB rows), **BidirLM-270M/0.6B/1B/1.7B-Embedding** (Apache-2.0, custom `bidirlm` architecture, only 3/10 English retrieval tasks on the leaderboard), **Giga-Embeddings-instruct-480M-0826** (MIT, custom Qwen3-bidirectional code), **mdbr-leaf-ir/mt** (23M MongoDB models), **LiquidAI LFM2.5-ColBERT-350M** (late interaction). No "nomic-embed-text-v3" exists (search returned nothing; HF org listing shows v1/v1.5/v2-moe only) and no EmbeddingGemma successor or Qwen3-Embedding successor was found (Qwen3-VL-Embedding is the multimodal extension).

## Appendix C - Hugging Face API scan (trending / most downloaded / most liked embedding models, created since 2025-07-01, top 25 by 30-day downloads)

From `https://huggingface.co/api/models?pipeline_tag={feature-extraction,sentence-similarity}&sort={trendingScore,downloads,likes}&limit=100` (428 distinct models, scan of 2026-10-01; the file `raw/hf_trending_scan.json` has all). Many are multimodal/vision/audio or fine-tunes; the text-embedding ones are the models in this report plus: topk-embed-v1, Desearch-Embedding, borealis-embed, bekko-embedding, Giga-Embeddings, tencent WeMM-Embedding (multimodal), Qwen3-VL-Embedding (multimodal).

| model | created | downloads (30d) | likes |
|---|---|---:|---:|
| `ibm-granite/granite-embedding-small-english-r2` | 2025-07-17 | 5,433,363 | 84 |
| `google/embeddinggemma-300m` | 2025-07-17 | 3,671,068 | 1968 |
| `Qwen/Qwen3-VL-Embedding-8B` | 2026-01-07 | 1,329,426 | 485 |
| `Qwen/Qwen3-VL-Embedding-2B` | 2026-01-07 | 1,161,810 | 462 |
| `Octen/Octen-Embedding-8B` | 2025-12-23 | 1,104,102 | 193 |
| `gabor-hosu/e5-mistral-7b-instruct-bnb-4bit` | 2026-01-09 | 1,024,874 | 1 |
| `jinaai/jina-embeddings-v5-omni-small` | 2026-04-01 | 586,893 | 156 |
| `onnx-community/embeddinggemma-300m-ONNX` | 2025-08-22 | 479,959 | 74 |
| `nvidia/Nemotron-3-Embed-1B-BF16` | 2026-07-14 | 423,223 | 158 |
| `nvidia/llama-nemotron-embed-1b-v2` | 2025-10-16 | 400,054 | 64 |
| `voyageai/voyage-4-nano` | 2026-01-06 | 338,208 | 145 |
| `jinaai/jina-embeddings-v5-text-small` | 2026-01-22 | 312,717 | 201 |
| `microsoft/harrier-oss-v1-0.6b` | 2026-03-30 | 302,221 | 314 |
| `RamManavalan/Qwen3-VL-Embedding-8B-FP8` | 2026-01-22 | 278,096 | 5 |
| `unsloth/bge-small-en-v1.5-GGUF` | 2026-06-09 | 250,489 | 5 |
| `microsoft/harrier-oss-v1-270m` | 2026-03-30 | 237,538 | 201 |
| `unsloth/bge-small-en-v1.5` | 2026-06-01 | 189,084 | 2 |
| `ibm-granite/granite-embedding-311m-multilingual-r2` | 2026-04-20 | 179,799 | 136 |
| `ai-sage/Giga-Embeddings-instruct-480M-0826` | 2026-08-10 | 160,131 | 28 |
| `OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano` | 2026-04-02 | 158,015 | 29 |
| `jinaai/jina-embeddings-v5-text-nano` | 2026-01-22 | 150,709 | 102 |
| `NeuML/colbert-bert-tiny` | 2025-08-16 | 145,406 | 2 |
| `eustlb/higgs-audio-v2-tokenizer` | 2026-02-19 | 129,673 | 1 |
| `jinaai/jina-embeddings-v5-text-small-text-matching` | 2026-02-10 | 116,855 | 13 |
| `nvidia/Nemotron-3-Embed-8B-BF16` | 2026-07-14 | 109,377 | 104 |

## Appendix D - serving checklist for llama-server on a P40 (pitfalls found)

1. **Physical batch must cover the longest chunk.** `-ub` defaults to 512 (llama-server README); non-causal embedding models reject longer inputs ("input is too large to process. increase the physical batch size", llama.cpp #11105). NOMAD chunks are up to 3,000 characters (~750 tokens, inputs capped at 4,000 chars) -> use `-ub 2048` or more (Qwen card uses `-ub 8192`).
2. **`-c` is shared across `-np` slots** (unified KV buffer by default) - give each slot at least one chunk of context; EmbeddingGemma crashed with a non-power-of-2 `--parallel` (#18532, fixed, reported again 2026-08-17). Batched requests with `-np>1` gave slightly different vectors for the jina-v5 (nano/small) GGUFs (#26282, closed by the stale bot without a fix) -> run a determinism check (same text alone vs inside a batch) before bulk indexing.
3. **Pooling is a per-model flag.** Check with `--pooling` or the GGUF header (`<arch>.pooling_type`: 1 mean, 2 CLS, 3 last): nomic mean, EmbeddingGemma mean, bge-m3/arctic CLS, Qwen3/jina-v5/harrier last. Decoder-only embedders need the EOS token: the official Qwen3 GGUF sets `add_eos_token=true`; self-converted ones need `<|endoftext|>` appended by hand (#14234).
4. **Prefixes/instructions are not applied by the server** - NOMAD must send them (table in `models.json`; upstream PR #1367 shows a per-model table). Qwen3/Harrier/KaLM/F2LLM want an `Instruct: ...\nQuery: ` prefix on queries only.
5. **`dimensions` (MRL) is ignored by the llama-server `/v1/embeddings` endpoint** (open PR #24898 / issue #25210). Truncate client-side and re-normalise (nomic v1.5 additionally needs layer-norm before truncation). Only trained dims are valid (Jina: a 131-d cut is worse than 128-d).
6. **P40 specifics.** Pascal has no useful FP16 (1/64 of FP32 rate) and no tensor cores; use Q8_0/Q4 GGUFs (integer dp4a kernels, INT8 47 TOPS per the NVIDIA datasheet <https://images.nvidia.com/content/pdf/tesla/184427-Tesla-P40-Datasheet-NV-Final-Letter-Web.pdf>) or F32; EmbeddingGemma must not run in FP16. Prefer Q8_0 over F16 [inference].
7. **Score calibration.** NOMAD's cosine floors (`score_threshold` 0.3, `RAG_MIN_FINAL_SCORE` 0.62) were tuned on nomic; PR #1367 found other models need 0.30-0.44.
8. **llama.cpp architecture support (master, 2026-10-01, `src/llama-arch.cpp`):** bert, modern-bert, nomic-bert, nomic-bert-moe, neo-bert, jina-bert-v2/v3, eurobert, qwen2/3, gemma3, gemma-embedding, lfm2, mistral3, llama-embed... **not** gte/NewModel (arctic-embed-m-v2.0, gte-multilingual-base) and not custom-code architectures (geevec, Jasper, Giga).
9. **Memory for the vectors (not the model):** 3,072 B per 768-d float32 vector, 4,096 B at 1024-d, 8,192 B at 2048-d; MRL truncation (e.g. 256-d = 1,024 B) is the lever if the index must shrink. Qdrant scalar int8 quantisation would cut RAM 4x but NOMAD does not expose it (see `nomad_upstream.md`).

## Reproduce

```bash
git clone --depth 1 --filter=blob:none --no-checkout https://github.com/embeddings-benchmark/results.git results-repo && cd results-repo
git checkout ecd91ce5f259ee6a3efb5668afdcb1d208eded9d   # snapshot used; then: git sparse-checkout init --no-cone; git sparse-checkout set --stdin < ../sparse_patterns.txt; git checkout
python3 mteb_scores.py && python3 build_models.py && python3 render_models_md.py   # scripts + inputs are in raw/
```
`raw/results-repo` (a 215 MB sparse checkout) was deleted after the numbers were extracted; the extracted per-model scores are in `raw/mteb_scores_all.json`, Hugging Face API dumps in `raw/hf/`, GitHub issue dumps in `raw/gh/`.
