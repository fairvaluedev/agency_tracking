# Headless agency_tracking backend (Frappe v15), containerized for Railway.
#
# Single-container deployment: gunicorn (web), an RQ worker, the Frappe scheduler, and a
# local Redis instance are all run together under supervisord -- the simplest thing that
# actually works for a single Railway service. MariaDB is NOT bundled -- point this at
# Railway's own MySQL/MariaDB plugin via the DB_* environment variables (see entrypoint.sh).
#
# Self-contained: build context is this app's own directory (docker build -t agency-tracking .
# from inside apps/agency_tracking/) -- nothing from the rest of the bench is needed, since
# the Frappe framework itself is cloned fresh from GitHub below rather than copied locally.

FROM python:3.12-slim-bookworm AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    BENCH_PATH=/home/frappe/bench

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl wget gnupg build-essential pkg-config \
        python3-dev default-libmysqlclient-dev \
        libssl-dev libffi-dev libjpeg62-turbo-dev zlib1g-dev libwebp-dev \
        mariadb-client redis-server \
        wkhtmltopdf xfonts-75dpi xfonts-base \
        tesseract-ocr \
        supervisor cron \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g yarn \
    && pip install --no-cache-dir frappe-bench \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -ms /bin/bash frappe
USER frappe
WORKDIR /home/frappe

# --- Bench + framework -------------------------------------------------------
# Cloned fresh from GitHub at build time (pinned to the same version-15 line this app was
# built against, see apps/frappe/frappe/__init__.py's __version__ = 15.x in the source repo)
# rather than COPYing the local checkout -- keeps the build context small and avoids baking
# in any local-only dev artifacts.
RUN bench init --skip-redis-config-generation --frappe-branch version-15 ${BENCH_PATH}

WORKDIR ${BENCH_PATH}

# --- agency_tracking app ------------------------------------------------------
# The build context root *is* this app's source (see the note at the top of this file) --
# copied wholesale into the bench's apps/ directory, same place `bench get-app` would put it.
COPY --chown=frappe:frappe . apps/agency_tracking
# `bench init`'s freshly-generated sites/apps.txt has no trailing newline after "frappe" --
# a bare `echo ... >> apps.txt` glues straight onto that line, producing a single malformed
# entry ("frappeagency_tracking") that then fails to import. printf guarantees the leading
# newline that separates them.
RUN ./env/bin/pip install --no-cache-dir -e apps/agency_tracking \
    && printf '\n%s\n' agency_tracking >> sites/apps.txt

# --- Frontend assets (agency_tracking's own bundled React SPA + Frappe's desk assets) -------
RUN bench build --app agency_tracking

# --- Preserve the fully-initialized sites/ (apps.txt, common_site_config.json, built assets)
# outside the mount path. A Railway Volume mounted at $BENCH_PATH/sites (required for
# site_config.json/encryption_key to survive redeploys, see entrypoint.sh) *replaces* whatever
# was baked into the image at that path with the volume's own -- empty, on first attach --
# content, silently deleting apps.txt and everything else built above. entrypoint.sh restores
# from this backup into the empty volume on first boot.
RUN cp -r sites /home/frappe/sites-init

# --- Runtime plumbing ---------------------------------------------------------
USER root
COPY --chown=frappe:frappe docker/entrypoint.sh /entrypoint.sh
COPY docker/supervisord.conf /etc/supervisor/supervisord.conf
RUN chmod +x /entrypoint.sh \
    && mkdir -p /var/log/supervisor && chown frappe:frappe /var/log/supervisor

USER frappe
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
