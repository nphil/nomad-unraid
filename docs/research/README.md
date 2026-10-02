# Research behind the NOMAD indexing work (2026-10-01 and 02)

Measurements and reading that led to the nightly embedding window, the choice to keep nomic
embeddings, and the Qdrant rebuild. Numbers are from beastnas, usually measured under heavy host
load, and are tagged provisional where they were. Start with the plain-language sections at the top
of each file.

| Where | What it answers |
| --- | --- |
| [`../indexing-estimate.md`](../indexing-estimate.md) | How long indexing everything takes, and what fits in a night. |
| `models.md`, `models.json` | Which embedding models a Tesla P40 can run through llama-server, and what they cost per chunk. The raw MTEB inputs it cites were not kept (re-downloadable). |
| `nomad_upstream.md` | What upstream NOMAD has fixed, and what it has not (the per-job ZIM re-walk, the embed-probe issue). |
| `wikipedia_variants.md`, `wikipedia_variants.json` | The English Wikipedia ZIM flavours (maxi, nopic, mini) and how much text each holds. |
| `zimstats/` | Chunk, character and token counts per installed ZIM, per-job fixed costs (`fixed_costs.md`), sampling tables. The harness that produced them was not kept. |
| `qdrantlab/` | What a NOMAD-style Qdrant collection costs in disk and RAM (report in `results.md`, in-place update study in `inplace_update.md`, scripts). Scope was cut: only 10,000-point runs were measured. |
| `bench/` | Granite versus nomic embedding benchmarks: scripts, logs and result files. Outcome: granite gained +0.3 to +0.7 recall points on NOMAD-style questions (the bar was +3) and is 25 to 30 % slower, so it stays off. |
| `state-before-repair/` | Qdrant collection config, telemetry, per-source facet and queue state captured before the repair. |

Not kept (all regenerable): sampled chunk datasets, benchmark embedding caches, a 10 MB payload
sample, and the 6.5 GB of downloaded model files.

The scripts keep the paths they ran with (`/data/home/tmp/nomadindex/...`, `/mnt/nvme/appdata/...`);
adjust them before re-running. References to `local://quiet-*.md` notes point at hand-off files of the
Cody workspace that are not part of this repo.
