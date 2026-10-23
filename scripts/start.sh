#!/usr/bin/env bash
# Start the databases. If Docker left broken containers behind (the "RWLayer ... nil"
# error after a Codespace stop), remove them and start again. Data volumes are kept.
set -u
cd "$(dirname "$0")/.."

if ! docker compose up -d --wait; then
    echo "Start failed - removing broken containers and trying again (your data is kept)..."
    docker rm -f dbagent-main dbagent-sandbox
    docker compose up -d --wait
fi
docker compose ps