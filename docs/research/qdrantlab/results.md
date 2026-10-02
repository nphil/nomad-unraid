# qdrantlab - what a NOMAD-style Qdrant collection costs (disk, RAM, settings), 4.1M -> 40M points

Qdrant **v1.16.3** (same as production), throw-away containers only, production never touched.
**Scope was cut on instruction** (host overloaded, one-heavy-job lock): the planned 100k/300k/1M runs and the real-vector fidelity runs were
**NOT executed**. This report = (a) measurements on a 10,000-point throw-away collection, (b) live production telemetry snapshot,
(c) Qdrant v1.16.3 source code and documentation. Every number is tagged:

| tag | meaning |
|---|---|
| **[smoke]** | measured by me on Qdrant v1.16.3, N=10,000 synthetic vectors, host load 40-165 (all timings PROVISIONAL; sizes are exact but tiny-N overheads dominate) |
| **[prod]** | measured on the live production collection (telemetry snapshot `state/qdrant_telemetry.json`, `state/qdrant_collection.json`; host `ls`/`du`) |
| **[src]** | read from Qdrant v1.16.3 source code / its OpenAPI schema (links in section 6) |
| **[docs]** | Qdrant documentation formula (links in section 6) |
| **[infer]** | my inference, not measured |

## 1. Answers first

1. **Disk per chunk: about 5.4 KB with NOMAD defaults** (3,072 B vector + 2,171 B stored payload + ~91 B payload indexes + ~35 B id tracker + ~54 B HNSW graph).
   Check against production: formula 22.3 GB at 4.1M vs ~21 GB of real data observed. Int8 quantization adds 768 B/chunk (+14%).
   At 21M chunks that is **~114 GB (defaults) / ~130 GB (int8)** - fits the NVMe pool (~285 GB available there), not comfortable at 40M (217-248 GB).
2. **RAM is the real constraint, and the vectors are only part of it.** Everything-in-RAM (NOMAD default) needs ~3.3 KB/chunk resident:
   3.0M chunks fill the host's ~10 GB of free RAM. Int8 in RAM + originals on NVMe needs ~1.0 KB/chunk (10M chunks per 10 GB).
   With vectors/graph/quantized copy all on NVMe only ~52 B/chunk is mandatory (page cache then decides speed).
3. **Production's heap is about 8x what the formulas explain**: 5.9 GB live heap at 4.11M points = 1.44 KB/pt, formulas explain ~0.18 KB/pt [prod vs docs].
   I could not locate the remaining ~1.27 KB/pt without scale runs. One hard data point: at N=10k a never-indexed (plain-segment) collection used
   **58.5 MB anon after a restart vs 29.9 MB for the same data once indexed** [smoke] - the plain/unindexed state costs about 2x the heap.
   Working hypothesis [infer]: keep the collection in the indexed state and the heap shrinks; this must be verified at >=300k points.
4. **Why production search died (very likely a filesystem problem, not a Qdrant setting):** the Nomad container bind-mounts the Unraid **user share**
   (`/mnt/user/Stash/Nomad`, FUSE `shfs`), and the `qdrant/` folder physically exists on **three array disks** (disk2 3.5 GB, disk3 38 GB, disk5 empty dir) [prod, `ls`/`du`].
   Qdrant's installation docs require *block-level storage with a POSIX file system* and say NFS-style network file systems do not work; for the
   identical "Directory not empty (os error 39)" error a maintainer wrote "I suspect that NFS might be the reason" and another reply called SMB shares "not supported" (issues #3080, #6371). So: put Qdrant on `/mnt/nvme/...` (direct ZFS path) or a single `/mnt/diskN/...`, never `/mnt/user`.
5. **What NOMAD gets by default after switching to int8: NO rescoring.** NOMAD v1.35.0 sends no `params.quantization`. In v1.16.3 `default_rescoring()` is
   `false` for scalar (int8) and PQ, `true` for binary [src]; oversampling default 1.0 [src]. So results are ranked by int8-approximate scores; `score_threshold 0.3` is applied to those scores.
   Rescoring + oversampling (`{"quantization":{"rescore":true,"oversampling":2.0}}`) needs a one-line NOMAD patch. **Recall on real nomic vectors is not measured** (docs claim <1% scalar error); `scripts/fidelity.py` is written to measure it.
6. **Recommended settings** (details and exact JSON in section 8 and `inplace_update.md`): fresh collection on NVMe with
   `vectors.on_disk=true` + scalar int8 `always_ram=true` (V1); add `hnsw_config.on_disk=true` only if RAM is tighter than ~1 KB/chunk (V2); keep payload on disk (already the default).

## 2. Variant table (what each layout costs per chunk)

V0 = NOMAD defaults. V1 = int8 `always_ram` + originals `on_disk` + HNSW in RAM. V2 = V1 + `hnsw_config.on_disk=true`.
V3 = everything on NVMe: originals on disk, int8 **mmap not always_ram**, HNSW on disk, payload indexes on disk.

| variant | disk B/pt | RAM B/pt, healthy indexed collection (formula) | + production-observed heap slack | recall@15 | p95 latency | upsert/s |
|---|---|---|---|---|---|---|
| V0 defaults | 5,423 [prod+smoke] | 3,308 = 3,072 vectors (page cache) + 54 graph + 52 id tracker + 130 payload idx [prod+docs+smoke] | +1,270 [prod] | synthetic 0.946 (N=10k, ef=100) [smoke]; real: not measured | 34 ms synthetic N=10k [smoke, PROVISIONAL load 58] | 1-5/call 108-316; bulk 2,000-2,300 [smoke, PROVISIONAL] |
| V1 int8 always_ram | 6,191 (+768) [docs] | 1,004 = 768 quantized + 54 + 52 + 130 [docs+smoke] | +1,270 | not measured on real vectors; no rescore by default [src] | not measured | not measured |
| V2 = V1 + HNSW on disk | 6,191 | 950 (graph out of RAM) | +1,270 | as V1 | not measured | not measured |
| V3 all on NVMe, int8 mmap | 6,191 | 52 mandatory (+952 wanted as page cache) | +1,270 | as V1 | not measured | not measured |

Binary quantization (96 B/pt in RAM) would rescore by default [src] from the on-disk originals: do not use it while any original vectors sit on a spinning disk.

## 3. Measured on a throw-away v1.16.3 collection, N = 10,000 [smoke]

Created with NOMAD's exact calls (768-d Cosine + 3 keyword + 1 bool payload index on the empty collection). Qdrant 1.16.3 defaults equal production's collection config
exactly (`on_disk_payload=true`, HNSW m16/ef100/full_scan 10000, `indexing_threshold` 10000, WAL 32 MB, no quantization).

**Disk, allocated bytes per point (ZFS, compression off), 10,000 pts, synthetic payload 2,277 B JSON:**

| part | B/pt |
|---|---|
| vectors (`vector_storage/vectors/chunk_*.mmap`) | 3,097.6 |
| payload storage (Gridstore, JSON 2,277 B -> 1,584 B stored, ratio 0.70) | 1,618.1 |
| 4 payload indexes (fixed per-file overhead dominates at 10k; prod ~91) | 195.9 |
| HNSW graph (7,000 of 10,000 pts indexed = 54 B per indexed pt, m=16, compressed links) | 38.0 |
| id tracker | 35.3 |
| segment/collection metadata | 5.6 |
| WAL (fixed, not per point) | 61 MB allocated (100 MB apparent) |
| **total ex-WAL** | **4,990.6** (apparent size 17,684 B/pt: Qdrant pre-allocates sparse 32 MiB chunks - always use allocated bytes) |

**RAM of the qdrant process (RssAnon = heap, RssFile = mapped file pages), MB:**

| state | RssAnon | RssFile |
|---|---|---|
| empty collection | 25.5 | 56.9 |
| right after ingest, optimizer still running (HWM 414 MB) | 155.3 | 250.9 |
| optimizer done + 15 s | 43.0 | 129.2 |
| after 200 queries | 48.4 | 146.4 |
| after container restart (1 GB cap) | **29.9** | 186.7 (everything re-read into page cache) |
| never-indexed (`indexing_threshold=0`) after restart | **58.5** | 178.8 |

- Heap right after a build is mostly allocator slack: it shrinks from 155 MB to 43 MB and to 30 MB after a restart. Report restart numbers as the structural ones.
- After a restart Qdrant pulls the whole collection into the page cache ("cached" tier). [infer for production] a restart of the 4.1M-point collection re-reads ~12 GB of vectors through the FUSE/HDD path.
- Plain -> indexed in place: `PATCH /collections/nomad_knowledge_base {"optimizers_config":{"indexing_threshold":10000}}` worked: 33 s for 10k points at host load ~100 (status `yellow` while optimizing, no error),
  disk allocated 117.2 MB -> peak **169.5 MB (1.45x)** -> 117.6 MB, heap +5 MB peak, CPU 24.6 s = ~2.5 ms CPU per point. Searchability *during* the rebuild was not probed with queries.
- Search shape of NOMAD v1.35.0: `limit 15, score_threshold 0.3, with_payload, filter must_not [active==false]` (the `collection==eval` exclusion exists only in NOMAD's facet calls, `rag_service.ts` l.43-45 vs l.1030-1042). Run on 200 synthetic queries: p50 7.4 / p95 34 ms (load 58, PROVISIONAL).
- Harness check: my numpy exact ground truth equals Qdrant's `exact:true` search (recall@10 = 1.0000 on 100 queries).
- NOMAD's per-job `_ensureCollection()` (4x createPayloadIndex + `is_empty(active)` backfill setPayload) costs 0.01-0.04 s per call at N=10k [smoke], but production telemetry shows
  2,040 index PUTs averaging 4.8 s (max 1,480 s) and 507 setPayloads averaging 155 s (max 3,290 s) in 15 h [prod]. That is [infer] filesystem-path latency plus write contention, a likely major part of the 426 ms average upsert.
- NOMAD-style upserts (1-5 points per call, `wait=true`): 108-316 pts/s, p50 5-12 ms per call; bulk 500 per call: 2,000-2,300 pts/s; steady-state small upserts on an indexed collection ~300 pts/s [smoke, load 40-165, PROVISIONAL].

## 4. Production facts used [prod]

Plain segment 3,989,177 points: vectors 3,072 B/pt, payload 2,171 B/pt stored, payload index ~91 B/pt, jemalloc allocated 5.91 GB (resident 6.12 GB) at 4.11M points,
status red (optimizer error on a `*.deleted` dir), ~20 GB leftover `temp_segments`, 118k of 4.11M points HNSW-indexed, vector storage type `InRamChunkedMmap`, payload storage `mmap` (Gridstore),
payload indexes `mutable_map` (heap) while the segment is plain.

## 5. Extrapolation (decimal GB; N = points)

Constants and formulas: `scripts/extrapolate.py` -> `results/extrapolation.json`. Disk = N x B/pt + 0.06 GB WAL.

**Disk (GB)** - V1, V2, V3 have the same on-disk size (quantized copy +768 B/pt):

| N | V0 | V1 / V2 / V3 | V0 if Wikipedia payload (2.4 KB stored) | V1 if 2.4 KB |
|---|---|---|---|---|
| 4.1M (today) | 22.3 [prod+smoke] | 25.4 [docs+prod] | 23.2 | 26.4 |
| 8M | 43.4 [formula] | 49.6 [formula] | 45.3 | 51.4 |
| 20M | 108.5 [formula] | 123.9 [formula] | 113.1 | 128.5 |
| 40M | 217.0 [formula] | 247.7 [formula] | 226.1 | 256.9 |

Peak during a rebuild: +45% of the segment being rebuilt [smoke 1.45x]; for the current single 20 GB plain segment that is ~+9 GB (the ~20 GB of leftover temp segments in production suggests repeated failed rebuild attempts [infer]).

**RAM (GB) needed for a fast, healthy, indexed collection (formula; "slack" row adds production's unexplained 1.27 KB/pt)**

| N | V0 formula | V0 + slack | V1 formula | V1 + slack | V2 formula | V2 + slack | V3 mandatory | V3 page cache wanted | V3 + slack |
|---|---|---|---|---|---|---|---|---|---|
| 4.1M | 13.6 | 18.8 | 4.1 | 9.3 | 3.9 | 9.1 | 0.2 | 4.1 | 5.4 |
| 8M | 26.5 | 36.6 | 8.0 | 18.2 | 7.6 | 17.8 | 0.4 | 8.0 | 10.6 |
| 20M | 66.2 | 91.6 | 20.1 | 45.5 | 19.0 | 44.4 | 1.0 | 20.1 | 26.4 |
| 40M | 132.3 | 183.1 | 40.2 | 91.0 | 38.0 | 88.8 | 2.1 | 40.2 | 52.9 |

Largest N that fits ~10 GB: V0 3.0M (2.2M with slack), V1 10.0M (4.4M), V2 10.5M (4.5M), V3 mandatory part ~190M but page-cache part 10 GB/952 B = 10.5M (7.6M with slack).
**Verdict for the host (62 GB total, ~8-11 GB usually free): 21M+ chunks fit only as V1/V2 if the heap stays near the documented ~0.18 KB/pt (20 GB at 21M: needs more RAM than is free), or as V3 with a page cache smaller than the working set (NVMe latency decides). Nothing is comfortable at 40M.** The deciding number is the heap per point, which only a >=300k run on a healthy NVMe collection can settle.

**Build time [infer, PROVISIONAL]**: rebuild used 2.5 CPU-ms per point at N=10k (load ~100): 2.8 CPU-hours for 4.1M, 13.7 for 20M (up to ~2x more because HNSW cost grows ~log N); divide by the 4 CPUs granted: ~0.7-1.4 h for the 4.1M plain segment, ~3.4-7 h for 20M.

## 6. Documented behaviour (links)

- **Quantization defaults / rescoring**: `QuantizationSearchParams` in v1.16.3: `ignore=false`, `rescore: Option<bool>` ("if not set, qdrant decides"), `oversampling` default 1.0 -
  https://github.com/qdrant/qdrant/blob/v1.16.3/lib/segment/src/types.rs (struct at l.480-505); automatic rescore choice `default_rescoring()`: scalar/PQ false, binary true -
  https://github.com/qdrant/qdrant/blob/v1.16.3/lib/segment/src/vector_storage/quantized/quantized_vectors.rs (l.194-208). Docs (current): "By default, rescoring is only enabled for binary quantization, TurboQuant 1/1.5/2 bit. Other methods do not rescore by default" - https://qdrant.tech/documentation/manage-data/quantization/#searching-with-quantization
- **Scalar int8** = 1 byte per dimension (768 B/pt), originals kept alongside for rescoring; `always_ram`: "quantized vectors always stored in RAM, ignoring the config of main storage" (v1.16.3 OpenAPI `ScalarQuantizationConfig`) - https://github.com/qdrant/qdrant/blob/v1.16.3/docs/redoc/master/openapi.json . **Binary** = 1 bit per dimension (96 B/pt), rescores by default.
- **Memory formulas**: dense = N x dims x 4 B; quantized = N x dims x quant_bytes; HNSW = N x m x 2 x 4 x 1.2 (= 154 B/pt at m=16; measured compressed graph 54 B/pt); payload disk = N x avg payload x 1.5; payload index ~ 2 x indexed payload (resident); id tracker 52 B/pt resident - https://qdrant.tech/documentation/guides/capacity-planning/
- **Update in place (PATCH)**: patchable: `optimizers_config`, `hnsw_config`, `quantization_config`, `vectors` (map; "to update a collection having a single unnamed vector, use an empty string as name"), `params`; `VectorParamsDiff.on_disk` ("vectors are served from disk"); "`optimizers_config` ... This operation is blocking, it will only proceed once all current optimizations are complete" (v1.16.3 OpenAPI above); docs: https://qdrant.tech/documentation/manage-data/collections/#update-collection-parameters (also describes the bulk recipe: disable indexing while uploading, enable after).
- **`indexing_threshold: 0` disables vector indexing**; `HnswConfigDiff.on_disk`, `inline_storage` (copies of original+quantized vectors inside the HNSW file: fewer random seeks, +3.8 KB/pt disk) - same OpenAPI.
- **Storage requirements**: block-level access + POSIX file system, no NFS - https://qdrant.tech/documentation/installation/#storage ; "if you offload vectors to local disk we recommend SSD or NVMe".
- **"Can't remove segment data ... Directory not empty (os error 39)"**: https://github.com/qdrant/qdrant/issues/3080 (maintainer: NFS likely; "NFS is definitely not a good choice"), https://github.com/qdrant/qdrant/issues/6371 (SMB/Azure files "not supported"). Fixed-race note in v1.19.0 ("defer source segment destruction until durable", #9536) - https://github.com/qdrant/qdrant/releases/tag/v1.19.0
- **What a restart does (v1.16.3 source)**: `LocalShard::load` skips directories ending `.deleted` and calls `fs::remove_dir_all` on them; **if that removal fails the load returns an error ("failed to remove leftover segment")** instead of continuing; segments without a version file are removed the same way; `clear_temp_segments()` deletes the whole `temp_segments/` dir (failure only logged) -
  https://github.com/qdrant/qdrant/blob/v1.16.3/lib/collection/src/shards/local_shard/mod.rs (l.350-365, 415), https://github.com/qdrant/qdrant/blob/v1.16.3/lib/segment/src/segment_constructor/segment_constructor_base.rs (l.690-715), https://github.com/qdrant/qdrant/blob/v1.16.3/lib/collection/src/optimizers_builder.rs (l.146-156).
  [infer] on a healthy filesystem a restart clears the error state, deletes the ~20 GB `temp_segments` and re-runs the optimizer; on the current FUSE path the same `remove_dir_all` can fail again and stop the collection loading until the `*.deleted` dir is removed by hand with Qdrant stopped. **Not reproduced** (ZFS cannot; the fake-leftover test in `scripts/inplace.py` was not run).

## 7. HDD array vs NVMe

Rescoring and HNSW traversal do random reads. A 7,200 rpm disk needs seek ~9 ms + rotational latency 4.17 ms = **~13 ms per random read**
(https://en.wikipedia.org/wiki/Hard_disk_drive_performance_characteristics : desktop drives ~9 ms seek; rotational latency table 7,200 rpm = 4.17 ms; 5,400 rpm = 5.56 ms).
Rescoring 30 candidates (limit 15 x oversampling 2) from the array = 30 x 13 ms = **up to ~0.4 s per query** [formula; a spinning disk serves random reads one at a time]; every HNSW hop or vector read that misses RAM is another ~13 ms -> seconds. Production's 60 s timeouts are different: with the segment never indexed, each search is a brute-force scan of 3.99M plain vectors (12 GB) read through the FUSE/HDD path [prod, per NomadIndexAgent].
On NVMe a random 4 KB read is ~0.1 ms (typical drive spec, not measured here) -> the same 30 rescoring reads cost ~3 ms. In my own small test (page cache evicted, 12.8 major faults per query) the first query pass was p50 11 ms vs 5 ms warm on the ZFS NVMe at load ~60 [smoke, PROVISIONAL].
**Therefore: originals/graph on disk is only sane on NVMe; on the array keep everything the query touches in RAM or do not use the array for Qdrant at all.**

## 8. Recommended settings

Fresh collection on NVMe (NOMAD's `_ensureCollection` only creates a collection when it does not exist, then idempotently adds the 4 payload indexes, so we can pre-create it; `rag_service.ts` l.149-207):

```json
PUT /collections/nomad_knowledge_base
{
  "vectors": {"size": 768, "distance": "Cosine", "on_disk": true},
  "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": true}},
  "hnsw_config": {"m": 16, "ef_construct": 100, "on_disk": false},
  "on_disk_payload": true
}
```
(V1.) V2 = same with `"hnsw_config": {"m": 16, "ef_construct": 100, "on_disk": true}`. Qdrant container: bind `/mnt/nvme/appdata/<dir>:/qdrant/storage` (never `/mnt/user/...`), give it a memory limit so page cache is reclaimed instead of swapping the host.
Bulk (re)load recipe [docs]: create with `"optimizers_config": {"indexing_threshold": 0}`, load, then `PATCH ... {"optimizers_config": {"indexing_threshold": 10000}}` for one build pass.
In-place switch of an existing collection: `inplace_update.md`.

## 9. What is NOT done (and how to do it)

Not run: N>=100k variant runs (disk/RAM slopes, build rate), real-vector recall/NDCG, the in-place quantization PATCH proof, restart-with-leftovers test, anon-heap attribution (`E_plain`, `E_noidx`, `E_idxdisk`, `E_intid` variants are defined in `scripts/run_v.py`).
Scripts are written but **only the old `run_variant.py` (with the earlier `qlab.py`) ran, at N=10k; the current `qlab.py` (random UUIDs, session/lock mode, ssh retry), `run_v.py`, `inplace.py`, `fidelity.py` have never run against a live container** and will need a debug pass. Deferred runs with exact commands and durations: `local://quiet-NomadQdrantLab.md` (driver: `scripts/quiet_window.sh`).
