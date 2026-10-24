"""Run only in an approved GPU pod. No model weights or inference."""
import argparse
import datetime
import json
import socket


def validate_devices(devices):
    if len(devices)!=8: raise ValueError('Exactly eight GPUs are required')
    for device in devices:
        if 'RTX PRO 6000' not in device['name'] or tuple(device['capability'])!=(12,0):
            raise ValueError('Approved RTX PRO 6000 Blackwell SM120 hardware required')
        if device['memory_bytes']<90_000_000_000:
            raise ValueError('96GB-class GPU memory required on every device')


def worker(rank, port):
    import torch
    import torch.distributed as dist
    torch.cuda.set_device(rank)
    dist.init_process_group('nccl', init_method=f'tcp://127.0.0.1:{port}',rank=rank,world_size=8,
                            timeout=datetime.timedelta(seconds=60))
    value=torch.ones(1,device=f'cuda:{rank}')
    dist.all_reduce(value)
    assert value.item()==8, (rank,value.item())
    dist.destroy_process_group()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    import torch
    import torch.multiprocessing as mp
    devices=[dict(name=torch.cuda.get_device_name(i),capability=torch.cuda.get_device_capability(i),
                  memory_bytes=torch.cuda.get_device_properties(i).total_memory)
             for i in range(torch.cuda.device_count())]
    validate_devices(devices)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    mp.spawn(worker,args=(port,),nprocs=8,join=True)
    print(json.dumps({'gpu_validation':'passed','nccl_all_reduce':'passed','devices':devices,'model_loaded':False},indent=2))


if __name__=='__main__':main()
