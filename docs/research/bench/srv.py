import subprocess, time, json, os, sys, urllib.request
from bench_lib import sh, host_state
IMAGE = "ghcr.io/mostlygeek/llama-swap:unified-cuda"
MODELS = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/models"
HOSTIP = "192.168.1.69"
def start(name, gguf, port, args, mem="4g", wait=240):
    sh(f"ssh unraid 'docker rm -f {name} >/dev/null 2>&1'", 60)
    cmd = (f"ssh unraid 'docker run -d --rm --name {name} --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all "
           f"-e NVIDIA_DRIVER_CAPABILITIES=compute,utility --memory={mem} --memory-swap={mem} --cpus=4 --cpuset-cpus=0-4,8-12 "
           f"-v {MODELS}:/models:ro -p {HOSTIP}:{port}:8080 --entrypoint llama-server {IMAGE} "
           f"--host 0.0.0.0 --port 8080 -m /models/{gguf} --embedding {args}'")
    out = sh(cmd, 120)
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            with urllib.request.urlopen(f"http://{HOSTIP}:{port}/health", timeout=3) as r:
                if r.status == 200: return time.time() - t0
        except Exception: pass
        time.sleep(1.0)
    logs = sh(f"ssh unraid 'docker logs {name} 2>&1 | tail -20'", 30)
    raise RuntimeError("server did not become healthy:\n" + logs)
def vram_mb(name):
    pid = sh(f"ssh unraid \"docker inspect -f '{{{{.State.Pid}}}}' {name}\"", 30)
    out = sh("ssh unraid 'nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits'", 30)
    for line in out.splitlines():
        p, m = [x.strip() for x in line.split(",")]
        if p == pid: return int(m)
    return None
def stop(name):
    sh(f"ssh unraid 'docker rm -f {name} >/dev/null 2>&1'", 60)
def logs(name, n=40):
    return sh(f"ssh unraid 'docker logs {name} 2>&1 | tail -{n}'", 30)
