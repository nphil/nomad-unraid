# NOMAD upstream status for indexing speed, embedding model and Qdrant (checked 2026-10-01)

Repo: <https://github.com/Crosstalk-Solutions/project-nomad>. Latest release **v1.35.0 (2026-09-29)**; there is **no v1.36 pre-release**; `dev` is only 3 commits ahead of v1.35.0 and none of them touches ingestion (commit list checked with `gh api compare/v1.35.0...dev`). I listed all 1,269 issues/PRs (589 issues + 680 PRs, `gh api`), keyword-filtered their titles/bodies (313 hits), read the ~30 relevant ones in full with comments, read the v1.34.1 / v1.35.0-rc.1 / rc.2 / v1.35.0 release notes, scanned the 128 Discussions titles and listed all 75 open items.

## Answer first (plain language)

- **Yes, we must patch NOMAD ourselves for speed.** The big slowdown (every 50-article job re-reads the Wikipedia file from the start, issue #1185) is **still open and not in v1.35.0**. A fix exists only as an *unmerged* pull request (#1386, "review required", merge state "DIRTY").
- **Already fixed and shipped in v1.35.0** (so Nitin's box has them): duplicate chains from "stalled job" recovery (#1269 via #1270, but only partly), jobs stopping after one sparse batch (#1240 via #1242), vectors left behind for deleted ZIMs (#1170 via #1227). Fixed earlier in v1.34.0: re-creating Qdrant payload indexes on every document (#1129 via #1135).
- **Choosing another embedding model is not possible in stock NOMAD.** An opt-in setting exists only as an open, unmerged PR (#1367, 5 models: nomic default, bge-m3, qwen3-embedding:0.6b, snowflake-arctic-embed2, embeddinggemma). The model name, 768 width, prefixes and the relevance cut-off are hard-coded for nomic.
- **Nothing upstream about Qdrant memory/quantization/on_disk/HNSW or about batching Qdrant upserts or sending embeddings in parallel.** The only related open reports are #1328 (single-threaded ingestion) and #1268 (remote Ollama GPU capacity); both are acknowledged but unfixed.

## Index of relevant issues / PRs

| # | what | state | in v1.35.0? | relevance to us |
|---|---|---|---|---|
| [#1185](https://github.com/Crosstalk-Solutions/project-nomad/issues/1185) | ZIM ingestion is O(n^2): each batch re-scans archive from entry 0 | **open** (bug) | no | main speed problem for Wikipedia |
| [#1386](https://github.com/Crosstalk-Solutions/project-nomad/pull/1386) | PR "seek ZIM batches instead of rescanning" (closes #1185) | **open**, review required, DIRTY | no | candidate patch to cherry-pick/rebase |
| [#1212](https://github.com/Crosstalk-Solutions/project-nomad/issues/1212) | "extraction cost scales with batchOffset" (user: ZIM_BATCH_SIZE 50->5000 gave 5.5 -> 50 entries/s) | closed as duplicate of #1185 | n/a | data points + workaround ideas |
| [#1269](https://github.com/Crosstalk-Solutions/project-nomad/issues/1269) / [#1270](https://github.com/Crosstalk-Solutions/project-nomad/pull/1270) | stalled-job recovery forks the batch chain -> duplicate vectors | closed, merged 2026-09-02 | **yes** | partial fix only (see below) |
| [#1129](https://github.com/Crosstalk-Solutions/project-nomad/issues/1129) / [#1135](https://github.com/Crosstalk-Solutions/project-nomad/pull/1135) | `_ensureCollection()` re-created payload indexes on every document (~45% of Qdrant time) | closed, merged 2026-07-22 | yes (since v1.34.0) | per-job overhead removed |
| [#1240](https://github.com/Crosstalk-Solutions/project-nomad/issues/1240) / [#1242](https://github.com/Crosstalk-Solutions/project-nomad/pull/1242) | ZIM ingestion silently stops after first sparse batch | closed, merged 2026-09-02 | yes | correctness |
| [#1069](https://github.com/Crosstalk-Solutions/project-nomad/issues/1069) | embedding stops at identical point count (same root cause as #1240) | closed (dup) | yes | - |
| [#1170](https://github.com/Crosstalk-Solutions/project-nomad/issues/1170) / [#1227](https://github.com/Crosstalk-Solutions/project-nomad/pull/1227) | Qdrant keeps vectors of deleted/replaced ZIMs | closed, merged 2026-09-23 | yes (rc.2) | orphan sweep now exists; see #1378/#1393 for its bugs |
| [#1328](https://github.com/Crosstalk-Solutions/project-nomad/issues/1328) | single-threaded ingestion, GPU idle, UI lag | **open** | no | maintainers: real, rescan fix first |
| [#1268](https://github.com/Crosstalk-Solutions/project-nomad/issues/1268) | use available GPU capacity on remote Ollama (nomic capped at 2048 ctx) | **open** | no | - |
| [#1366](https://github.com/Crosstalk-Solutions/project-nomad/issues/1366) / [#1367](https://github.com/Crosstalk-Solutions/project-nomad/pull/1367) | configurable KB embedding model (5 models) | **open** (PR not merged) | no | exactly what we need to switch models |
| [#947](https://github.com/Crosstalk-Solutions/project-nomad/issues/947) | hybrid retrieval (dense + lexical), faster KB ops | **open**, roadmap item | no | FTS5 + RRF plan agreed by maintainer |
| [#1182](https://github.com/Crosstalk-Solutions/project-nomad/issues/1182) | keyword search over KB docs without AI | open | no | - |
| [#1015](https://github.com/Crosstalk-Solutions/project-nomad/issues/1015) | "Wikipedia indexing for over 3 weeks" (17-22%) | closed 2026-07-13 | n/a | maintainer advice: use a smaller ZIM |
| [#883](https://github.com/Crosstalk-Solutions/project-nomad/issues/883) / #891 | RFC: KB ingestion UX; ratio registry for disk/time estimates | closed | yes | heuristic seeds (see below) |
| [#873](https://github.com/Crosstalk-Solutions/project-nomad/pull/873) | pace continuation batches 1 s when embedding is CPU-only | merged (v1.32.0) | yes | not relevant when GPU embedding |
| [#1279](https://github.com/Crosstalk-Solutions/project-nomad/issues/1279) / #1284 | `_embedWithFallback()` always tried Ollama `/api/embed` first even on non-Ollama backends | closed | yes | relevant for llama-swap/OpenAI-compatible backend |

## 1. The O(n^2) re-scan (#1185) - still open

- Mechanism (reporter @PairsOfTwoSocks, 2026-08-01): every continuation job opens the archive and walks `iterByPath()` from entry 0, skipping `startOffset` articles, so batch k costs O(k). Their numbers on `wikipedia_en_all_maxi_2026-02.zim`: extraction 1.4 s per 50 articles at offsets 0-100k -> 11.2 s at 1.1-1.2M while embedding stayed flat (14-16 s); 13.7 days to reach 5.83% of the (inflated) corpus.
- Maintainer reproduction (comment 2026-08-26, @chriscrosstalk): per-entry skip cost is flat (1.82-1.89 us); full pass 2.31 us/raw entry on NVMe; projected **~61 days of pure seeking for a complete Wikipedia ingest** even on NVMe. (An earlier maintainer comment in #1212 said "~4 hours"; the later, measured number supersedes it.)
- **Real size of the corpus (same comment):** raw entries 27,199,904 = redirects 10,556,428 + non-HTML items 8,217,690 + `isArticleEntry()` 8,425,786; `archive.articleCount` 18,982,214 = 8,425,786 + 10,556,428. NOMAD's progress bar uses `articleCount`, so a completed Wikipedia run would stop at ~44.4%. (I confirmed the 8,425,786 figure independently from the ZIM's own `M/Counter` metadata; see `wikipedia_variants.md`.)
- PR #1386 ("seek ZIM batches", @aaronvt, opened 2026-09-27, last update 2026-09-30): each batch counts every dirent it finishes and passes `resumeAtDirent` to the next job, which seeks with `iterByPath().offset(resumeAtDirent, range.size)`; the first batch and old-format jobs still scan once. Reported test on the same 18,982,214-entry file: "Seeking to dirent offset 13416" at article offset 5600, extraction under 0.1 s. Status: OPEN, review decision REVIEW_REQUIRED, merge state DIRTY (needs rebase). The PR shows 100 changed files because of branch drift against `dev` (merge state DIRTY); the ingestion change itself is about +36 lines in `admin/app/jobs/embed_file_job.ts` and +39/-6 in `admin/app/services/zim_extraction_service.ts` (per the PR file list), so it must be rebased before use.
- Note (not tracked upstream; figure from the lead's briefing): each job still **re-opens the archive** (`new Archive(...)`); our median open time was 99 s on the 124 GB file. Nobody upstream reports this, and #1386 does not change it.

## 2. Duplicate chains (#1269) - mitigated, not eliminated

- Cause: `file-embeddings` used BullMQ's default 5-minute lock and `maxStalledCount` 1, so a healthy job blocked by a long ZIM batch was "recovered", producing two parallel chains over the same file (Redis evidence in #1212/#1269; one user reported ~10 M duplicate points of 24 M).
- Shipped fix (PR #1270, merged 2026-09-02, in v1.35.0): `file-embeddings` gets a **30-minute lock and `maxStalledCount: 0`** (a stall now fails the job instead of silently re-queueing it).
- **Explicitly NOT fixed:** point IDs are still random UUIDs (`randomUUID()` per write), so any re-run of an offset adds new points instead of overwriting. PR text: "Deterministic Qdrant point ids derived from source, offset, and chunk index would turn a duplicated write into an idempotent overwrite. That is a larger change ... it is not in this PR." Existing duplicates are not cleaned up. -> We should check our collection for duplicates (chunks per article ratio; the reporter used "chunks / batchOffset should be ~2-3 on Wikipedia"; 8,020,083 chunks at offset 3,480,000 = 2.30).

## 3. Per-job overhead (`_ensureCollection`, setPayload backfill)

- #1129/#1135: `_ensureCollection()` issued `GET /collections` plus payload-index creation on every document (the logged cycle was 4-5 requests; ~21 ms of every ~46 ms document cycle). Fixed in v1.34.0-rc.2 by memoising in `RagService.ensuredCollections`; because each `EmbedFileJob` constructs a new `RagService`, the check still runs **once per 50-article job**, which the PR calls negligible.
- No upstream issue mentions a `setPayload` backfill cost; the only payload-write items are the per-source `active` toggle (#1286/#1395) and collection assignment (#1063/#1200). Not a known bottleneck upstream. (The log in #1129 shows `PUT /points?wait=true` taking ~5.6 ms on the reporter's machine; our measured average upsert is 426 ms on the spinning array - this matters because NOMAD does one upsert per section.)

## 4. Embedding model configurability (#1366 / PR #1367, both open)

- Today: hard-coded `nomic-embed-text:v1.5`, `EMBEDDING_DIMENSION = 768`, prefixes `search_document: ` / `search_query: `, relevance floor `RAG_MIN_FINAL_SCORE = 0.62` (calibrated on nomic's score distribution). Changing only the model name breaks the collection width.
- PR #1367 (@mmoyles87, 2026-09-24, opt-in `rag.embeddingModel` KV setting, unset = unchanged behaviour, switching via existing Reset & Rebuild, a mismatch makes jobs fail once with "run Reset & Rebuild"). Its `EMBEDDING_MODELS` table (the prefixes are the useful part for us):

| Ollama model | width | doc prefix | query prefix | min final score |
|---|---:|---|---|---:|
| nomic-embed-text:v1.5 (default) | 768 | `search_document: ` | `search_query: ` | 0.62 |
| bge-m3 | 1024 | none | none | 0.44 |
| qwen3-embedding:0.6b | 1024 | none | `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` | 0.35 |
| snowflake-arctic-embed2 | 1024 | none | `query: ` | 0.30 |
| embeddinggemma | 768 | `title: none \| text: ` | `task: search result \| query: ` | 0.30 |

- The PR's own measurement (NOMAD eval corpus: 99 golden questions over **28 documents**, so tiny; one question = 1.0 point of recall): English recall@5 nomic 0.991, bge-m3 0.995, qwen3-0.6b 0.991, arctic-embed2 0.933, embeddinggemma 0.973; cross-language (el/ru/ro machine translations of the same goldens) nomic **0.265**, bge-m3 0.990, qwen3 0.876, arctic 0.877, gemma 0.868. Off-topic leak at each model's floor: nomic 67%, bge-m3 89%, qwen3 39%, arctic 11%, gemma 11%. English quality was a tie on that corpus - it is not evidence for or against a model on 19 M Wikipedia chunks. Not tested on a real ZIM ("I haven't ingested a real ZIM with them").
- Maintainer reaction: none yet (0 comments on both). Related open item #1268 notes nomic being capped at 2048 context on remote Ollama.

## 5. Batching / parallelism

- Hard-coded `ZIM_BATCH_SIZE = 50` (constant, **not** an environment variable; "setting ZIM_BATCH_SIZE in compose.yml has no effect", #1212). A user patched it to 500/2000/5000 and got 3-9x throughput but also duplicate chains (before #1270's lock change).
- Suggestions from #1212 (unimplemented): keep the archive open across batches; overlap extraction and embedding (GPU 27% busy); concurrent `/api/embed` calls (8 concurrent 0.088 s vs 0.319 s sequential = 3.6x on short inputs); make the batch size configurable.
- #1328 (open): maintainers (2026-09-22): the pinned Node core is #1185; extraction/chunking run in the admin's single Node process that also serves the UI ("a long ingest starves the UI ... a real architecture issue"); "Sequential dispatch to Ollama is also real, but the rescan fix comes first". Memory growth of `nomad_admin` (15 GiB RSS after ~5 days) was also reported in #1212.
- `file-embeddings` worker concurrency is 2 (from #1269/#1270 text).
- Embedding requests are sent in batches of 8 and each section is one Qdrant upsert (from the v1.35.0 source read by the lead; no upstream issue proposes cross-section upsert batching).
- v1.35.0 fixed the non-Ollama backend probe (#1284/#1279): NOMAD no longer tries Ollama's `/api/embed` first on an OpenAI-compatible backend, which matters for the llama-swap setup.

## 6. Qdrant memory / quantization / on_disk / HNSW

- Searched issues/PRs for `quantization`, `on_disk`, `hnsw`, `optimizer`: **no upstream issue or PR configures them.** NOMAD creates the collection with vector size 768 / Cosine and default optimizer settings (per the lead's measurement of our instance: HNSW m=16 ef_construct=100, on_disk=false, no quantization).
- One user (#1212, Qdrant v1.16) wrote "scalar int8 quantization enabled" - done by hand outside NOMAD; there is no NOMAD setting for it.
- #124 ("Stretch Goal - GPU Support for Qdrant") was closed on 2026-05-05 by shipping AMD ROCm acceleration for **Ollama** (PR #804, v1.32.0-rc.1) - no Qdrant GPU indexing was implemented. Qdrant restart policy / start button exist (#673/#700) and telemetry is disabled by default (#742/#747/#748).
- Upstream's own disk/time heuristics (RFC #883, code `admin/app/utils/kb_ratio_lookup.ts`, migration `1776100000001_create_kb_ratio_registry_table.ts`): `BYTES_PER_CHUNK_ON_DISK = 8,000` (3,072 B vector + ~3,000 B text + ~2,000 B payload/indexes) and seeded **270 chunks per MB of ZIM** for `wikipedia_en_*` ("Heuristic seed", not measured on full Wikipedia). For the 123,980,647,016-byte file that would be ~33 M chunks / ~263 GB. [inference] The measured ratio from #1269 (2.30 chunks per article) times 8,425,786 real pages is ~19.4 M chunks, i.e. upstream's seed over-estimates by ~1.7x for this file.

## 7. Other upstream context

- #1015 (closed): users report full-Wikipedia indexing "3+ weeks, 17-22%" on RTX 3060 class GPUs; maintainer advice (2026-06-24): "a multi-day job, not hours ... a smaller, more focused ZIM will index far faster". #1185/#1328 report 5-6% after 2 weeks.
- #947 (open, roadmap): hybrid dense+lexical retrieval; community plan (@tekstrand, 2026-06-27, maintainer approved 2026-07-11): SQLite FTS5 lexical lane + RRF, opt-in `ai.hybridRetrieval`; follow-up "a Kiwix lexical lane for un-embedded ZIM content (offline Wikipedia), which we can't realistically embed wholesale". [inference] Upstream itself regards full-Wikipedia embedding as impractical.
- #1341/#1365: the relevance floor (0.62) does not reject coherent off-topic queries; opt-in LLM relevance check shipped in v1.35.0. Any change of embedding model needs a recalibrated floor (PR #1367 shows how).
- v1.35.0 also changed: `ZIM_BATCH_SIZE` unchanged; `file-embeddings` stall options (#1270); sparse-batch continuation (#1242); orphan sweep (#1227, #1378/#1393 fixed its "purge everything when the zim dir looks empty" bug).

## What this means for a patch plan (inference)

1. Cherry-pick / rebase #1386 (seek by dirent) - removes the quadratic term; keep the archive open across jobs if possible (not in #1386).
2. Keep #1270's lock settings; add deterministic point IDs (e.g. UUIDv5 of `document_id:chunk_index`) so a retry cannot duplicate; clean existing duplicates first.
3. For a model switch, reuse the #1367 structure (model table with width/prefixes/floor) rather than inventing another convention.
4. Make batch size a setting (e.g. 500-2000) only together with #1270's 30-min lock.

## Sources

- Issues/PRs linked inline; release notes: <https://github.com/Crosstalk-Solutions/project-nomad/releases/tag/v1.35.0>, [rc.1](https://github.com/Crosstalk-Solutions/project-nomad/releases/tag/v1.35.0-rc.1), [rc.2](https://github.com/Crosstalk-Solutions/project-nomad/releases/tag/v1.35.0-rc.2), [v1.34.1](https://github.com/Crosstalk-Solutions/project-nomad/releases/tag/v1.34.1).
- Raw API dumps: `raw/nomad_issues_all_merged.json`, `raw/gh/*.json` (issue bodies + comments), `raw/nomad_releases_merged.json`.
- Quote of the #1185 maintainer comment: <https://github.com/Crosstalk-Solutions/project-nomad/issues/1185#issuecomment-5427962842>; #1212 workaround/suggestions: <https://github.com/Crosstalk-Solutions/project-nomad/issues/1212>.
