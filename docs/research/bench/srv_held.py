"""Lock-guarded llama-server containers (Main's rule: ONE heavy job at a time, flock /tmp/agents-heavy.lock,
foreground docker run, never -d). The server lives inside `ssh unraid 'flock ... docker run --rm ...'` which runs as a local
background subprocess; the lock is held until the container exits. A hard `timeout` bounds the container lifetime."""
import subprocess, time, json, os, sys, urllib.request
from bench_lib import sh
IMAGE = "ghcr.io/mostlygeek/llama-swap:unified-cuda"
MODELS = "/mnt/nvme/appdata/cody/home/tmp/nomadindex/models"
HOSTIP = "192.168.1.69"
def load1():
    try: return float(sh("ssh unraid 'cut -d\" \" -f1 /proc/loadavg'", 20))
    except Exception: return 999.0
def wait_quiet(max_load=8.0, max_wait=3600, log=print, poll=30):
    t0 = time.time()
    while True:
        l = load1()
        if l < max_load: return l
        if time.time() - t0 > max_wait: return None
        log(f"  load {l} >= {max_load}, waiting {poll}s ..."); time.sleep(poll)
def start(name, gguf, port, args, mem="4g", max_life=1500, health_timeout=3600, extra_env=""):
    sh(f"ssh unraid 'docker rm -f {name} >/dev/null 2>&1'", 60)
    remote = (f"docker run --rm --name {name} --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all "
              f"-e NVIDIA_DRIVER_CAPABILITIES=compute,utility {extra_env} --memory={mem} --memory-swap={mem} --cpus=4 --cpuset-cpus=0-4,8-12 "
              f"-v {MODELS}:/models:ro -p {HOSTIP}:{port}:8080 --entrypoint timeout {IMAGE} {max_life} llama-server "
              f"--host 0.0.0.0 --port 8080 -m /models/{gguf} --embedding {args}")
    logf = open(f"/tmp/{name}.ssh.log", "w")
    p = subprocess.Popen(["ssh", "unraid", remote], stdout=logf, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < health_timeout:
        if p.poll() is not None:
            raise RuntimeError("container exited early: " + open(f"/tmp/{name}.ssh.log").read()[-800:])
        try:
            with urllib.request.urlopen(f"http://{HOSTIP}:{port}/health", timeout=3) as r:
                if r.status == 200: return p, time.time() - t0
        except Exception: pass
        time.sleep(2.0)
    raise RuntimeError("health timeout")
def stop(name, p=None):
    sh(f"ssh unraid 'docker rm -f {name} >/dev/null 2>&1'", 60)
    if p is not None:
        try: p.wait(timeout=60)
        except Exception: p.kill()
def vram_mb(name):
    pid = sh(f"ssh unraid \"docker inspect -f '{{{{.State.Pid}}}}' {name}\"", 30)
    out = sh("ssh unraid 'nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits'", 30)
    for line in out.splitlines():
        a, m = [x.strip() for x in line.split(",")]
        if a == pid: return int(m)
    return None
def logs(name, n=60):
    return sh(f"ssh unraid 'docker logs {name} 2>&1 | tail -{n}'", 30)
def bench(gguf, extra="-p 512,2048 -n 0 -ngl 99 -r 3 -b 2048 -ub 2048", max_life=900):
    remote = (f"docker run --rm --name nomadindex-lbench --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all "
              f"-e NVIDIA_DRIVER_CAPABILITIES=compute,utility --memory=4g --memory-swap=4g --cpus=4 --cpuset-cpus=0-4,8-12 "
              f"-v {MODELS}:/models:ro --entrypoint timeout {IMAGE} {max_life} llama-bench -m /models/{gguf} {extra} -o json")
    r = subprocess.run(["ssh", "unraid", remote], capture_output=True, text=True, timeout=max_life + 600)
    try: return json.loads(r.stdout[r.stdout.index("["):])
    except Exception: return {"raw": r.stdout[-500:], "err": r.stderr[-300:]}
