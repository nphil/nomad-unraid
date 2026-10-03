# NOMAD's AI search database (Qdrant): where it must live, and the October 2026 recovery

Written 2026-10-02 on beastnas, after NOMAD's AI search stopped answering and was repaired.
Plain language first, technical detail after.

## The short version

- **What broke.** Every NOMAD AI search failed after 60 seconds. The vector database (Qdrant) kept its
  files on an Unraid *user share* (`/mnt/user/...`, a FUSE layer). While it was indexing heavily, its
  housekeeping on that share stalled: the job that merges and indexes its data never finished, and the
  list that says which stored vector belongs to which chunk (the "id table") for its biggest block of
  3.99 million chunks was never written to disk. It lived only in the process's memory.
- **Why that mattered.** The first restart (needed to move the files) would have looked like the loss of
  96 % of the knowledge base: Qdrant came back with 220,942 of 4,130,695 chunks. Nothing was actually deleted.
  The vectors and texts were on disk, and the stuck job had left a complete working copy of the id table
  in a scratch folder.
- **What was done.** (1) Qdrant moved to NVMe (a real disk). (2) The lost id table was rebuilt from that
  scratch folder and the full 4,130,695 chunks came back. (3) 868,176 exact duplicate chunks were removed.
  (4) The fast index (HNSW) was built, with int8 compression and the vectors kept on disk.
- **Result.** Search takes about 3 ms instead of failing, the database process holds about 0.83 GB of real
  memory instead of 5.35 GB (the rest it touches is disk cache the system can drop), and the live store is
  about 19 GiB on NVMe.

## Rules (what keeps this from happening again)

1. **`/data/qdrant` must be a real local disk path, never `/mnt/user/...`.** On Unraid use a pool path such
   as `/mnt/cache/appdata/nomad-qdrant`. NOMAD puts Qdrant's files in `<Content path>/qdrant`; the template
   needs its own Path entry for `/data/qdrant` (it has one now). Qdrant itself warns at start-up about
   FUSE ("may cause data corruption due to caching issues"); in `docker logs nomad_qdrant` that line is the
   signal.
2. **Never start a Qdrant on a copy of the store that has leftovers in `collections/*/0/temp_segments`
   until you have saved them.** At load Qdrant deletes that folder. In this incident it held the only
   copy of the id table.
3. **Before restarting a Qdrant that shows `red` or a stuck optimizer, look for state that only lives in
   memory:** a segment whose `mutable_id_tracker.mappings` is hours older than its vector chunk files is
   the warning sign (`ls -l --time-style=full-iso collections/*/0/segments/*/mutable_id_tracker.mappings`).
   If in doubt, export the points through the scroll API first, while the process is still up.
4. **The nightly gate lives in the image now** (`nomad-embed gate`, started by the entrypoint), so a recreate keeps it.
   The Redis pause flag and the parked libraries survive too. Check with `docker exec Nomad nomad-embed status`.
5. **After a host-wide overload (swap full) the inner containers can lose `docker exec`:** `docker exec Nomad docker exec
   nomad_redis ...` fails with "error adding pid ... to cgroups ... cgroup.procs: no such file or directory" and
   `nomad_admin` shows unhealthy, although the apps still answer. A plain `docker stop Nomad` + `docker start Nomad`
   (about a minute, Qdrant and Redis save on the way down) fixes it; the gate restarts with the container (rule 4).
6. **Snapshots of this dataset are cheap in steady state but expensive around a rebuild.** A rebuild pinned
   21 GiB in one snapshot; ordinary nightly churn is small (see the numbers). Check `zfs list -o name,used,usedbysnapshots`
   after any re-index.

## What happened

| When (EDT) | What |
| --- | --- |
| 2026-09-30 | NOMAD indexes into Qdrant on the user share. "Trying to read-lock a segment is taking a long time" warnings start. |
| 10-01 05:00 | Qdrant restarts. Within 21 minutes one plain segment of about 4 million vector slots is written (most likely the merge of the many small segments). |
| 10-01 05:08 | **Last successful flush of that segment's id table.** From here the mappings exist only in RAM. |
| 10-01 05:25-07:06 | The index builder copies the segment into `temp_segments/segment_builder_*`, writes a complete id table (07:01), then starts the HNSW build and never finishes it. |
| 10-01 05:59 | The clean-up after a finished merge fails on the share ("Can't remove segment data ... .deleted"); the optimizer reports an error from here on. |
| 10-01 / 10-02 | Searches fail after 60 s (`Operation 'Search' timed out after 59.99 s`). |
| 10-02 11:30 | Qdrant moved to NVMe. It comes back with 220,942 points. Old instance's count was 4,130,695 = 138,707 + 3,989,177 + 2,811, to the point. |
| 10-02 12:02-12:32 | Recovered store assembled, checked in a scratch Qdrant, then made live. |
| 10-02 12:43-13:37 | 868,176 duplicates removed; int8 + HNSW build (46 minutes for 3.2 million points at 2 threads). |

## How the lost id table was rebuilt (technical)

Qdrant 1.16.3 file formats, read from its source (`lib/segment/src/id_tracker/`):

- Immutable id tracker (what the builder wrote): `id_tracker.mappings` = u64 count, then per point
  `1 byte type (0 number, 1 uuid) + 16 uuid bytes + u32 internal id`; plus `id_tracker.versions` (u64 per
  internal id) and `id_tracker.deleted` (bitset).
- Mutable id tracker (what a plain, appendable segment loads): `mutable_id_tracker.mappings` = append-only
  records `1 byte type (2 = InsertUuid) + 16 uuid bytes + u32 internal id`, no header;
  `mutable_id_tracker.versions` = the same u64 array.

So the conversion is: drop the 8-byte header, change every type byte from 1 to 2, copy the versions file.
The builder's internal ids are the rank of the uuid (it iterates in uuid order), they run 0..N-1 with no
deleted points, so they line up with the builder's own vector chunks and payload pages. The recovered
segment is: builder `vector_storage/` + `payload_storage/` (366 chunks, 259 pages, 64 MiB tracker),
converted id files, `segment.json` and `version.info` copied from the stale segment (plain,
`InRamChunkedMmap`, version 2472778), and `payload_index/config.json` from the stale segment with no field
folders: Qdrant rebuilds missing payload indexes from the stored payloads when it loads (about 6 minutes
for 4 million points). The write-ahead log of the old store was replayed on top.

Checks before it went live (scratch Qdrant, capped at 4 GB): the point count was exactly 4,130,695;
120 of 120 reference points (taken from the independent, consistent part of the old store) had identical
payload and vector; 42 of 42 random points matched the raw vectors in the chunk files; 600 of 600 sampled
vectors of the stale segment were byte-identical to the builder's.

The repair scripts, logs and result summaries are in [`tools/repair/`](../tools/repair/README.md) (runbook order in
its README); the research behind the indexing work is in [`docs/research/`](research/README.md).

## Numbers (2026-10-02)

| | Before | After |
| --- | --- | --- |
| Chunks in the database | 4,130,695 (RED, searches time out) | 3,262,519 after removing 868,176 exact duplicates |
| NOMAD-style search (limit 15, threshold 0.3), median / p90 | fails after 60 s | 3.1 ms / 3.5 ms (host load about 12; first, cold query 49 to 206 ms). Before the index was built: 5 to 20 s, median 8 s. |
| Recall@15 against exact float search | n/a | 0.98 for natural-language queries (14.7 of 15; the missing one differs by 0.0002 in score) |
| Qdrant process memory (anonymous / heap) | 5.35 GB (+131 MB swapped) | 0.83 GB. The file-backed part (0.48 GB cold, up to 11.1 GB after exact full scans) is page cache and can be dropped. |
| Disk | about 41.5 GiB on the array, 19.6 GiB of it stuck leftovers | about 19 GiB on NVMe (ZFS) |
| Index | none on 96 % of the data | HNSW m=16 ef=100, int8 scalar quantization (quantile 0.99, not forced into RAM), vectors on disk |
| New chunks from the nightly queue | not reaching search | written, searchable (4 of 4 sampled new chunks found at ranks 1 to 5) and indexed within minutes |
| ZFS snapshot churn of the live store | n/a | 72 MB and 119 MB pinned by a snapshot per 10-minute embedding window (mostly write-ahead-log files and young segments that get merged). Scaled to a 3-hour night (140,000 to 380,000 new chunks, about 7 to 10 KB pinned per chunk of the previous night) that is roughly 1 to 3 GB. The default daily 7 / weekly 4 / monthly 3 policy is fine; a full re-index would pin the old 19 GiB for up to three months. |

Duplicates were removed only when source, article, section, chunk number and character count were equal
**and** the text was identical; the newest copy was kept, 656 groups with the same key but different text
were left alone. NOMAD never stores or uses point ids (they are random UUIDs, and every update or delete is
by filter on `source`, `collection` or `active`), so nothing in NOMAD's MySQL or Redis refers to the
removed points; only the display-only `kb_ingest_state.chunks_embedded` is now a little higher than the
real count for libraries that had duplicates.

## What was deleted afterwards (with Nitin's approval, after the checks above)

The old array copy (41.5 GiB: 3.4 GiB on disk2, 38.1 GiB on disk3, an empty folder tree on disk5), the first NVMe copy
(20.3 GiB, the partial store with 220,942 points), the ZFS snapshot taken before the duplicate removal (21.1 GiB
held), and a 74 MB scratch folder. NVMe pool free space went from 195 GiB to 237 GiB, disk2 and disk3 gained
3.4 GiB and 38.1 GiB. Only the live store (18.9 GiB, dataset `nomad-qdrant-recovered`) remains. The empty `qdrant`
folder on the share stays: it is the mount point of the container's `/data/qdrant`.

## Changes made to this repo after the recovery

- `unraid/nomad.xml` has a "Vector database (Qdrant)" Path for `/data/qdrant` (default
  `/mnt/cache/appdata/nomad-qdrant`, never `/mnt/user`), so the database does not land on the user share by default.
- The README mount table has a `/data/qdrant` row and `CLAUDE.md` has the matching trap note.
- `QDRANT_CPUSET` and `QDRANT_NICE` (template variables, empty by default) pin and deprioritise Qdrant; the entrypoint
  re-applies them every minute with `docker update --cpuset-cpus` and a per-thread `renice`.

## Follow-ups worth a decision (not done)

- **Tiny chunks: done 2026-10-02.** 530,302 scrap chunks (number-only, tail fragments, title-only stubs; 16.2 %) were
  deleted by id after a snapshot, and NOMAD no longer embeds them (`MIN_CHUNK_CHARS`). 18,217 short real chunks (drug
  brand names, spec values) were kept. The 8 NOMAD-style searches returned the same top-15 afterwards.
- **Wikibooks twins: done 2026-10-02.** 322,045 points of `wikibooks_en_all_nopic` whose article also exists in the maxi
  copy were deleted (98.2 % of the nopic text sits inside maxi's version of the same article; chunk-for-chunk only 85 %,
  because maxi's image text shifts chunk boundaries). 1,386 points of nopic-only articles stay. nopic is parked with
  `nomad-embed exclude`, the ZIM file stays in Kiwix.
- **Disk is not reclaimed yet.** Qdrant only rewrites a block when more than `deleted_threshold` of it is deleted
  (default 0.2); the big block is 25.6 % deleted now, so `deleted_threshold` is parked at 0.5 to stop an unattended
  rewrite. Rewriting it rebuilds the HNSW graph, which Qdrant aborts after 150 minutes; at host load 50 it did not finish.
  Two traps: a `PATCH /collections/...` of the optimizer config **blocks all searches on that collection until the running
  optimization ends** (restore settings only when `/optimizations` shows nothing ongoing), and if it hangs, stop
  `nomad_qdrant`, edit `collections/<name>/config.json` and start it (about 10 s).
- **Seven small libraries have no chunks at all.** `canadian_prepper_bugoutroll`, `canadian-prepper_preppingfood`,
  `freecodecamp`, `lrnselfreliance`, `urban-prepper`, `zimgit-knots` and `zimgit-water` are marked "indexed" in NOMAD's
  database (rows from 2026-09-22 with 0 chunks) but have no points in Qdrant, and the old store did not have them
  either (checked in its index of source names before anything was changed). NOMAD's own scan noticed and queued
  them; they are embedded in the next nightly windows. This was not caused by the repair.
- **The nightly gate and Qdrant's CPU limits are now permanent.** The gate ships in the image
  (`nomad-embed gate`, started by the entrypoint), and `QDRANT_CPUSET` / `QDRANT_NICE` are applied by the
  entrypoint every minute, so a recreate no longer loses them.
