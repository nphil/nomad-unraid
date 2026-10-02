# English Wikipedia ZIM variants (Kiwix catalog snapshot 2026-10-01)

Worker: `research` slice. Everything below was fetched on 2026-10-01 from the live Kiwix OPDS catalog (`articleCount`, `mediaCount`, size = OPDS `length`) and, for the real page counts, from each ZIM's own `M/Counter` metadata (read with HTTP range requests, nothing downloaded in full). Machine-readable copy: `wikipedia_variants.json`.

## Plain-language answer

- **The catalog's `articleCount` is NOT the number of articles.** It also counts *redirects* (alias pages such as `USA -> United States`). For the file NOMAD is indexing, `wikipedia_en_all_maxi_2026-02.zim`, the `archive.articleCount` NOMAD sees is 18,982,214 but the ZIM really holds **8,425,786 HTML pages** (the rest, 10,556,428, are redirects). NOMAD's own progress bar divides by the inflated number, so a finished Wikipedia run would show only ~44%.
- **The three flavours hold the same article list but very different amounts of text**: `maxi` = full articles with images, `nopic` = the same full text without images (so the *index* is the same size as maxi, only the download is smaller), `mini` = only the introduction + infobox of every article (about 1/9 of the file size, much less text to embed).
- **Smaller Wikipedia options exist**: `wikipedia_en_top` (about 50,000 best articles, 0.30-6.99 GB), `wikipedia_en_top1m` (1.77 M pages, 3-49 GB), `wikipedia_en_100` (0.33 GB), Simple English (0.53-3.1 GB) and 24 topical packs (medicine, physics, chemistry, mathematics, history, computer, ...).
- **Page counts change between builds.** Today's `all_maxi` build (2026-08) contains 10.92 M HTML pages versus 8.43 M in the 2026-02 build NOMAD uses; the 2026-09 `all_mini` contains 7.33 M versus 8.51 M in the 2026-06 mini. Always read the Counter of the exact file before planning an index size.

## How `articleCount` is defined (is it redirects?) - yes, it includes them

- libzim doc: getArticleCount() = all entries marked FRONT_ARTICLE at ZIM creation time; implementation returns the front-article index size when present, else the Counter text/html* total.
- kiwix-tools #536 (2022): catalog articleCount=16,229,464 for wikipedia_en_all_maxi_2021-12 while M/Counter text/html=6,422,607.
- NOMAD #1185 (maintainer measurement, wikipedia_en_all_maxi_2026-02): raw entries 27,199,904 = redirects 10,556,428 + non-html items 8,217,690 + isArticleEntry() 8,425,786; archive.articleCount 18,982,214 = 8,425,786 + 10,556,428.
- My own read of that same ZIM's M/Counter (2026-10-01): text/html=8,425,786 (+1 text/html; charset=iso-8859-1) - identical to the maintainer figure; dirents 27,199,921.

Links: libzim docs <https://github.com/openzim/libzim/blob/master/include/zim/archive.h>, implementation <https://github.com/openzim/libzim/blob/master/src/archive.cpp>, <https://github.com/kiwix/kiwix-tools/issues/536>, NOMAD <https://github.com/Crosstalk-Solutions/project-nomad/issues/1185#issuecomment-5427962842>.

OPDS `length` is the file size rounded up to a multiple of 1 KiB (e.g. `wikipedia_en_all_maxi_2026-08`: OPDS 127,418,088,448 vs HTTP Content-Length 127,418,087,648).

## Flavours (primary source: <https://kiwix.org/en/frequently-asked-questions/>)

| flavour | meaning (quote) | OPDS tags |
|---|---|---|
| `mini` | "only the introduction of each article, plus the infobox. Saves about 95% of space vs. the full version." | `_details:no;_pictures:no` |
| `nopic` | "full articles, but no images. About 75% smaller than the full version." | `_details:yes;_pictures:no` |
| `maxi` | "the default full version." | `_details:yes;_pictures:yes` |

## General variants (full details)

`pages (Counter text/html)` = real HTML pages = what NOMAD's `isArticleEntry()` iterates; `articleCount` and `mediaCount` are quoted exactly from the OPDS entry; size is OPDS `length` in bytes (GB = 10^9).

| book (latest) | flavour | updated | size (bytes) | size GB | articleCount (OPDS) | mediaCount (OPDS) | pages (Counter text/html) | redirects (inferred) | contents | download |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|
| `wikipedia_en_all_maxi_2026-08` | maxi | 2026-08-25 | 127,418,088,448 | 127.42 | 21,673,012 | 8,469,385 | 10,923,207 | 10,749,805 | The free encyclopedia | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_maxi_2026-08.zim> |
| `wikipedia_en_all_nopic_2026-06` | nopic | 2026-06-17 | 52,690,707,456 | 52.69 | 19,191,219 | 515,775 | 8,516,991 | 10,674,228 | The free encyclopedia | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_nopic_2026-06.zim> |
| `wikipedia_en_all_mini_2026-09` | mini | 2026-09-09 | 14,386,799,616 | 14.39 | 18,095,848 | 33,992 | 7,331,817 | 10,764,031 | The free encyclopedia | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_2026-09.zim> |
| `wikipedia_en_top_maxi_2026-09` | maxi | 2026-09-14 | 6,991,082,496 | 6.99 | 877,754 | 618,143 | 224,147 | 653,607 | A selection of the best 50,000 Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top_maxi_2026-09.zim> |
| `wikipedia_en_top_nopic_2026-09` | nopic | 2026-09-14 | 2,745,850,880 | 2.75 | 877,754 | 52,909 | 224,147 | 653,607 | A selection of the best 50,000 Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top_nopic_2026-09.zim> |
| `wikipedia_en_top_mini_2026-09` | mini | 2026-09-14 | 296,858,624 | 0.30 | 703,608 | 1,907 | 50,002 | 653,606 | A selection of the best 50,000 Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top_mini_2026-09.zim> |
| `wikipedia_en_top1m_maxi_2026-04` | maxi | 2026-04-28 | 49,385,356,288 | 49.39 | 5,918,856 | 3,677,489 | 1,774,449 | 4,144,407 | A selection of the best 1 Million Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top1m_maxi_2026-04.zim> |
| `wikipedia_en_top1m_nopic_2026-04` | nopic | 2026-04-28 | 17,134,155,776 | 17.13 | 5,918,889 | 286,527 | 1,774,449 | 4,144,440 | A selection of the best 1 Million Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top1m_nopic_2026-04.zim> |
| `wikipedia_en_top1m_mini_2026-04` | mini | 2026-04-28 | 3,022,411,776 | 3.02 | 5,918,899 | 11,128 | 1,774,449 | 4,144,450 | A selection of the best 1 Million Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_top1m_mini_2026-04.zim> |
| `wikipedia_en_100_2026-08` | - | 2026-08-20 | 333,430,784 | 0.33 | 5,056 | 4,122 | 1,322 | 3,734 | Top one hundred Wikipedia articles | <https://download.kiwix.org/zim/wikipedia/wikipedia_en_100_2026-08.zim> |
| `wikipedia_en-simple_all_maxi_2026-09` | maxi | 2026-09-27 | 3,121,061,888 | 3.12 | 400,061 | 343,260 | 290,034 | 110,027 | Wikipedia in a simple English | <https://download.kiwix.org/zim/wikipedia/wikipedia_en-simple_all_maxi_2026-09.zim> |
| `wikipedia_en-simple_all_nopic_2026-09` | nopic | 2026-09-27 | 1,094,936,576 | 1.09 | 400,061 | 5,386 | 290,034 | 110,027 | Wikipedia in a simple English | <https://download.kiwix.org/zim/wikipedia/wikipedia_en-simple_all_nopic_2026-09.zim> |
| `wikipedia_en-simple_all_mini_2026-09` | mini | 2026-09-27 | 530,482,176 | 0.53 | 395,241 | 1,641 | 285,214 | 110,027 | Wikipedia in a simple English | <https://download.kiwix.org/zim/wikipedia/wikipedia_en-simple_all_mini_2026-09.zim> |

Notes on the selections (from the catalog summaries + Counter):
- `wikipedia_en_top_*`: catalog says "A selection of the best 50,000 Wikipedia articles". The `mini` build contains 50,002 HTML pages (the 50,000 plus 2 extra pages [inference]); the `nopic`/`maxi` builds contain 224,147 HTML pages (more than the 50k selection; extra pages are probably linked pages - [inference]). The selection tooling is openzim `wp1_selection_tools` (pageviews, links, ...) - <https://github.com/openzim/wp1_selection_tools>; community note that top-50k is celebrity-heavy: <https://github.com/openzim/zim-requests/issues/508>.
- `wikipedia_en_top1m_*`: "A selection of the best 1 Million Wikipedia articles"; the three flavours all hold 1,774,449 HTML pages.
- `wikipedia_en_100`: "Top one hundred Wikipedia articles"; 1,322 HTML pages (the 100 plus linked pages [inference]).
- `wikipedia_en-simple_all_*`: Simple English Wikipedia ("Wikipedia in a simple English").

## Topical English packs (all flavours that exist)

| book (latest) | flavour | updated | size GB | articleCount (OPDS) | mediaCount (OPDS) | pages (Counter) | summary |
|---|---|---|---:|---:|---:|---:|---|
| `wikipedia_en_astronomy_maxi_2026-08` | maxi | 2026-08-24 | 1.77 | 152,761 | 65,946 | 81,855 | A selection of Wikipedia articles on astronomy |
| `wikipedia_en_astronomy_nopic_2026-08` | nopic | 2026-08-24 | 0.40 | 152,761 | 7,055 | 81,855 | A selection of Wikipedia articles on astronomy |
| `wikipedia_en_baseball_maxi_2026-09` | maxi | 2026-09-12 | 0.87 | 112,733 | 48,197 | 54,634 | A selection of Wikipedia articles on baseball |
| `wikipedia_en_baseball_nopic_2026-09` | nopic | 2026-09-12 | 0.50 | 112,733 | 368 | 54,634 | A selection of Wikipedia articles on baseball |
| `wikipedia_en_basketball_maxi_2026-09` | maxi | 2026-09-17 | 0.51 | 87,423 | 25,034 | 37,018 | A selection of Wikipedia articles on basketball |
| `wikipedia_en_basketball_nopic_2026-09` | nopic | 2026-09-17 | 0.33 | 87,423 | 251 | 37,018 | A selection of Wikipedia articles on basketball |
| `wikipedia_en_chemistry_maxi_2026-07` | maxi | 2026-07-16 | 0.51 | 57,058 | 43,989 | 23,803 | A selection of Wikipedia articles on chemistry |
| `wikipedia_en_chemistry_nopic_2026-07` | nopic | 2026-07-16 | 0.13 | 57,058 | 13,579 | 23,803 | A selection of Wikipedia articles on chemistry |
| `wikipedia_en_chemistry_mini_2026-07` | mini | 2026-07-16 | 0.02 | 57,058 | 1,155 | 23,803 | A selection of Wikipedia articles on chemistry |
| `wikipedia_en_climate-change_maxi_2026-07` | maxi | 2026-07-06 | 0.22 | 20,144 | 12,888 | 6,852 | A selection of Wikipedia articles on climate change |
| `wikipedia_en_climate-change_nopic_2026-07` | nopic | 2026-07-06 | 0.09 | 20,144 | 822 | 6,852 | A selection of Wikipedia articles on climate change |
| `wikipedia_en_climate-change_mini_2026-07` | mini | 2026-07-06 | 0.01 | 20,144 | 127 | 6,852 | A selection of Wikipedia articles on climate change |
| `wikipedia_en_comics_maxi_2026-07` | maxi | 2026-07-16 | 0.66 | 94,406 | 27,134 | 48,420 | A selection of Wikipedia articles on comic books |
| `wikipedia_en_comics_nopic_2026-07` | nopic | 2026-07-16 | 0.32 | 94,406 | 120 | 48,420 | A selection of Wikipedia articles on comic books |
| `wikipedia_en_computer_maxi_2026-09` | maxi | 2026-09-15 | 0.91 | 244,023 | 74,569 | 91,847 | A selection of Wikipedia articles on computer |
| `wikipedia_en_computer_nopic_2026-09` | nopic | 2026-09-15 | 0.52 | 244,023 | 18,291 | 91,847 | A selection of Wikipedia articles on computer |
| `wikipedia_en_cricket_maxi_2026-07` | maxi | 2026-07-16 | 0.38 | 88,847 | 15,207 | 49,750 | A selection of Wikipedia articles on cricket |
| `wikipedia_en_cricket_nopic_2026-07` | nopic | 2026-07-16 | 0.25 | 88,847 | 154 | 49,750 | A selection of Wikipedia articles on cricket |
| `wikipedia_en_football_maxi_2026-04` | maxi | 2026-04-10 | 3.54 | 710,693 | 253,110 | 319,040 | All Wikipedia articles on football |
| `wikipedia_en_football_nopic_2026-07` | nopic | 2026-07-09 | 2.58 | 710,223 | 268 | 317,993 | All Wikipedia articles on football |
| `wikipedia_en_geography_maxi_2026-07` | maxi | 2026-07-13 | 1.48 | 213,925 | 91,014 | 102,180 | A selection of Wikipedia articles on geography |
| `wikipedia_en_geography_nopic_2026-07` | nopic | 2026-07-13 | 0.57 | 213,925 | 1,200 | 102,180 | A selection of Wikipedia articles on geography |
| `wikipedia_en_golf_maxi_2026-07` | maxi | 2026-07-17 | 0.14 | 25,938 | 7,141 | 12,960 | A selection of Wikipedia articles on golf |
| `wikipedia_en_golf_nopic_2026-07` | nopic | 2026-07-17 | 0.09 | 25,938 | 136 | 12,960 | A selection of Wikipedia articles on golf |
| `wikipedia_en_history_maxi_2026-07` | maxi | 2026-07-14 | 2.38 | 224,313 | 158,247 | 69,681 | A selection of Wikipedia articles on History |
| `wikipedia_en_history_nopic_2026-07` | nopic | 2026-07-14 | 0.73 | 224,312 | 498 | 69,681 | A selection of Wikipedia articles on History |
| `wikipedia_en_ice-hockey_maxi_2026-07` | maxi | 2026-07-15 | 0.60 | 96,525 | 29,324 | 42,405 | A selection of Wikipedia articles on ice hockey |
| `wikipedia_en_ice-hockey_nopic_2026-07` | nopic | 2026-07-15 | 0.33 | 96,525 | 156 | 42,405 | A selection of Wikipedia articles on ice hockey |
| `wikipedia_en_indian-cinema_maxi_2026-07` | maxi | 2026-07-16 | 0.44 | 54,911 | 23,240 | 28,433 | A selection of Wikipedia articles on Bollywood |
| `wikipedia_en_indian-cinema_nopic_2026-07` | nopic | 2026-07-16 | 0.19 | 54,911 | 109 | 28,433 | A selection of Wikipedia articles on Bollywood |
| `wikipedia_en_knots_maxi_2026-07` | maxi | 2026-07-20 | 0.02 | 1,730 | 3,501 | 596 | A subset of Wikipedia encyclopedia dedicated to knots |
| `wikipedia_en_mathematics_maxi_2026-09` | maxi | 2026-09-15 | 1.00 | 113,072 | 361,161 | 41,531 | A selection of Wikipedia articles on mathematics |
| `wikipedia_en_mathematics_nopic_2026-09` | nopic | 2026-09-15 | 0.37 | 113,072 | 278,246 | 41,531 | A selection of Wikipedia articles on mathematics |
| `wikipedia_en_mathematics_mini_2026-06` | mini | 2026-06-17 | 0.06 | 112,869 | 19,124 | 41,437 | A selection of Wikipedia articles on mathematics |
| `wikipedia_en_medicine_maxi_2026-04` | maxi | 2026-04-11 | 2.22 | 362,501 | 100,895 | 102,062 | The largest medical encyclopedia, from Wikipedia |
| `wikipedia_en_medicine_nopic_2026-04` | nopic | 2026-04-11 | 0.86 | 362,501 | 5,304 | 102,062 | The largest medical encyclopedia, from Wikipedia |
| `wikipedia_en_medicine_mini_2026-04` | mini | 2026-04-11 | 0.16 | 362,501 | 318 | 102,062 | The largest medical encyclopedia, from Wikipedia |
| `wikipedia_en_molcell_maxi_2026-04` | maxi | 2026-04-14 | 0.99 | 129,647 | 61,013 | 40,442 | 30,000 Molecular and Cell Biology articles from Wikipedia |
| `wikipedia_en_molcell_nopic_2026-07` | nopic | 2026-07-15 | 0.34 | 113,729 | 3,037 | 34,297 | 30,000 Molecular and Cell Biology articles from Wikipedia |
| `wikipedia_en_movies_maxi_2026-07` | maxi | 2026-07-09 | 5.31 | 701,705 | 272,749 | 350,774 | A selection of Wikipedia articles on movies |
| `wikipedia_en_movies_nopic_2026-07` | nopic | 2026-07-09 | 2.55 | 701,710 | 356 | 350,774 | A selection of Wikipedia articles on movies |
| `wikipedia_en_nollywood_maxi_2026-07` | maxi | 2026-07-17 | 0.02 | 3,150 | 1,255 | 1,961 | Encyclopedia of Nigerian cinema |
| `wikipedia_en_physics_maxi_2026-07` | maxi | 2026-07-16 | 1.33 | 99,397 | 166,308 | 32,591 | A selection of Wikipedia articles on physics |
| `wikipedia_en_physics_nopic_2026-07` | nopic | 2026-07-16 | 0.32 | 99,397 | 105,354 | 32,591 | A selection of Wikipedia articles on physics |
| `wikipedia_en_physics_mini_2026-07` | mini | 2026-07-16 | 0.06 | 99,397 | 6,324 | 32,591 | A selection of Wikipedia articles on physics |
| `wikipedia_en_ray-charles_maxi_2026-08` | maxi | 2026-08-02 | 0.00 | 340 | 178 | 152 | Wikipedia articles about Ray Charles |
| `wikipedia_en_ray-charles_nopic_2026-08` | nopic | 2026-08-02 | 0.00 | 340 | 25 | 152 | Wikipedia articles about Ray Charles |
| `wikipedia_en_ray-charles_mini_2026-08` | mini | 2026-08-02 | 0.00 | 340 | 21 | 152 | Wikipedia articles about Ray Charles |
| `wikipedia_en_sociology_maxi_2026-07` | maxi | 2026-07-16 | 0.57 | 66,453 | 32,002 | 20,095 | A selection of Wikipedia articles on sociology |
| `wikipedia_en_sociology_nopic_2026-07` | nopic | 2026-07-16 | 0.24 | 66,453 | 605 | 20,095 | A selection of Wikipedia articles on sociology |
| `wikipedia_en_tennis_maxi_2026-07` | maxi | 2026-07-14 | 0.48 | 108,379 | 11,110 | 45,700 | A selection of Wikipedia articles on tennis |
| `wikipedia_en_tennis_nopic_2026-07` | nopic | 2026-07-14 | 0.37 | 108,379 | 119 | 45,700 | A selection of Wikipedia articles on tennis |

Download URL pattern: `https://download.kiwix.org/zim/wikipedia/<book>.zim` (metalink: same path + `.meta4`, the OPDS acquisition link uses `lb.download.kiwix.org`). Full per-entry data (incl. raw Counter strings and metalink URLs) is in `wikipedia_variants.json`.

## Older builds still on the mirror (what NOMAD/our box actually has)

| book | size (Content-Length bytes) | dirents | pages (Counter text/html) | note |
|---|---:|---:|---:|---|
| `wikipedia_en_all_maxi_2026-02` | 123,980,647,016 | 27,199,921 | 8,425,786 | **the build installed on Nitin's box and being indexed** (124.0 GB, per Main's briefing); Counter text/html matches the maintainer figure 8,425,786 exactly |
| `wikipedia_en_all_nopic_2026-03` | 51,927,559,581 | 19,551,522 | 8,452,796 | same text as maxi, no images |
| `wikipedia_en_all_mini_2026-06` | 12,531,679,311 | 19,217,348 | 8,513,331 | intro+infobox, one page per article |
| `wikipedia_en-simple_all_maxi_2026-06` | n/a | 732,532 | 287,465 |  |

## Other large English Kiwix libraries relevant to a knowledge server (catalog sizes)

| library | variant | updated | size GB | articleCount (OPDS) | mediaCount (OPDS) |
|---|---|---|---:|---:|---:|
| `stackoverflow.com_en_all` | - | 2026-07-02 | 114.86 | 30,594,570 | 4,082,223 |
| `math.stackexchange.com_en_all` | - | 2026-08-04 | 7.42 | 2,087,321 | 238,764 |
| `gutenberg_en_all` | - | 2025-11-25 | 221.25 | 80,656 | 1,275,468 |
| `wikisource_en_all` | maxi | 2026-09-08 | 8.62 | 857,535 | 222,489 |
| `wikisource_en_all` | nopic | 2026-09-08 | 3.91 | 857,535 | 12,306 |
| `wiktionary_en_all` | nopic | 2026-08-13 | 9.16 | 9,129,949 | 15 |
| `wikibooks_en_all` | maxi | 2026-04-27 | 6.18 | 118,571 | 266,325 |
| `wikibooks_en_all` | nopic | 2026-04-27 | 3.51 | 118,571 | 142,451 |
| `wikiversity_en_all` | maxi | 2026-05-06 | 2.46 | 69,848 | 145,506 |
| `wikiversity_en_all` | nopic | 2026-08-04 | 1.63 | 69,476 | 80,660 |
| `wikivoyage_en_all` | maxi | 2026-09-13 | 1.07 | 68,182 | 90,778 |
| `wikiquote_en_all` | maxi | 2026-07-16 | 0.97 | 102,400 | 64,142 |

All English Stack Exchange ZIMs together: 164 sites, 184.8 GB (Stack Overflow alone 114.9 GB; the other 163 sites 70.0 GB), 43,717,079 `articleCount` (same redirect caveat; Stack Exchange ZIMs have few redirects [inference]). Source: <https://library.kiwix.org/catalog/v2/entries?count=500&lang=eng&category=stack_exchange>. Project Gutenberg English: `gutenberg_en_all` 221.3 GB, 80,656 books (<https://library.kiwix.org/catalog/v2/entries?count=500&lang=eng&category=gutenberg>).

## What this means for NOMAD (inference, flagged)

- [inference] NOMAD embeds `text/html` pages only, so work = `pages (Counter text/html)`, not `articleCount`. For the installed file that is 8,425,786 pages, not 18,982,214.
- [inference] `nopic` gives the identical article text as `maxi` (same index size) at 42% of the download; only `mini` and the `top*`/topical packs actually shrink the index. A `mini` index would hold roughly one lead-section chunk per page ([inference]; measure before relying on it).
- Variant page counts are build-dependent (see Counter columns); re-measure before downloading a different build.

## Method / reproducibility

- Catalog: `curl -L 'https://library.kiwix.org/catalog/v2/entries?lang=eng&q=wikipedia&count=200'` (65 entries). Directory listing: `https://download.kiwix.org/zim/wikipedia/`.
- Counter: parse ZIM header (80 bytes), binary-search the URL pointer table for `M/Counter` by HTTP range reads (~28-52 requests, 16-216 KB of cluster data per file), decompress the zstd cluster, read the blob. Script kept at `raw/zim_counter.py`; raw results `raw/zim_counters.json`.
