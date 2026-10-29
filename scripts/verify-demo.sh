#!/usr/bin/env bash
# Open tmux with the verification suite on the left and the filtered stack logs on the right.
# Usage: scripts/verify-demo.sh [verify.py arguments]   Example: scripts/verify-demo.sh scaling --yes
# With --root DIR, the right pane follows the logs of the stack in DIR.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
session="${VERIFY_DEMO_SESSION:-verify-demo}"

for tool in tmux uv docker; do
	command -v "$tool" >/dev/null 2>&1 || { printf '%s is required.\n' "$tool" >&2; exit 2; }
done

if tmux has-session -t "$session" 2>/dev/null; then
	printf 'Session %s already exists. Attach with: tmux attach -t %s\n' "$session" "$session" >&2
	exit 1
fi

# Follow the logs of the same stack that verify.py checks.
logs_root="$root"
previous=""
for argument in "$@"; do
	[ "$previous" = --root ] && logs_root="$argument"
	previous="$argument"
done

quoted=$(printf ' %q' "$@")
tmux new-session -d -s "$session" -c "$root" "uv run scripts/verify.py${quoted}; printf '\\nPress Enter to close.\\n'; read -r _"
tmux split-window -h -t "$session" -c "$root" "scripts/watch-logs.sh $(printf %q "$logs_root")"
tmux select-pane -t "$session:0.0"
if [ -n "${VERIFY_DEMO_DETACH:-}" ]; then
	printf 'Started tmux session %s. Attach with: tmux attach -t %s\n' "$session" "$session"
else
	exec tmux attach -t "$session"
fi
