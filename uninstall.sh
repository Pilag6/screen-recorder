#!/bin/sh
set -eu
if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Usage: uninstall.sh (no arguments)' >&2
    exit 1
fi
if [ ! -x /usr/bin/python3 ]; then
    printf '%s\n' 'System /usr/bin/python3 is required.' >&2
    exit 1
fi
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
exec /usr/bin/python3 -B "$script_dir/installation.py" uninstall
