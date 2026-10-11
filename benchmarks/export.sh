#!/bin/sh
# Copy rating_snapshots from the production database to benchmarks/data/ (read only).
set -eu
host="$1"
out="$(dirname "$0")/data"
mkdir -p "$out"
ssh "$host" 'docker exec geostats-db-1 sh -c "psql -U \$POSTGRES_USER -d \$POSTGRES_DB -c \"copy (select account_id, captured_at, rating, rating_moving, rating_nomove, rating_nmpz, games_played, games_won, win_streak, guessed_first_rate, avg_guess_distance_km from rating_snapshots order by account_id, captured_at) to stdout with csv header\"" | gzip -c' > "$out/snapshots.csv.gz"
