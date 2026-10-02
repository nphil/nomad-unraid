# Qdrant repair toolkit (2026-10-02 incident)

The scripts that rescued NOMAD's search index after Qdrant stalled on the Unraid user share, plus
the logs and result summaries from that run. Read [the write-up](../../docs/qdrant-storage-and-recovery.md)
first: it explains what happened, the rules that prevent it, and the recovery recipe with the file
formats. This folder is the working record behind it.

These are **incident scripts, kept as a record and as a starting point**, not a supported
tool. They hard-code beastnas paths (`R=/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair`, the
dataset `nvme/appdata/nomad-qdrant-recovered`, a segment id, the Unraid template path). Change
those at the top of each script before using them on another system. Every heavy step ran under
`flock /tmp/agents-heavy.lock`, niced, and with a RAM check first.

## Runbook order

The recovery itself (Qdrant had come back with 220,942 of 4,130,695 chunks because the id table of
its biggest segment only ever lived in memory):

| Step | File | What it does |
| --- | --- | --- |
| 1 | `03_recover_copy.sh` + `recover_convert.py` | Copies the old store to a new NVMe dataset and rebuilds the lost id table from the optimizer's leftover `segment_builder_*` folder (drop the 8-byte header, change one type byte per record). Only reads the old store. |
| 2 | `04_recover_validate.sh` + `recover_check.py` | Loads the result in a capped scratch Qdrant; checks the exact count and compares reference and random points against the raw vectors. Never touches production. |
| 3 | `05_recover_swap.sh` (+ `recreate.php`) | Stops Nomad, points the template's `/data/qdrant` Path at the recovered store (backup first), recreates the container the Unraid way. `99_rollback.sh` restores a template backup (it refuses one with no Qdrant path, which would start Qdrant on the array). |

Cleanup of the recovered index:

| Step | File | What it does |
| --- | --- | --- |
| 4 | `06_dedupe_scan_plan.sh` + `dedupe.py` | Scans for exact duplicates (same source, article, section, chunk number, character count, text) and writes a delete plan. Deletes nothing. |
| 5 | `07_apply_and_build.sh`, `04_patch_build.sh` | Applies the plan, then builds the int8 + HNSW index (`04_patch_build.sh` starts, pauses, resumes and watches the build). |

Verification and aftermath:

| File | What it does |
| --- | --- |
| `08_final_verify.sh`, `verify_prepare.py`, `verify_search.py` | NOMAD-style queries, latency, recall against exact search, RAM, disk. |
| `09_embed_test.sh`, `new_points_check.py`, `snapdiff.py` | Opens the nightly queue for 10 minutes; checks new chunks are written, searchable and indexed; measures what a ZFS snapshot pins. |
| `11_recall_diag.sh`, `recall_diag.py` | Separates real recall loss from ties between identical chunks. |
| `12_restart_nomad.sh` | Plain stop/start of Nomad after a host overload broke `docker exec` into the inner containers. |
| `10_cleanup.sh` | Deletes the old copies. Run only after verification passed. |

Reusable on their own: `verify_search.py`, `new_points_check.py`, `snapdiff.py`, `recall_diag.py`.

## What is here and what is not

- `results/`: the dedupe plan summary, the final and post-restart verification runs, the recall
  diagnostic, Nomad's container state before the repair, Qdrant memory snapshots.
- `logs/`: one log per step (122 KB).
- Not kept: the 83 MB duplicate candidate list and 32 MB delete list (rebuild them with step 4;
  the executed plan is summarised in `results/dedupe_plan.json`), a sample of vectors and texts,
  and the first NVMe move (`01_precopy.sh`, `01b_copy_big.sh`, `02_cutover.sh`), which the recovery
  superseded. Their logs are in `logs/`.
