#!/usr/bin/env bash
# Follow the Compose logs and show only the events that matter during a verification run.
# Usage: scripts/watch-logs.sh [ROOT]   ROOT is the directory with compose.yaml and .env (default: this repository).
# Set WATCH_ALL=1 to see every line.
set -euo pipefail

root="${1:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$root"

events='uvicorn.access [^ ]+ - "(GET|POST|PUT|PATCH|DELETE) /api/'
events+='|dependency_failure|gateway_hop_failure|circuit_open|removal_outcome|health_transition'
events+='|alert event=|discord_delivery|reactivat|registration_state|removed'
events+='|TASK_LIMIT_EXCEEDED|critical_load|load_recovered'

# --ansi always keeps the Compose colours when the output goes through grep.
if [ "${WATCH_ALL:-}" = 1 ]; then
	exec docker compose --ansi always logs -f --tail 0
fi
docker compose --ansi always logs -f --tail 0 |
	grep --line-buffered -E "$events" |
	grep --line-buffered -v -E '/internal/v1/status|GET /ready|GET /healthz'
