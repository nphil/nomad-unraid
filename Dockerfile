# Project NOMAD as one portable container.
#
# NOMAD is built to run as several containers and to create more (one per app) through
# the Docker socket. This image gives it a private Docker daemon of its own, so all of
# that happens inside this one container: the host sees a single app, one port, and
# NOMAD itself runs unmodified.
FROM docker:29-dind

LABEL org.opencontainers.image.source="https://github.com/nphil/nomad-unraid" \
      org.opencontainers.image.description="Project NOMAD as a single, portable Unraid app" \
      org.opencontainers.image.licenses="Apache-2.0"

ARG NOMAD_VERSION
ENV NOMAD_VERSION=${NOMAD_VERSION}

RUN apk add --no-cache bash curl jq caddy tini gettext sed

COPY rootfs/ /
RUN chmod +x /usr/local/bin/*

# /config          small state: MySQL, Redis, secrets, Caddy data  (fast disk)
# /data            NOMAD content: ZIMs, maps, uploads              (big disk)
# /var/lib/docker  the private daemon's images and containers      (fast disk, no snapshots)
VOLUME ["/config", "/data", "/var/lib/docker"]
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
  CMD curl -fsS http://127.0.0.1:18080/api/health >/dev/null && curl -fsS http://127.0.0.1/.nomad-unraid/ok >/dev/null || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/nomad-entrypoint"]
