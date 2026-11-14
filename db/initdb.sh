#!/bin/sh
# Applies TrucksIL SQL migrations in order on first database initialisation.
set -eu
for f in /trucksil-migrations/*.sql; do
  echo "trucksil: applying $f"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
