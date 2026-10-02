# Switching the existing NOMAD collection to compact settings in place (no re-embedding)

Qdrant v1.16.3 (production's version). Collection name used by NOMAD: `nomad_knowledge_base`. Replace `Q` with the Qdrant REST URL (`http://<host>:6333`).
Tags: **[smoke]** measured by me (N=10,000, throw-away container), **[src]** read in the v1.16.3 source/OpenAPI, **[docs]** Qdrant docs, **[infer]** my inference. **Not tested by me: the quantization/on_disk PATCH on a populated collection** (the run was cancelled for host load); only the `indexing_threshold` PATCH was executed.

## 1. Exact requests

```bash
Q=http://localhost:6333
C=nomad_knowledge_base

# V1: int8 scalar quantization (quantized copy always in RAM) + original float32 vectors served from disk
curl -sS -X PATCH $Q/collections/$C -H 'content-type: application/json' -d '{
  "vectors": {"": {"on_disk": true}},
  "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": true}}
}'

# V2: V1 + HNSW graph on disk (only if RAM is tighter than ~1 KB per chunk)
curl -sS -X PATCH $Q/collections/$C -H 'content-type: application/json' -d '{
  "vectors": {"": {"on_disk": true}},
  "hnsw_config": {"on_disk": true},
  "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": true}}
}'

# V3 (everything on NVMe): quantized copy memory-mapped instead of pinned in RAM
curl -sS -X PATCH $Q/collections/$C -H 'content-type: application/json' -d '{
  "vectors": {"": {"on_disk": true}},
  "hnsw_config": {"on_disk": true},
  "quantization_config": {"scalar": {"type": "int8", "quantile": 0.99, "always_ram": false}}
}'

# undo quantization
curl -sS -X PATCH $Q/collections/$C -H 'content-type: application/json' -d '{"quantization_config": "Disabled"}'

# watch the rebuild (status yellow = optimizing, green = done; segments_count and indexed_vectors_count move)
curl -sS $Q/collections/$C | python3 -m json.tool | head -40
curl -sS "$Q/telemetry?details_level=10" | python3 -c "import sys,json; t=json.load(sys.stdin)['result']; [print(s['info']['segment_type'], s['info']['num_points'], s['config']['vector_data']['']['storage_type'], s['config']['vector_data']['']['quantization_config']) for c in t['collections']['collections'] for sh in c['shards'] for s in sh['local']['segments']]"
```

Body semantics, from the v1.16.3 OpenAPI (https://github.com/qdrant/qdrant/blob/v1.16.3/docs/redoc/master/openapi.json): `UpdateCollection.vectors` = "map of vector data parameters to update for each named vector;
to update a collection having a single unnamed vector, use an empty string as name" (hence `"vectors": {"": ...}`); `VectorParamsDiff.on_disk` = "vectors are served from disk"; `quantization_config` top-level "if none - left unchanged";
`ScalarQuantizationConfig.always_ram` = "quantized vectors always stored in RAM, ignoring the config of main storage".
Docs page: https://qdrant.tech/documentation/manage-data/collections/#update-collection-parameters (parameters can be changed on the fly; its own example is the bulk-load recipe: indexing off while uploading, `indexing_threshold: 10000` afterwards).

## 2. What Qdrant does after the PATCH [src]

No restart is needed and nothing is re-embedded: the float32 vectors stay in the segments, the quantized copy is derived from them.
The collection config is stored immediately; a background `ConfigMismatchOptimizer` selects every segment whose real parameters differ from the configured ones and rebuilds it
(https://github.com/qdrant/qdrant/blob/v1.16.3/lib/collection/src/collection_manager/optimizers/config_mismatch_optimizer.rs, l.76-176): payload storage on/off disk mismatch; HNSW parameters that require a rebuild; **vectors `on_disk` differing from the segment's storage type (any segment, plain ones included)**;
quantization config changed (for an indexed segment also when quantization is merely switched on/off). A segment is therefore rebuilt in the background into a new segment (indexed + quantized + vectors on disk) and swapped in when ready; the old segment is deleted afterwards.
Searches keep running on the old segments meanwhile [docs/infer]; **I did not probe searches during a rebuild**. Anything `status != green` means optimizing, not broken.

Costs while it runs:
- **Disk peak = old segment + new segment**: measured 1.45x for a plain->indexed rebuild at N=10k (117.2 -> 169.5 MB -> 117.6 MB) [smoke]. For the production collection (one 20 GB plain segment) budget +9 GB, **plus** whatever stale `temp_segments` are still on disk.
- **CPU**: HNSW build + quantization ~2.5 CPU-ms per point at N=10k [smoke, load ~100] -> ~2.8 CPU-h for 4.1M, 13.7 CPU-h for 20M, possibly up to 2x more [infer]; with the 4 CPUs normally granted ~0.7-1.4 h for 4.1M.
- **RAM**: heap grew only +5 MB at the 10k rebuild peak [smoke]; at scale [infer] the builder holds the graph links of the segment being built (order of N x 2m x 4 B = 128 B/pt uncompressed).
- `PATCH` with `optimizers_config` "is blocking, it will only proceed once all current optimizations are complete" [src, OpenAPI]: **on a collection with a stuck optimizer do not put `optimizers_config` in the PATCH** (the quantization/vectors/hnsw PATCH above does not touch it).

## 3. What was actually executed [smoke]

Throw-away collection created with NOMAD's defaults + `indexing_threshold: 0` (never indexed = production's plain-segment state), 10,000 points, then:

```bash
curl -X PATCH $Q/collections/nomad_knowledge_base -H 'content-type: application/json' -d '{"optimizers_config": {"indexing_threshold": 10000}}'
# -> {"result":true,"status":"ok","time":0.0248}
```
33 s until green at host load ~100 (status `yellow` during, no errors, 2 plain segments of 5,000 -> 2 segments with 10,600 indexed vectors incl. later duplicates), heap +5 MB at peak, disk 1.45x at peak, CPU 24.6 s.
Result file: `results/plain.test.10000.smoke.json` (key `unstick`).

## 4. What a restart does to a stuck optimizer / leftovers [src], not reproduced

Source of truth: `LocalShard::load` (https://github.com/qdrant/qdrant/blob/v1.16.3/lib/collection/src/shards/local_shard/mod.rs l.350-365 and l.415), `load_segment` (.../segment_constructor_base.rs l.690-715), `clear_temp_segments` (.../optimizers_builder.rs l.146-156):
1. `temp_segments/` (the 20 GB of leftovers in production) is deleted at startup; a failure is only logged as a warning.
2. Segment directories whose name ends `.deleted` are skipped by `load_segment`, then removed with `fs::remove_dir_all`; **if that removal fails, loading the shard returns an error** ("failed to remove leftover segment ...") rather than continuing. Segments without a version file (crash mid-write) take the same path.
3. The optimizer error text in production (`Can't remove segment data at ./storage/collections/nomad_knowledge_base/0/segments/<uuid>.deleted ... Directory not empty (os error 39)`) is held in memory; a restart clears it, and on a sane filesystem the optimizer simply runs again.
[infer] On the current storage path the same `remove_dir_all` may fail again on restart, which would stop the collection from loading until the `<uuid>.deleted` directory is deleted by hand while Qdrant is stopped.

**Likely root cause (strong evidence, not proven):** production's Qdrant folder is reached through the Unraid user share (FUSE `shfs`): the Nomad container binds `/mnt/user/Stash/Nomad` [prod], and `qdrant/` exists on three array disks at once (`/mnt/disk2` 3.5 GB, `/mnt/disk3` 38 GB, `/mnt/disk5` empty dir) [prod]. Qdrant requires "block-level access to storage devices with a POSIX-compatible file system" and "won't work with network file systems"
(https://qdrant.tech/documentation/installation/#storage); the same `Directory not empty (os error 39)` error was answered by maintainers with "NFS/non-POSIX storage" (https://github.com/qdrant/qdrant/issues/3080, https://github.com/qdrant/qdrant/issues/6371).

## 5. Safe sequence for production (my recommendation, untested)

1. Pause NOMAD embedding (queue already paused), stop the Qdrant container gracefully.
2. Copy the storage tree to NVMe, skipping garbage: `rsync -a --exclude 'temp_segments' --exclude '*.deleted' /mnt/user/Stash/Nomad/qdrant/ /mnt/nvme/appdata/nomad-qdrant/` (reads the logical tree through shfs once; ~21 GB).
3. Start `qdrant/qdrant:v1.16.3` with `-v /mnt/nvme/appdata/nomad-qdrant:/qdrant/storage` (direct ZFS path, **not** `/mnt/user`), env `QDRANT__TELEMETRY_DISABLED=true`, a memory limit.
4. Wait until it is loaded (status may be yellow: the 3.99M-point plain segment will now be indexed, ~1 h of CPU [infer]); then PATCH V1 (section 1). Both go through the same background rebuild; if you PATCH first, the single rebuild of the plain segment already produces the indexed+quantized+on-disk layout.
5. NOMAD keeps calling `createPayloadIndex` (idempotent) and the `is_empty(active)` backfill on every first use after a restart: harmless on NVMe (0.01-0.04 s at N=10k).
6. Only if NOMAD should rescore: patch the search call to pass `"params": {"quantization": {"rescore": true, "oversampling": 2.0}}` (NOMAD sends none today, so int8 is not rescored: v1.16.3 `default_rescoring()` is false for scalar).

## 6. Scripts

`scripts/inplace.py` (written, **never run**) does the full proof in one lock-held session: builds the 100k-point NOMAD-default collection, PATCHes it to V1 while a background thread runs NOMAD-shaped searches, traces status/segments/disk/RAM until green, measures recall before/after against exact search, then tests a graceful restart, a restart with a fake `*.deleted` dir + 50 MB `temp_segments`, and a SIGKILL in the middle of a second rebuild. Command: `cd /data/home/tmp/nomadindex/qdrantlab && OPENBLAS_NUM_THREADS=2 nice -n 15 python3 scripts/inplace.py --n 100000 --patch v1` (needs the synthetic data and request bodies regenerated first; see `local://quiet-NomadQdrantLab.md`).
