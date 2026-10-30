#!/usr/bin/env bash
set -e
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$script_dir/download_dsa_annotations.py" "$@"
