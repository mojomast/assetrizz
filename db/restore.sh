#!/usr/bin/env bash
# Restore db/assets.db from the compressed snapshot.
# Run from anywhere:  bash db/restore.sh
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [[ ! -f db/assets.db.xz ]]; then
  echo "db/restore.sh: missing db/assets.db.xz" >&2
  exit 1
fi
if [[ -e db/assets.db ]]; then
  echo "db/restore.sh: db/assets.db already exists; not overwriting" >&2
  exit 1
fi
xz -dk db/assets.db.xz
echo "Restored $root/db/assets.db"
