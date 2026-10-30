#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd -- "$project_dir"
exec python3 "$project_dir/delete_annotations.py" "$@"


# example
# To preview dont use --apply flag
./delete_annotations.sh \
  # --source /orange/pinaki.sarder/j.fermin/cort_med_wsi/trident_processed_final/KPMP/inference_jsons/svc_2_rbf_1.0/ \
  # --destination 'https://athena.rc.ufl.edu/#folder/6ad6a9d8e27b973811097f02'
# --apply 
