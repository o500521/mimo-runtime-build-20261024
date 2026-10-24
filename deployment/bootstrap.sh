#!/usr/bin/env bash
set -euo pipefail
# This script never creates a pod, rents GPUs, changes billing, or adds credit.
# Execute inside an already approved cloud pod only.
if [[ "${USER_APPROVED_GPU_START:-0}" != "1" ]]; then
  echo 'STOP: explicit user approval is required before any GPU-stage command.' >&2
  exit 2
fi
mode="${1:-preflight}"
image="ghcr.io/o500521/mimo-runtime-build-20261024:blackfrost-d78419fc"
checkpoint="/workspace/models/MiMo-V2.6-Pro-MOPD"
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
    docker run --rm --gpus all --entrypoint python "$image" -c 'import torch; assert torch.cuda.device_count()==8; print([(torch.cuda.get_device_name(i), torch.cuda.get_device_capability(i)) for i in range(8)])'
    ;;
  download)
    mkdir -p /workspace/models
    docker run --rm -v /workspace/models:/models --entrypoint python "$image" -c "from huggingface_hub import snapshot_download; snapshot_download('XiaomiMiMo/MiMo-V2.6-Pro-MOPD', revision='adea8e2c5373181e5a973fa1ecb343cb31af214b',local_dir='/models/MiMo-V2.6-Pro-MOPD',max_workers=16)"
    ;;
  *)
    echo 'Allowed modes: preflight or download. Model serving is a separate reviewed step.' >&2
    exit 2
    ;;
esac
