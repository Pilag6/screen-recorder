#!/bin/sh
# System Python avoids a PATH-selected virtualenv without GI/GTK bindings.
set -eu
if [ "$#" -ne 0 ]; then
    printf '%s\n' 'Usage: install.sh (no arguments)' >&2
    exit 1
fi
if [ ! -x /usr/bin/python3 ]; then
    printf '%s\n' 'System /usr/bin/python3 (3.10+) is required; see INSTALL.md.' >&2
    exit 1
fi
script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
exec /usr/bin/python3 -B "$script_dir/installation.py" install
