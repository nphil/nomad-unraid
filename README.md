<p align="center"><img src="assets/icon.png" width="112" alt=""></p>

<h1 align="center">NOMAD for Unraid</h1>

<p align="center"><a href="https://www.projectnomad.us">Project NOMAD</a>, the offline knowledge and education server, as <b>one container</b>.</p>

NOMAD is built to run as five containers and to create one more for every app you install
(Kiwix, Kolibri, notes, ...). This image gives it a private Docker daemon, so all of that
happens inside a single container. Your server sees one app, one port and one update button,
and NOMAD itself runs completely unmodified.

- **One container.** NOMAD, its database, and every app it installs live inside it.
- **One address.** Apps open under paths of your NOMAD address instead of extra ports:
  `/wiki/`, `/learn/`, `/notes/`, `/cyberchef/`. Works behind any reverse proxy.
- **Normal updates.** Each image is pinned to a NOMAD release and tagged with its version.
  A new NOMAD release becomes a new image within about six hours, so Unraid shows
  *update available* and the release notes come along. The apps inside update themselves
  overnight in a window you choose.
- **Portable.** Everything is in three folders. Copy them to another machine, run the same
  image, and it comes up as it was.
- **Bring your own AI.** Point it at any OpenAI-compatible server (llama-swap, LM Studio,
  Ollama elsewhere) instead of running Ollama inside.

## Install

**Unraid:** Docker → Add Container → Template URL
`https://raw.githubusercontent.com/nphil/nomad-unraid/main/unraid/nomad.xml`, then fill in
the paths and your public URL.

**Anywhere else:**

```bash
docker run -d --name nomad --privileged --stop-timeout 120 -p 8085:80 \
  -v /fast/nomad:/config \
  -v /fast/nomad-docker:/var/lib/docker \
  -v /big/nomad:/data \
  -e PUBLIC_URL=https://knowledge.example.com \
  -e AI_URL=http://192.168.1.10:9292 \
  ghcr.io/nphil/nomad-unraid:latest
```

| Mount | Holds | Put it on |
| --- | --- | --- |
| `/config` | Database, settings, generated secrets | Fast disk; back it up |
| `/var/lib/docker` | The private daemon's images and containers | Fast disk; rebuildable, leave it out of snapshots and backups |
| `/data` | ZIM libraries, maps, courses, uploads | Big disk; tens to hundreds of GB |
| `/data/qdrant` | The search index (Qdrant), about 20 GiB per few million chunks | **A real disk or pool path, never `/mnt/user`** (see [the incident](docs/qdrant-storage-and-recovery.md)); without its own mount it lands inside `/data` |

| Variable | Default | What it does |
| --- | --- | --- |
| `PUBLIC_URL` | `http://localhost` | The address you open NOMAD at. App links are built from it. |
| `AI_URL` | *(empty)* | An OpenAI-compatible server, base URL without `/v1`. Empty means NOMAD's own AI setup. |
| `UPDATE_WINDOW` | `03:00-05:00` | When installed apps may update themselves, local time. |
| `EMBED_WINDOW` | `02:00-05:00` | When NOMAD may index knowledge-base libraries on the AI server, local time. `always` turns the limit off. See [Batch indexing](#batch-indexing). |
| `TZ` | `UTC` | Time zone, which both windows use. |
| `QDRANT_CPUSET` | *(empty)* | CPUs the search database (Qdrant) may use, e.g. `0-4,8-12`, so indexing leaves the rest of the host alone. Re-applied every minute. |
| `QDRANT_NICE` | *(empty)* | Lowers Qdrant's CPU priority (1 to 19; `10` is a good value). Re-applied every minute, because a restart resets it. |
| `MIN_CHUNK_CHARS` | `21` | Skips ZIM chunks shorter than this that carry nothing (a number, a tail fragment, or only the page title) instead of embedding them. `0` turns it off. See [Skipping scrap chunks](#skipping-scrap-chunks-min_chunk_chars). |

`--privileged` is required: the private Docker daemon needs it. For comparison, NOMAD's
normal install hands the admin container the host's Docker socket, which is the same
level of trust.

## Apps under a path

[`rootfs/etc/nomad/apps.json`](rootfs/etc/nomad/apps.json) lists which apps get a path and
how. Each app's own sub-path setting is applied to NOMAD's catalogue and re-applied every
ten minutes, because NOMAD resets its catalogue when it boots. An installed app found
without its setting is reinstalled; its data lives in `/data` and is kept.

| App | Path | Notes |
| --- | --- | --- |
| Kiwix (Information Library) | `/wiki/` | |
| Kolibri (Education Platform) | `/learn/` | Lesson files are served from `/learn-content/`, see below |
| FlatNotes (Notes) | `/notes/` | |
| CyberChef (Data Tools) | `/cyberchef/` | |

Not supported, because they cannot run under a sub-path: **IT Tools**, **Excalidraw** and
**Homebox** (hard-coded root paths). Any other catalogue app still installs and works on
its own port, but that port is only reachable inside the container.

**Kolibri's lesson files.** Kolibri sandboxes lesson content by loading it from a second
web origin, which by default is the same host on port 8311. Behind one address that port is
unreachable, so here the content is served from `/learn-content/` on the main address
instead. That keeps everything on one hostname, at the cost of the extra isolation a
separate origin gives. The official Kolibri channels are the intended content.

## AI and knowledge-base search

With `AI_URL` set, NOMAD uses that server for chat, and it never installs Ollama. NOMAD's
knowledge-base search needs the embedding model **`nomic-embed-text:v1.5`** by that name
(its index is built for that model's 768 dimensions), so the server has to provide it. For
llama-swap:

```yaml
  nomic-embed-text-v1.5:
    cmd: |
      llama-server --host 127.0.0.1 --port ${PORT}
      -m /models/nomic-embed-text-v1.5.Q8_0.gguf
      --embedding --pooling mean -ngl 999 -c 2048 -b 2048 -ub 2048
    aliases: ["nomic-embed-text:v1.5"]
```

On a GPU it takes about 400 MB of VRAM. With `-ngl 0` it runs on the CPU instead, which is
fine for searching (about 45 ms a query) but about 20 times slower to index a library;
it does not save host RAM either way.

Qdrant, NOMAD's vector database, is normally installed only together with its own
Ollama, so with `AI_URL` set this image installs it and runs one indexing pass. NOMAD's
ingest policy (*Always*, or *Manual* in the knowledge-base panel) then decides whether new
ZIM libraries are indexed automatically. A full Wikipedia is far more work than a night
can hold (see below), so *Manual* is worth considering before downloading one.

### Batch indexing

NOMAD indexes a ZIM library as an endless chain of small jobs: 50 articles per job, the
next job queued the moment one finishes. Left alone that keeps the AI server's GPU busy
day and night for as long as there is something left to index. This image therefore
pauses NOMAD's indexing queue (`file-embeddings`) outside `EMBED_WINDOW` and resumes it
inside, by default 02:00 to 05:00 in `TZ`. A batch that is running when the window closes
finishes, then indexing stops until the next window and carries on from the same article.
Knowledge-base **search is not affected**: a query is embedded on the spot and never waits
in the queue. Only new content waits for the window, and that includes a document you
upload, until the next window or until you ask for it (below).

`EMBED_WINDOW` is `HH:MM-HH:MM` in local time and may cross midnight (`22:00-02:00`); the
start is included and the end is not. `always` disables the limit. A value that cannot be
read is logged and replaced by the default. The state is decided on every start, so a
restart never leaves indexing paused for good.

`nomad-embed` is the tool for the rest. Run it as `docker exec Nomad nomad-embed ...`.

| Command | What it does |
| --- | --- |
| `status` | Paused or running, job counts, progress per library, parked libraries, Qdrant point count. |
| `now [MINUTES]` | Index outside the window for a while (default 60). `now off` ends it. The way to index an uploaded document right away. |
| `pause`, `resume` | One-off switch for the queue. The gate puts it back as the window says within a minute, unless `EMBED_WINDOW=always`. Use `now` to stay open. |
| `dedupe [--apply]` | Dry run by default. Per library, keeps the waiting job that is furthest along and drops the others. Never touches a running job. |
| `exclude NAME [--apply]` | Dry run by default. Takes a library's waiting jobs out of the queue and remembers where it stopped. A running job queues its next batch when it ends, so run it again afterwards. |
| `include NAME` | Puts a parked library back in the queue, continuing from the article it stopped at. |

Duplicate chains can appear when a job stalls and the retry and the original both go on:
two chains then index the same articles, and every pass writes the same text into Qdrant
again under a new id. `dedupe` stops that; points already written twice stay.

**Scale.** The English Wikipedia (`wikipedia_en_all_maxi`) is 124 GB with about 8.4 million
real pages, but NOMAD counts 18.98 million entries because redirects are included, so its
progress bar would stall near 44%. NOMAD's job chain re-opens the 124 GB file for every
50-article job (about 100 seconds) and walks it again from the start, so on beastnas a
whole Wikipedia cannot finish this way: indexing ran at roughly 2 chunks a second, and a
3-hour window fits about 40 jobs, around 2,000 articles a night. Qdrant needs about 5.4 KB
per chunk. All the other libraries together come to about 5 million chunks and 30 GB,
which is a matter of weeks of nights. Keep the full Wikipedia out: choose *Manual* ingest,
or `nomad-embed exclude wikipedia_en_all_maxi`.

**Reset & Rebuild.** The knowledge-base panel's *Reset & Rebuild* button drops the whole
collection and queues every file again, including the full Wikipedia. Run
`nomad-embed exclude wikipedia_en_all_maxi --apply` right after pressing it (the queue is
paused outside the window, so nothing starts before you can).

A job that is running when the window closes finishes its batch first, which can take
many minutes while Qdrant is busy, and NOMAD fails any job that runs over 30 minutes.

**Known limitation with llama.cpp-based servers.** NOMAD cuts text into chunks by
JavaScript string length, which can split an emoji in half. The half is invalid JSON, and
llama.cpp's strict parser rejects that batch (Ollama tolerates it). The affected file shows
as failed in the knowledge-base panel; everything else indexes normally. On beastnas this
hit 1 of NOMAD's 13 help docs (its release notes, which are full of emoji). It is a NOMAD
bug and belongs upstream.

## Patches to NOMAD

NOMAD itself is meant to run completely unmodified (see above), with two narrow exceptions.
The first is a bug fix.
With `AI_URL` pointed at a non-Ollama server (llama-swap, LM Studio, vLLM, ...), NOMAD's
admin container calls `POST /api/embed` before every single knowledge-base embedding and
only falls back to the OpenAI-compatible `/v1/embeddings` after that 404s. Against a real
Ollama this costs nothing; against everything else it is a guaranteed-failing request plus
a warn log line on every embedding, for the life of the process.

Fixed upstream ("ai: don't probe the native embed endpoint on a non-Ollama backend", closes
[crosstalk-solutions/project-nomad#1279][1279]) but only in the `v1.35.0-rc` pre-release
channel so far. [`build.yml`](.github/workflows/build.yml) only ever builds
`releases/latest`, which never resolves to a pre-release, so this image can't pick the fix
up on its own until Crosstalk Solutions cuts a stable release that includes it.

Until then, [`nomad-entrypoint`](rootfs/usr/local/bin/nomad-entrypoint) carries the same
fix as a small, self-checking text patch to `nomad_admin`'s `ollama_service.js`
(`patch_embed_fallback`, applied right after the stack comes up on every start): it makes
`_embedWithFallback` skip the native probe once this backend is known not to answer it, and
remembers that after the first 404. The patch matches on the exact original code and
touches nothing else; if a future NOMAD release changes that function, including by
fixing #1279 itself, the patch logs one line and leaves the file alone rather than
risk corrupting code it no longer recognises. At that point `patch_embed_fallback`
and its call in `nomad-entrypoint` can simply be deleted.

[1279]: https://github.com/Crosstalk-Solutions/project-nomad/issues/1279

### Skipping scrap chunks (`MIN_CHUNK_CHARS`)

The second patch is an ingest filter, not a bug fix. NOMAD embeds every chunk the ZIM
extractor yields, however tiny. On a four-million-chunk index 16 % of the points were 20
characters or fewer: the vote and answer counts of StackExchange tag pages (`11 1`), tail
fragments of longer texts (`media files.`), and stubs whose text is only the page title
(`1633 deaths`). Each cost a GPU embedding, none ever answers a question, and a number or a
title has no meaning on its own in the search.

`patch_min_chunk` in `nomad-entrypoint` (a self-checking text patch to `nomad_admin`'s
`rag_service.js`, same safety rules as above) skips such a chunk before it is embedded. It
skips a ZIM chunk only when its text is shorter than `MIN_CHUNK_CHARS` (default `21`, so 20
characters or fewer) **and** it is number-only or empty, or is a tail of a longer text (not
the first chunk), or equals the article or section title. Short real text stays, for
example a drug's brand name under a "Brand names" heading. Uploads and NOMAD's own docs are
never filtered. `MIN_CHUNK_CHARS=0` switches the filter off.

The filter only affects new indexing. To clear an index that already has such chunks, use
[`tools/repair/scrap_plan.py`](tools/repair/scrap_plan.py) (lists what the same rules would
remove) and [`scrap_delete.py`](tools/repair/scrap_delete.py), after a snapshot of the
Qdrant dataset.

## Updates

| What | How |
| --- | --- |
| NOMAD itself | A new image per NOMAD release (tag `1.34.1`, plus `latest`). Update the container as usual. NOMAD's own self-updater is switched off, so the two never compete. |
| Packaging changes | Rebuild of the same NOMAD version, tagged as a revision (`1.34.1-r2`). |
| Apps inside NOMAD | NOMAD's app auto-update, inside `UPDATE_WINDOW`. |

Every build publishes a [GitHub Release](../../releases) with NOMAD's release notes.

## How it works

On start, [`nomad-entrypoint`](rootfs/usr/local/bin/nomad-entrypoint) starts the private
daemon, renders upstream's compose file pinned to this image's NOMAD version, brings the
stack up, and starts a Caddy proxy on port 80 that sends each app path to its app and
everything else to NOMAD. On stop, it lets the daemon stop every container itself, so they
all come back on the next start.

## Credits

[Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) is by Crosstalk
Solutions under the Apache 2.0 license, and the icon is NOMAD's own. This repository only
packages it and is not affiliated with Crosstalk Solutions.
