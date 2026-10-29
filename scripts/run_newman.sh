#!/usr/bin/env bash
# Use the native htmlextra reporter, never publish raw Newman credentials.
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/tools/newman"

if ! command -v node >/dev/null 2>&1; then
    printf 'Node.js is required. On NixOS, use a Node/npm development shell.\n' >&2
    exit 2
fi
for arg in "$@"; do
    if [[ "$arg" == --help || "$arg" == -h ]]; then
        exec node "$TOOLS/report.cjs" --help
    fi
done
if [[ ! -f "$TOOLS/node_modules/newman/package.json" || ! -f "$TOOLS/node_modules/newman-reporter-htmlextra/package.json" || ! -f "$TOOLS/node_modules/postman-collection/package.json" ]]; then
    if ! command -v npm >/dev/null 2>&1; then
        printf 'npm is required to install the pinned local Newman tools.\n' >&2
        exit 2
    fi
    printf 'Installing pinned Newman + htmlextra dependencies locally (no global installation).\n'
    npm ci --prefix "$TOOLS" --ignore-scripts --no-audit --no-fund
fi
exec node "$TOOLS/report.cjs" "$@"
