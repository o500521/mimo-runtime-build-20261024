#!/usr/bin/env bash
set -euo pipefail
# No rental, billing, top-up, model serving or card API calls exist in this script.
if [[ "${USER_APPROVED_GPU_START:-0}" != "1" ]]; then
  echo 'STOP: explicit user approval is required before any GPU-stage command.' >&2
  exit 2
fi
mode="${1:-preflight}"
image="ghcr.io/o500521/mimo-runtime-build-20261024@sha256:90847d1411c17fafe42eed2a0b22aaf7baf77072fb8150cb0fdbb5344e2f9dc1"
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
case "$mode" in
  preflight)
    command -v nvidia-smi >/dev/null
    command -v docker >/dev/null
    nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv
    count=$(nvidia-smi --query-gpu=index --format=csv,noheader | wc -l)
    test "$count" -eq 8
    mkdir -p /workspace/models
    available=$(df -B1 --output=avail /workspace | tail -n 1 | tr -d ' ')
    test "$available" -ge 1000000000000
    docker info >/dev/null
    docker pull "$image"
    docker run --rm --gpus all --shm-size 32g \
      --mount "type=bind,src=$script_dir,dst=/preflight,readonly" \
      --entrypoint python "$image" /preflight/gpu_smoke.py
    ;;
  download)
    mkdir -p /workspace/models
    docker run --rm -v /workspace/models:/models --entrypoint python "$image" -c "from huggingface_hub import snapshot_download; snapshot_download('XiaomiMiMo/MiMo-V2.6-Pro-MOPD', revision='adea8e2c5373181e5a973fa1ecb343cb31af214b',local_dir='/models/MiMo-V2.6-Pro-MOPD',max_workers=16)"
    ;;
  *)
    echo 'Allowed modes: preflight or download. Use runtime_session.py for the budget-gated workflow.' >&2
    exit 2
    ;;
esac
