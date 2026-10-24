"""Approved-pod session preparation. Never rents, tops up or calls Lium APIs."""
import argparse
import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse

IMAGE = 'ghcr.io/o500521/mimo-runtime-build-20261024@sha256:90847d1411c17fafe42eed2a0b22aaf7baf77072fb8150cb0fdbb5344e2f9dc1'
NAME = 'mimo-blackfrost-eval'
REVISION = 'adea8e2c5373181e5a973fa1ecb343cb31af214b'
WEIGHT_BYTES = 573489510171
MODEL_DIR = '/workspace/models/MiMo-V2.6-Pro-MOPD'


def launch_command():
    return ['docker', 'run', '--detach', '--rm', '--name', NAME, '--gpus', 'all',
            '--network', 'host', '--shm-size', '32g',
            '--mount', 'type=bind,src=' + MODEL_DIR + ',dst=/models/MiMo-V2.6-Pro-MOPD,readonly',
            '--mount', 'type=bind,src=/workspace/mimo-cache,dst=/cache',
            '-e', 'MODEL_PATH=/models/MiMo-V2.6-Pro-MOPD',
            '-e', 'HOST=127.0.0.1', '-e', 'PORT=30000',
            '-e', 'SGLANG_CACHE_DIR=/cache/sglang',
            '-e', 'TORCHINDUCTOR_CACHE_DIR=/cache/torchinductor',
            '-e', 'TRITON_CACHE_DIR=/cache/triton',
            '--entrypoint', '/bin/bash', IMAGE,
            '/opt/blackfrost-runtime/scripts/launch_pro_mopd.sh']


def wait_ready(base, timeout=900, interval=2):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(base.rstrip('/') + '/v1/models', timeout=min(3, max(.05, deadline-time.monotonic()))) as response:
                data = json.load(response)
            ids = [item['id'] for item in data.get('data', []) if item.get('id')]
            if 'mimo-2.6-pro' in ids:
                return ids
        except (OSError, ValueError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError('Model readiness deadline reached; do not extend paid runtime automatically.')
        time.sleep(min(interval, max(0, deadline-time.monotonic())))


def validate_checkpoint(directory):
    root = pathlib.Path(directory).resolve()
    index = json.loads((root / 'model.safetensors.index.json').read_text())
    files = sorted(set(index['weight_map'].values()))
    for name in files:
        target = (root / name).resolve()
        if not target.is_relative_to(root) or not target.is_file() or target.stat().st_size < 1024:
            raise ValueError('Missing or invalid checkpoint shard: ' + name)
    if list(root.rglob('*.incomplete')):
        raise ValueError('Incomplete Hugging Face downloads remain.')
    return len(files)


def budget_estimate(bytes_per_second, hourly_usd, remaining_usd, overhead_minutes=45):
    if min(bytes_per_second, hourly_usd, remaining_usd) <= 0:
        raise ValueError('Positive measured throughput, hourly price and remaining credit are required.')
    # Planning estimate, not a promise: 50% transfer margin + load/test allowance.
    hours = WEIGHT_BYTES / bytes_per_second * 1.5 / 3600 + overhead_minutes / 60
    cost = hours * hourly_usd
    return dict(estimated_remaining_usd=round(cost, 2), fits_current_credit=cost <= remaining_usd,
                remaining_hours=round(hours, 3), overhead_minutes=overhead_minutes,
                estimate_not_guarantee=True)


def probe_download(sample_bytes=64*1024*1024):
    origin = 'https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Pro-MOPD/resolve/' + REVISION + '/'
    with urllib.request.urlopen(origin + 'model.safetensors.index.json', timeout=30) as response:
        index = json.loads(response.read(32*1024*1024))
    shard = sorted(set(index['weight_map'].values()))[0]
    if '/' in shard or '..' in shard:
        raise ValueError('Unexpected checkpoint shard path')
    req = urllib.request.Request(origin + urllib.parse.quote(shard), headers={'Range': 'bytes=0-'+str(sample_bytes-1)})
    began = time.monotonic()
    with urllib.request.urlopen(req, timeout=90) as response:
        if response.status != 206 or not response.headers.get('Content-Range', '').startswith('bytes 0-'):
            raise ValueError('Origin did not honor bounded range request; full shard transfer cancelled.')
        data = response.read(sample_bytes)
    elapsed = time.monotonic()-began
    if len(data) < 1024*1024:
        raise ValueError('Sample was too small for a useful planning estimate')
    return dict(sample_bytes=len(data), elapsed_seconds=round(elapsed,3),
                measured_mbps=round(len(data)*8/elapsed/1_000_000,3),
                checkpoint_revision=REVISION, sample_not_full_transfer_guarantee=True)


def start_model(run=subprocess.run, base='http://127.0.0.1:30000', timeout=900):
    run(launch_command(), check=True)
    try:
        return wait_ready(base, timeout)
    except Exception:
        run(['docker', 'logs', '--tail', '80', NAME], check=False)
        run(['docker', 'stop', '--time', '15', NAME], check=False)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'budget', 'probe', 'download', 'start', 'status', 'stop'])
    parser.add_argument('--approved', action='store_true')
    parser.add_argument('--provider-spend-cap-confirmed', action='store_true')
    parser.add_argument('--hourly-usd', type=float)
    parser.add_argument('--remaining-usd', type=float)
    parser.add_argument('--measured-mbps', type=float)
    parser.add_argument('--timeout-seconds', type=int, default=900)
    args = parser.parse_args()
    if args.mode == 'plan':
        print(json.dumps({'launch_command': launch_command(), 'creates_paid_resources': False,
                         'starts_model': False, 'provider_cap_required': True,
                         'stop_container_does_not_stop_pod_billing': True}, indent=2))
        return
    if args.mode == 'budget':
        if None in (args.measured_mbps, args.hourly_usd, args.remaining_usd):
            parser.error('budget requires measured-mbps, hourly-usd and remaining-usd')
        result = budget_estimate(args.measured_mbps*1_000_000/8, args.hourly_usd, args.remaining_usd)
        print(json.dumps(result, indent=2))
        if not result['fits_current_credit']:
            raise SystemExit(3)
        return
    if not args.approved:
        parser.error('STOP: explicit approval required; no commands executed')
    if args.mode == 'status':
        print(json.dumps(wait_ready('http://127.0.0.1:30000', timeout=5)))
    elif args.mode == 'probe':
        print(json.dumps(probe_download(),indent=2))
    elif args.mode == 'download':
        if not args.provider_spend_cap_confirmed or None in (args.measured_mbps,args.hourly_usd,args.remaining_usd):
            parser.error('Download requires confirmed provider cap, measured speed, price and effective remaining credit.')
        estimate=budget_estimate(args.measured_mbps*1_000_000/8,args.hourly_usd,args.remaining_usd)
        print(json.dumps(estimate,indent=2),flush=True)
        if not estimate['fits_current_credit']:
            raise SystemExit(3)
        subprocess.run(['bash',str(pathlib.Path(__file__).with_name('bootstrap.sh')),'download'],
                       env={**os.environ,'USER_APPROVED_GPU_START':'1'},check=True)
        print('Checkpoint shard validation:',validate_checkpoint(MODEL_DIR))
    elif args.mode == 'stop':
        subprocess.run(['docker', 'stop', '--time', '15', NAME], check=True)
        print('Model stopped. POD IS STILL BILLING until Lium removes it or its provider spend cap triggers.')
    else:
        if not args.provider_spend_cap_confirmed:
            parser.error('Set the provider-side pod auto-termination spend cap before starting.')
        if not args.hourly_usd or not args.remaining_usd or args.hourly_usd <= 0 or args.remaining_usd <= 0:
            parser.error('Supply the currently verified hourly rate and remaining credit.')
        allowed_seconds = int(args.remaining_usd/args.hourly_usd*3600) - 300
        if args.timeout_seconds < 1 or args.timeout_seconds > allowed_seconds:
            parser.error('Readiness timeout would exceed available credit with a five-minute reserve.')
        print('Checkpoint shards verified:', validate_checkpoint(MODEL_DIR))
        pathlib.Path('/workspace/mimo-cache').mkdir(parents=True, exist_ok=True)
        print('Ready model IDs:', start_model(timeout=args.timeout_seconds))
        print('Next: establish your SSH loopback forward to port 30000, then use local chat port 8766.')


if __name__ == '__main__':
    main()
