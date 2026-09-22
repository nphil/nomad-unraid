# nomad-unraid: notes for agents

Packaging only; NOMAD itself (Crosstalk-Solutions/project-nomad) is never modified.
Read README.md for the design. Traps that already cost a debugging round:

- **The compose project must be named `project-nomad`.** NOMAD hard-codes the network
  `project-nomad_default` for every app it creates, and the admin container must be named
  `nomad_admin` (it finds its own mounts by that name).
- **Never `docker stop` NOMAD's app containers on shutdown.** Docker then records them as
  deliberately stopped and `unless-stopped` will not restart them. The entrypoint lets the
  private daemon stop everything (`--shutdown-timeout=60`) instead.
- **NOMAD resets its app catalogue on every boot** (`ServiceSeeder`), except rows marked
  `is_user_modified`. Sub-path settings are therefore re-applied by `reconcile` on start and
  every 10 minutes rather than written once. `is_user_modified` is deliberately not used,
  so catalogue fixes from upstream still arrive.
- **`/apps` belongs to NOMAD** (it redirects to the Supply Depot); app paths must avoid it
  and NOMAD's other top-level routes.
- **Caddy runs `handle` before `respond`**, so anything answered directly needs its own
  `handle` block, or the catch-all proxy to NOMAD swallows it.
- **Alpine's BusyBox `sed` has no `-u`**; GNU `sed` is installed for line-buffered log prefixes.
- The dind entrypoint only adds its unauthenticated `tcp://0.0.0.0:2375` listener when it
  gets no arguments or only flags. We always pass `dockerd ...` explicitly; keep it that way.
- **With `AI_URL`, Qdrant must be online before the AI server is saved.** NOMAD installs
  Qdrant only alongside its own Ollama, and indexes its own docs exactly once, when the AI
  server is saved; jobs that fail then are never retried. Reconcile installs Qdrant, waits
  for `/api/rag/health`, and only then saves the URL.
- Test an image on a real host before pushing: a push to `main` touching the image
  publishes a release.

Deployed on Nitin's beastnas (Unraid) as container `Nomad`, documented in the homelabber
repo's seed doc `project-nomad`.
