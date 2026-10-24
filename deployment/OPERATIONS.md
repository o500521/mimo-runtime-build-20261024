# Blackfrost staged session

This bundle does not rent machines, add credit or call a paid model API. The cloud CPU integration test uses a **MOCK model**, the actual chat gateway/backend source, and a headless browser. Its success is transport evidence, not evidence of model quality, actual SSH connectivity, NVIDIA kernels or successful weight loading.

## Before any paid step

1. Obtain the user's explicit GPU-start approval and verify the live quote again.
2. Choose 8 RTX PRO 6000 Blackwell 96GB GPUs. Use the official PyTorch + CUDA + DinD template. Do not install the inference stack into the template's Python.
3. Select the previously approved existing SSH public key. Keep its private key on the client computer.
4. Turn OFF backup and Jupyter; leave local volume encryption ON. Do not attach a persistent S3 volume. Use only included local disk.
5. Set a provider-side auto-termination **spend cap**, not an empty hours field. Initial diagnostics and a full download are separate stages. Do not begin the full download under a diagnostic cap that cannot cover it.
6. Disable automatic top-ups. The effective remaining allowance is the smallest of current paid credit, remaining provider spend cap, and the user's remaining total budget. Previously paid credit is included in the total cash cap. Never interpret a total budget as approval to charge a card.

## Approved pod: inspect first

Fetch this public repository into **`/workspace/mimo-session`**, not the encrypted `/root`, because the checker script itself is bind-mounted into nested Docker. Its files contain no API keys or model weights:

```bash
git clone https://github.com/o500521/mimo-runtime-build-20261024.git /workspace/mimo-session
cd /workspace/mimo-session/deployment
USER_APPROVED_GPU_START=1 bash bootstrap.sh preflight
python runtime_session.py probe --approved
```

The first command inspects GPU count, disk and Docker, pulls the immutable image and tests GPU visibility. Read the reported **model, VRAM, compute capability and driver**; stop if they differ from the approved hardware. Use `/workspace/models` for public checkpoint files. Lium's encrypted `/root` cannot be bind-mounted into a nested Docker container.

The bounded probe reads at most 64 MiB from one pinned checkpoint shard. It refuses an unbounded HTTP 200 response. Sample throughput is only a planning estimate and can differ from sustained parallel downloads. The platform's published network benchmark is not a measured HF download rate.

## Budget gate and download

Replace the placeholders with fresh private account values. `EFFECTIVE_REMAINING_USD` is the smallest allowance described above. Do not use the account's total credit if the pod's remaining spend cap is smaller.

```bash
python runtime_session.py budget --measured-mbps MEASURED_HF_MBPS --hourly-usd VERIFIED_RATE --remaining-usd EFFECTIVE_REMAINING_USD
python runtime_session.py download --approved --provider-spend-cap-confirmed --measured-mbps MEASURED_HF_MBPS --hourly-usd VERIFIED_RATE --remaining-usd EFFECTIVE_REMAINING_USD
```

A conservative estimate applies a 50% transfer margin plus 45 minutes for loading, compilation and questions. Exit code 3 means insufficient current allowance: do not download or recharge automatically. This estimate is not a guarantee. If the user approves a later stage, update the **existing pod's provider cap** and verify its saved value before continuing; do not let a small diagnostic cap delete a partially downloaded checkpoint.

The HF checkpoint remains at revision `adea8e2c5373181e5a973fa1ecb343cb31af214b`. No additional quantization or pruning is applied. The published checkpoint is MXFP4; BF16 runtime direction tensors do not make the checkpoint BF16.

## Start and health check

```bash
python runtime_session.py start --approved --provider-spend-cap-confirmed --hourly-usd VERIFIED_RATE --remaining-usd EFFECTIVE_REMAINING_USD --timeout-seconds 900
```

This validates the checkpoint's referenced shards, starts the pinned container with the vendor's launcher and waits for `/v1/models` to report `mimo-2.6-pro`. The API binds only to the pod's loopback port 30000. It does not expose a public unauthenticated inference port. A readiness timeout captures recent container logs and stops the model container. **Stopping a container does not stop Lium pod billing.** The provider-side cap is mandatory; delete the disposable test pod through Lium when the session ends, after saving any wanted test results.

## Connect the existing chat UI

Obtain the actual SSH host/port and verify the host fingerprint against trusted provider information. On the client, use the existing OpenSSH client and existing approved private key. No WSL or local Linux installation is needed:

```text
ssh -N -i C:\Users\edwin\.ssh\0to1_extravm -p POD_SSH_PORT -L 127.0.0.1:30000:127.0.0.1:30000 -o ExitOnForwardFailure=yes root@POD_SSH_HOST
```

Do not bypass a changed-host-key warning. The command has placeholders until a pod actually exists. Do not place the private key or official API key on the rented host.

Open the existing client UI at `http://127.0.0.1:8766/`, select **八卡自架（SSH 轉發）**, leave API Key empty, and press **檢查連線**. The UI discovers the served model ID. Only then submit benign text or an image. Image-only, paste and drag/drop paths are covered by the free mock integration test. The UI currently accepts one PNG/JPEG/WebP image up to 2 MiB; it does not provide video/audio upload controls.

## Finish or error

- Preserve the provider spend cap. Do not increase it or top up without the user's approval.
- End the SSH tunnel when done. Stop the model if needed, then remove the disposable pod in Lium to stop GPU billing; verify that the pod list and hourly spending show no running resource.
- No paid-GPU success is claimed until actual checkpoint loading, GPU kernels, SSH forwarding and a real text/image response have been observed. Video/audio inference is a separate test and is not covered by the current chat interface.
