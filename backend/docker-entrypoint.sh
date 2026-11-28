#!/bin/sh
set -eu

if [ "${HOUSEMATE_SEED_DEMO:-0}" = "1" ]; then
    python seed.py --if-empty
fi

exec "$@"
