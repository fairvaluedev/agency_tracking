#!/bin/bash
# Runs once on container start, before supervisord takes over the foreground.
#
# IMPORTANT -- persistence: Railway containers are ephemeral. A Volume SHOULD be mounted at
# $BENCH_PATH/sites (i.e. /home/frappe/bench/sites) so site_config.json (and its encryption_key)
# persists across redeploys.
set -euo pipefail

echo "==> Starting Agency Tracking initialization..."

# -----------------------------------------------------------------------------
# 1. Environment Variable Auto-Discovery & Normalization
# -----------------------------------------------------------------------------

# Parse DATABASE_URL / MYSQL_URL if provided and individual DB vars are missing
DATABASE_CONN_URL="${DATABASE_URL:-${MYSQL_URL:-}}"
if [ -n "$DATABASE_CONN_URL" ] && [ -z "${DB_HOST:-}" ]; then
  echo "Found database connection URL, parsing parameters..."
  # Format: mysql://user:pass@host:port/dbname or mariadb://...
  PROTO="$(echo "$DATABASE_CONN_URL" | sed -e's,^\(.*://\).*,\1,g')"
  URL_NOPROTO="${DATABASE_CONN_URL#"$PROTO"}"
  USER_PASS="$(echo "$URL_NOPROTO" | grep @ | cut -d@ -f1 || true)"
  HOST_PORT_DB="${URL_NOPROTO#"$USER_PASS"}"
  HOST_PORT_DB="${HOST_PORT_DB#@}"
  
  if [ -n "$USER_PASS" ]; then
    DB_USER="${DB_USER:-$(echo "$USER_PASS" | cut -d: -f1)}"
    DB_PASSWORD="${DB_PASSWORD:-$(echo "$USER_PASS" | cut -d: -f2-)}"
  fi
  
  HOST_PORT="$(echo "$HOST_PORT_DB" | cut -d/ -f1)"
  DB_NAME="${DB_NAME:-$(echo "$HOST_PORT_DB" | cut -d/ -f2- | cut -d? -f1)}"
  DB_HOST="${DB_HOST:-$(echo "$HOST_PORT" | cut -d: -f1)}"
  if [[ "$HOST_PORT" == *:* ]]; then
    DB_PORT="${DB_PORT:-$(echo "$HOST_PORT" | cut -d: -f2)}"
  fi
fi

# Auto-detect standard Railway MySQL / MariaDB environment variables
DB_HOST="${DB_HOST:-${MYSQLHOST:-${MARIADB_HOST:-${MYSQL_HOST:-}}}}"
DB_PORT="${DB_PORT:-${MYSQLPORT:-${MARIADB_PORT:-${MYSQL_PORT:-3306}}}}"
DB_USER="${DB_USER:-${MYSQLUSER:-${MARIADB_USER:-${MYSQL_USER:-root}}}}"
DB_PASSWORD="${DB_PASSWORD:-${MYSQLPASSWORD:-${MARIADB_PASSWORD:-${MYSQL_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}}}}"
DB_NAME="${DB_NAME:-${MYSQLDATABASE:-${MARIADB_DATABASE:-${MYSQL_DATABASE:-agency_tracking}}}}"

# Auto-detect Site Name from Railway public domain or default
SITE_NAME="${SITE_NAME:-${RAILWAY_PUBLIC_DOMAIN:-${RAILWAY_STATIC_URL:-agency-tracking.local}}}"
SITE_NAME="${SITE_NAME#http://}"
SITE_NAME="${SITE_NAME#https://}"
SITE_NAME="${SITE_NAME%%/*}"

# Administrator password
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"

export PORT="${PORT:-8000}"
export GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"

echo "Site Name   : $SITE_NAME"
echo "Database    : $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
echo "HTTP Port   : $PORT"
echo "Workers     : $GUNICORN_WORKERS"

if [ -z "$DB_HOST" ]; then
  echo "ERROR: DB_HOST (or MYSQLHOST / MYSQL_URL) is not set. Please provision/link a MySQL service in Railway." >&2
  exit 1
fi

cd "$BENCH_PATH"

# -----------------------------------------------------------------------------
# 2. Volume & Sites Template Restoration
# -----------------------------------------------------------------------------

# When a volume is mounted at sites/, initialize any missing files from build-time template
if [ ! -f "sites/apps.txt" ]; then
  echo "Empty or incomplete sites/ directory detected -- seeding from build-time template..."
  cp -a /home/frappe/sites-init/. sites/
fi

# Guarantee apps.txt contains both frappe and agency_tracking
if ! grep -q "^agency_tracking$" sites/apps.txt 2>/dev/null; then
  echo "agency_tracking" >> sites/apps.txt
fi

# Restore built assets if missing
if [ ! -d "sites/assets" ] && [ -d "/home/frappe/sites-init/assets" ]; then
  cp -a /home/frappe/sites-init/assets sites/
fi

chown -R frappe:frappe sites

# -----------------------------------------------------------------------------
# 3. Wait for Database
# -----------------------------------------------------------------------------

echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
MAX_RETRIES=60
RETRY_COUNT=0
until mysqladmin ping -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" --silent 2>/dev/null || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  sleep 2
  RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "ERROR: Could not connect to database at ${DB_HOST}:${DB_PORT} after ${MAX_RETRIES} attempts." >&2
  exit 1
fi
echo "Database is reachable."

# -----------------------------------------------------------------------------
# 4. Global Bench Configuration
# -----------------------------------------------------------------------------

bench set-config -g redis_cache "redis://127.0.0.1:6379"
bench set-config -g redis_queue "redis://127.0.0.1:6379"
bench set-config -g redis_socketio "redis://127.0.0.1:6379"
bench set-config -g webserver_port "$PORT"
bench set-config -g serve_default_site true

# -----------------------------------------------------------------------------
# 5. Site Provisioning or Migration
# -----------------------------------------------------------------------------

if [ ! -f "sites/${SITE_NAME}/site_config.json" ]; then
  echo "No existing site_config.json found for ${SITE_NAME} -- creating new site..."
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
    --force \
    --set-default
else
  echo "Existing site_config.json found for ${SITE_NAME} -- running migrations..."
  bench --site "$SITE_NAME" migrate
  bench use "$SITE_NAME"
fi

# Ensure permissions on sites directory
chown -R frappe:frappe sites

# -----------------------------------------------------------------------------
# 6. Self-heal DB user host scope if needed
# -----------------------------------------------------------------------------

if [ -f "sites/${SITE_NAME}/site_config.json" ]; then
  SITE_DB_USER=$(python3 -c "import json; print(json.load(open('sites/${SITE_NAME}/site_config.json')).get('db_name', ''))" 2>/dev/null || true)
  if [ -n "$SITE_DB_USER" ]; then
    STALE_HOSTS=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" -N -B \
      -e "SELECT host FROM mysql.user WHERE user = '${SITE_DB_USER}' AND host != '%';" 2>/dev/null || true)
    if [ -n "$STALE_HOSTS" ]; then
      echo "Widening ${SITE_DB_USER}@ scope to '%' for container networking..."
      while IFS= read -r stale_host; do
        [ -z "$stale_host" ] && continue
        mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
          -e "RENAME USER '${SITE_DB_USER}'@'${stale_host}' TO '${SITE_DB_USER}'@'%';" 2>/dev/null || \
        mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
          -e "DROP USER IF EXISTS '${SITE_DB_USER}'@'${stale_host}';" 2>/dev/null || true
      done <<< "$STALE_HOSTS"
      mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -p"$DB_PASSWORD" \
        -e "GRANT ALL PRIVILEGES ON \`${SITE_DB_USER}\`.* TO '${SITE_DB_USER}'@'%'; FLUSH PRIVILEGES;" 2>/dev/null || true
    fi
  fi
fi

echo "==> Initialization complete. Launching services via supervisord..."
exec "$@"

