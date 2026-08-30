#!/bin/bash
# Runs once on container start, before supervisord takes over the foreground.
#
# IMPORTANT -- persistence: Railway containers are ephemeral. A Volume MUST be mounted at
# $BENCH_PATH/sites (i.e. /home/frappe/bench/sites) or every redeploy looks like a "fresh"
# bench with no site_config.json, and this script will try to `bench new-site` again against
# a database that (via Railway's managed MySQL, which *does* persist independently) may
# already have that site's tables in it -- new-site would fail outright, and even if it
# didn't, a freshly-generated encryption_key would silently break every existing encrypted
# field (Password-type fields: R2 secret key, WhatsApp access token, etc.) since the DB rows
# stay encrypted under the *old* key. The volume is what keeps site_config.json (and its
# encryption_key) stable across deploys while the DB itself lives in Railway's MySQL plugin.
set -euo pipefail

: "${SITE_NAME:?SITE_NAME env var is required, e.g. agency-tracking.railway.internal}"
: "${DB_HOST:?DB_HOST env var is required - point this at the MySQL/MariaDB plugin}"
: "${DB_PORT:=3306}"
: "${DB_NAME:?DB_NAME env var is required}"
: "${DB_USER:?DB_USER env var is required}"
: "${DB_PASSWORD:?DB_PASSWORD env var is required}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD env var is required (Administrator login on first boot)}"

# `: "${X:=default}"` only sets a shell variable, it does NOT export it -- supervisord.conf's
# %(ENV_PORT)s / %(ENV_GUNICORN_WORKERS)s interpolation needs these in the actual process
# environment it inherits from this script's `exec`, so export explicitly.
export PORT="${PORT:-8000}"
export GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"

cd "$BENCH_PATH"

echo "Waiting for MariaDB at ${DB_HOST}:${DB_PORT}..."
until mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null; do
  sleep 2
done
echo "MariaDB is up."

# common_site_config.json: local Redis (started by supervisord alongside this entrypoint),
# and Railway's dynamically-assigned $PORT for the webserver.
bench set-config -g redis_cache "redis://127.0.0.1:6379"
bench set-config -g redis_queue "redis://127.0.0.1:6379"
bench set-config -g redis_socketio "redis://127.0.0.1:6379"
bench set-config -g webserver_port "$PORT"
bench set-config -g serve_default_site true

if [ ! -f "sites/${SITE_NAME}/site_config.json" ]; then
  echo "No existing site_config.json for ${SITE_NAME} -- creating a new site."
  echo "(If this is meant to be a redeploy of an existing site, the sites/ Volume isn't mounted correctly.)"
  bench new-site "$SITE_NAME" \
    --db-type mariadb \
    --db-host "$DB_HOST" \
    --db-port "$DB_PORT" \
    --db-name "$DB_NAME" \
    --db-root-username "$DB_USER" \
    --db-root-password "$DB_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD" \
    --no-mariadb-socket \
    --install-app agency_tracking \
    --set-default
else
  echo "Existing site_config.json found for ${SITE_NAME} -- migrating."
  bench --site "$SITE_NAME" migrate
fi

exec "$@"
