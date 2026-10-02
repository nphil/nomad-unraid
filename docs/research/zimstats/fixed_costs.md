# NOMAD per-batch fixed costs on this host (zimstats slice)

**Status: timings are PROVISIONAL** - every timing below was taken while the host load was 20-75 (limit for valid timings: < 8); the load average is printed next to each number.
Counts, entry numbers and the totals derived from them do **not** depend on load. The timing runs that still need a quiet host are listed in `local://quiet-NomadZimStats.md` (one command per stage, `harness/timing_suite.sh`).

## Plain-language result

1. NOMAD cuts a ZIM into jobs of 50 pages. **Every job re-opens the ZIM and walks the whole entry list from entry 0** up to the job's start offset (redirects and images included), then processes 50 pages.
2. Wikipedia (`wikipedia_en_all_maxi_2026-02`) has **8,425,786 real pages** (Counter `text/html`), so **168,517 jobs**. On average a job must walk **9.4 million entries** (my sample of 13,008 pages), i.e. **1.58 x 10^12 entries over the whole run**.
3. Production shows a job at offset ~99k takes a median 57 s for walk + extracting 50 pages, i.e. at least **3,800 entries/s**. At that speed the walking alone is **13 years** (4,822 days). Even at a hypothetical warm 100,000 entries/s it is **183 days**, at 1,000,000 entries/s **18 days**. The skip cost grows linearly with the offset, so the total grows with the square of the ZIM size. [walk speeds above 3.8k/s are assumptions, to be replaced by the quiet-window measurement]
4. The archive open adds a fixed cost per job: **99 s median in production**, **336-338 s measured cold** (two runs, load 61-73) => 168,517 x 99 s = **193 days** (657 days at 337 s). Cause (strace): libzim's default open preloads dirent ranges = ~1,500 dependent random 256-byte reads over the 2.2 GB dirent area plus a 217 MB pointer-table populate; on the busy HDD each read costs 0.1-2 s.
5. For comparison the *useful* work (embedding ~19.8M chunks, see `zim_sampling.*`) is a fraction of this overhead. A design that opens the ZIM once and keeps one iterator would pay the walk once (~2 x 10^7 entries, minutes to hours) instead of 168,517 times.

## Measured timings (PROVISIONAL, load next to each)

| what | value | load 1/5/15 min | page cache | when / source |
|---|---:|---|---|---|
| `new Archive()` default config (= NOMAD), Wikipedia 124 GB | **338.5 s** | 61.2 / 63.5 / 58.0 | cold; disk3 98 % busy (~220 IOPS) | 20:13 `probe_wiki.mjs` |
| same, worker thread of the dataset run | **336 s** | 73 (1 min) | cold | 20:22 pool log |
| open with `preloadXapianDb(false)` only | > 150 s (timeout) | 36.8 / 74.8 / 74.3 | cold | 20:41 `probe_open.mjs`; strace: dirent-range loop still running |
| open light: `preloadXapianDb(false)` + `preloadDirentRanges(0)`, 4 threads at once + excluded-block search | 123 s | 24 (1 min) | pointer table maybe partly cached | pool slice 2 |
| same, later | 67 s | 33 (1 min) | unknown | pool slice 3 (open line) |
| default open of a 4 MB ZIM (devdocs python) | 0.55 s | 78.8 / 68.8 / 56.0 | warm | 20:11 `probe.mjs` |
| light open of mid-size ZIMs (medlineplus 1 s, medicine 2 s, diy 8 s, ifixit 18 s; all worker threads) | 1-18 s | 23-26 (1 min) | cold-ish | mixed-dataset job |
| random-access read of one random Wikipedia page (blob read incl. cluster decompress), n=10 | mean 0.71 s (0.10-1.72) | 59.0 / 62.8 / 57.9 | cold | `probe_wiki.mjs` |
| `getEntryByPath(randomIndex)` + `isArticleEntry`, n=40 draws | median 0.10 s (0.02-1.95) | 59 (1 min) | cold | `probe_wiki.mjs` |
| blob read per page during sampling, mean of 13,008 pages (parallel readers) | 0.22 s | 20-250 | cold | pool timers |
| NOMAD CPU stages per Wikipedia page (clean 31.6 + strategy 6.7 + extract 7.7 + chunk/payload 2.1 ms), mean HTML 42.9 KB, n=13,008 | mean 48 ms, median 15 ms | 20-250 | n/a | pool timers (contended CPU: upper bound) |
| production (NOMAD logs, via Main) | open median 99 s (mean 164 s); extract+skip median 57 s at offset ~99k; embed+upsert 22 s | - | - | not mine |

Sampling throughput (not a NOMAD number, for planning my own runs): 9.6 accepted pages/s with 6 reader threads (load 60-250), 5.4/s with 4 threads (load 20-25).

### Why the open is slow (strace of the light-config open, 100 s window)
`mmap(MAP_POPULATE)` of the URL pointer table (217,600,224 B = 8 B x 27.2M entries) took 18.3 s; then ~550 `pread(256 B)` calls in pairs at rising offsets (121.85 GB upward, spacing 1.1-2.3 MB) = the dirent-range preload (`OpenConfig.preloadDirentRanges`, "nbRanges+1 dirents are loaded"); extrapolated ~1,500 steps ~ 330 s, matching the measured 336-338 s. `preloadXapianDb(false)` does not remove it (log kept: `logs/strace_open_noxapian.log`).

## Entry walk per job (load independent; sample CDF of 13,008 uniformly random Wikipedia pages)

| start offset (articles) | entries walked (est.) | seconds @ 3.8k/s (production lower bound) | @ 100k/s [assumed] | @ 1M/s [assumed] |
|---:|---:|---:|---:|---:|
| 10,000 | 15.6 k | 4 | 0.2 | 0.02 |
| 99,350 (NOMAD today) | 216.6 k | 57 (by construction) | 2.2 | 0.2 |
| 500,000 | 1.10 M | 289 | 11 | 1.1 |
| 1,000,000 | 2.18 M | 575 | 22 | 2.2 |
| 2,000,000 | 4.44 M | 1,168 | 44 | 4.4 |
| 4,000,000 | 8.91 M | 2,344 | 89 | 8.9 |
| 6,000,000 | 13.3 M | 3,507 (58 min) | 133 | 13 |

(Entry index of the n-th page = quantile of the sampled pages' entry indexes; +-8 % at 99k because only 153 sampled pages lie there. 27.2M entries in total: 8.43M pages, 10.56M redirects, 8.22M media items in one contiguous `_assets_/` block.)

Whole-run totals for Wikipedia: jobs 168,517 x mean 9.40M entries = **1.583 x 10^12 entries**; plus open 168,517 x 99 s = 193 days.

## Other big ZIMs (walk only; mean entries per job = headerEntryCount/2 [inference])
See `fixed_costs.json` -> `entry_walk_totals.perZim`. Largest: electronics.stackexchange 7,047 jobs, 4.3 x 10^9 entries (13 days at 3.8k/s, 12 h at 100k/s); ifixit 5,078 jobs, 2.3 x 10^9 (7 days / 6 h); diy.stackexchange 3,546 jobs, 9.2 x 10^8 (2.8 days / 2.6 h); wikipedia_en_medicine 2,035 jobs, 4.7 x 10^8 (1.4 days / 1.3 h); wikibooks 2,045 jobs, 3.7 x 10^8.

## Not measured yet (needs quiet host) -> `local://quiet-NomadZimStats.md`
(a) cold/warm x3 open repetitions (default and light config); (b) measured walk speed per offset (continuous pass and NOMAD-equivalent job at 0/10k/100k/500k); (c) sequential cluster-order read vs random read rate; (d) isolated CPU benchmark; optional NVMe copy comparison.
