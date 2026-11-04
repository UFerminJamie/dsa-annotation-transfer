#!/usr/bin/env bash
#SBATCH --job-name=athena-folder-transfer
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=08:00:00
#SBATCH --output=logs/slurm-folder-transfer-%j.out
#SBATCH --error=logs/slurm-folder-transfer-%j.err

set -euo pipefail

if [[ $# -lt 1 || $1 == --help || $1 == -h ]]; then
    echo "Usage: sbatch run_transfer.sh ATHENA_FOLDER_URL_OR_ID --source JSON_DIR [--apply] [other options]" >&2
    echo "A nested collection/.../folder/... URL is scoped to its folder. Default: dry-run." >&2
    exit 2
fi

destination=$1
shift

project_dir=$(cd -- "${SLURM_SUBMIT_DIR:-$(dirname -- "${BASH_SOURCE[0]}")}" && pwd)
if [[ ! -f $project_dir/pyproject.toml ]]; then
    echo "Submit this job from the transfer project directory" >&2
    exit 2
fi
cd -- "$project_dir"
export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is unavailable on this node" >&2
    exit 2
fi

manifest="$project_dir/transfer-manifest/folder-transfer-${SLURM_JOB_ID:-manual}.json"
exec python3 "$project_dir/src/run_transfer.py" \
    --destination "$destination" --manifest "$manifest" "$@"
