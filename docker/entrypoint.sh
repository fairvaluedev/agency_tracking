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
# Frappe site names are a bare hostname -- strip an accidentally-pasted URL scheme (a very
# easy mistake when copying the value straight out of Railway's own public-domain field)
# rather than crash-looping on it.
SITE_NAME="${SITE_NAME#http://}"
SITE_NAME="${SITE_NAME#https://}"
SITE_NAME="${SITE_NAME%%/*}"
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

# A Railway Volume mounted at sites/ shadows everything the image baked in there at build
# time (apps.txt, common_site_config.json, built frontend assets) with the volume's own --
# empty, on first attach -- content. Restore from the build-time backup before doing
# anything else, or every bench/frappe command below fails with "apps.txt Not Found".
if [ ! -f "sites/apps.txt" ]; then
  echo "Empty sites/ volume detected -- seeding it from the image's build-time bench init."
  cp -rn /home/frappe/sites-init/. sites/
fi

# This whole script runs as root (needed to write into a freshly-mounted, root-owned Railway
# Volume at all -- see the note above). `bench` itself auto-drops from root to whatever
# common_site_config.json's frappe_user says (set to "frappe" during the image's build-time
# `bench init`, since that ran as the frappe user) for every command below -- but that only
# works if the files it's dropping privileges *to write* are actually owned by that user.
# The `cp` above (plain shell, not routed through bench) just created everything as root.
chown -R frappe:frappe sites

echo "Waiting for MariaDB at ${DB_HOST}:${DB_PORT}..."
until mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null; do
  sleep 2
done
echo "MariaDB is up."

# Self-heal the site's DB user host-scope on EVERY boot, unconditionally -- don't just rely
# on --mariadb-user-host-login-scope being right the one time new-site ran. Railway containers
# get a new internal IP on every redeploy; if this site's user was ever created (by this
# script before this fix existed, by a manual bench new-site, by literally anything) without
# a wildcard host, it silently breaks on the next redeploy with "Access denied" -- and no
# amount of resetting volumes/DB names fixes that, since it's a row in MariaDB's own mysql.user
# table, not anything living in the site's own files. Fix the actual row instead.
if [ -f "sites/${SITE_NAME}/site_config.json" ]; then
  SITE_DB_USER=$(python3 -c "import json; print(json.load(open('sites/${SITE_NAME}/site_config.json')).get('db_name', ''))")
  if [ -n "$SITE_DB_USER" ]; then
    STALE_HOSTS=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -N -B \
      -e "SELECT host FROM mysql.user WHERE user = '${SITE_DB_USER}' AND host != '%';" 2>/dev/null || true)
    if [ -n "$STALE_HOSTS" ]; then
      echo "Found ${SITE_DB_USER}@ scoped to a non-wildcard host -- widening to '%' so redeploys with a new container IP don't break auth again."
      while IFS= read -r stale_host; do
        [ -z "$stale_host" ] && continue
        # RENAME USER preserves the existing password as-is, just widens which host it's
        # allowed to connect from. If a '%' entry already exists (e.g. a previous boot
        # partially applied this fix), the rename fails harmlessly -- ignore and move on,
        # then drop the now-redundant stale-host row so it doesn't linger forever.
        if ! mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
             -e "RENAME USER '${SITE_DB_USER}'@'${stale_host}' TO '${SITE_DB_USER}'@'%';" 2>/dev/null; then
          mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
            -e "DROP USER IF EXISTS '${SITE_DB_USER}'@'${stale_host}';" 2>/dev/null || true
        fi
      done <<< "$STALE_HOSTS"
      mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -e "GRANT ALL PRIVILEGES ON \`${SITE_DB_USER}\`.* TO '${SITE_DB_USER}'@'%'; FLUSH PRIVILEGES;" 2>/dev/null || true
    fi
  fi
fi

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
  # --mariadb-user-host-login-scope '%': without this, DbManager.create_user() (frappe/
  # database/db_manager.py) scopes the new site DB user to whatever IP the container happens
  # to have *at this exact moment* -- Railway containers get a fresh internal IP on every
  # redeploy, so the very next boot would get "Access denied" against its own site's database.
  bench new-site "$SITE_NAME" \
    --db-type mariadb \
    --db-host "$DB_HOST" \
    --db-port "$DB_PORT" \
    --db-name "$DB_NAME" \
    --db-root-username "$DB_USER" \
    --db-root-password "$DB_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD" \
    --mariadb-user-host-login-scope '%' \
    --no-mariadb-socket \
    --install-app agency_tracking \
    --set-default
else
  echo "Existing site_config.json found for ${SITE_NAME} -- migrating."
  bench --site "$SITE_NAME" migrate
fi

exec "$@"
