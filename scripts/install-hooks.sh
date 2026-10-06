#!/bin/sh
set -eu
force=false
case "$#" in
    0) ;;
    1) if [ "$1" = --force ]; then force=true; else
           echo "Usage: $0 [--force]" >&2; exit 1
       fi ;;
    *) echo "Usage: $0 [--force]" >&2; exit 1 ;;
esac
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
if current=$(git -C "$root" config --get core.hooksPath); then
    if [ "$current" != .githooks ] && [ "$force" != true ]; then
        echo "Refusing to replace core.hooksPath=$current; use --force to replace it." >&2
        exit 1
    fi
fi
git -C "$root" config --local core.hooksPath .githooks
printf '%s\n' 'Installed hooks: core.hooksPath=.githooks'
