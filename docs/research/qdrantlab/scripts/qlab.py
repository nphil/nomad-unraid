#!/usr/bin/env python3
"""qlab - tiny harness for NOMAD-style Qdrant experiments (slice `qdrantlab`).

Everything runs against throw-away `qdrant/qdrant:v1.16.3` containers started on the
Unraid host over ssh (never production). The client side (this file) talks plain REST
with the stdlib only, exactly like NOMAD's @qdrant/js-client-rest does.
"""
import http.client
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from time import perf_counter

import numpy as np

HOST_IP = '192.168.1.69'
PORT = 16333
SCRATCH = '/mnt/nvme/nomadindex-scratch/qdrantlab'
IMAGE = 'qdrant/qdrant:v1.16.3'
BASE = '/data/home/tmp/nomadindex/qdrantlab'
WORK = BASE + '/work'
RES = BASE + '/results'
LOGS = BASE + '/logs'
LOCKFILE = '/tmp/agents-heavy.lock'  # host-wide 'one heavy job at a time' lock (Main's directive 2026-10-01)
COLL = 'nomad_knowledge_base'
DIM = 768

SSH_BASE = ['ssh', '-o', 'ControlMaster=auto', '-o', 'ControlPath=/tmp/qlab-ssh-%C',
            '-o', 'ControlPersist=900', '-o', 'ServerAliveInterval=30', 'unraid']


def ssh(cmd, timeout=600, check=True, retries=5):
    """run a command on the Unraid host. ssh-level failures (rc 255: connection reset, MaxStartups on the shared
    host, ...) are retried with backoff; remote command failures are not."""
    p = None
    for i in range(retries):
        p = subprocess.run(SSH_BASE + [cmd], capture_output=True, text=True, timeout=timeout)
        if p.returncode == 255 and i < retries - 1:
            time.sleep(2 * (i + 1))
            continue
        break
    if check and p.returncode != 0:
        raise RuntimeError(f'ssh failed rc={p.returncode}: {cmd[:200]}\n{p.stderr[-500:]}')
    return p.stdout


def loadavg():
    with open('/proc/loadavg') as f:
        return f.read().split()[:3]


_logf = None


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} [load {' '.join(loadavg())}] {msg}"
    print(line, flush=True)


# ----------------------------------------------------------------------------------
# REST client
# ----------------------------------------------------------------------------------
class Qd:
    def __init__(self, host=HOST_IP, port=PORT):
        self.host, self.port = host, port
        self.conn = None

    def _conn(self):
        if self.conn is None:
            self.conn = http.client.HTTPConnection(self.host, self.port, timeout=3600)
        return self.conn

    def raw(self, method, path, body=None):
        """returns (status, bytes, seconds). body: bytes|str|dict|None"""
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode()
        hdr = {'Content-Type': 'application/json'} if body is not None else {}
        for attempt in range(3):
            try:
                c = self._conn()
                t0 = perf_counter()
                c.request(method, path, body=body, headers=hdr)
                r = c.getresponse()
                data = r.read()
                return r.status, data, perf_counter() - t0
            except (http.client.HTTPException, ConnectionError, OSError):
                self.conn = None
                if attempt == 2:
                    raise
                time.sleep(1)

    def req(self, method, path, body=None):
        st, data, dt = self.raw(method, path, body)
        try:
            js = json.loads(data)
        except Exception:
            js = {'raw': data[:300].decode(errors='replace')}
        return st, js, dt

    def ok(self, method, path, body=None):
        st, js, dt = self.req(method, path, body)
        if st >= 300:
            raise RuntimeError(f'{method} {path} -> {st} {json.dumps(js)[:400]}')
        return js

    # convenience
    def info(self, coll=COLL):
        return self.ok('GET', f'/collections/{coll}')['result']


def wait_ready(qd, timeout=1800):
    t0 = perf_counter()
    while perf_counter() - t0 < timeout:
        try:
            st, data, _ = qd.raw('GET', '/readyz')
            if st == 200:
                return perf_counter() - t0
        except Exception:
            qd.conn = None
        time.sleep(0.5)
    raise TimeoutError('qdrant not ready')


# ----------------------------------------------------------------------------------
# Container lifecycle + process/cgroup/disk measurements (all on the host over ssh)
# ----------------------------------------------------------------------------------
class Lab:
    def __init__(self, run, mem='4g', cpus=4, cpuset='0-4,8-12', port=PORT):
        self.run = run
        self.name = f'nomadindex-qdrantlab-{run}'[:60]
        self.mem, self.cpus, self.cpuset, self.port = mem, cpus, cpuset, port
        self.storage = f'{SCRATCH}/{run}/storage'
        self.qd = Qd(port=port)
        self.cid = self.qpid = None
        self.t_start_to_ready = None

    def free_gb(self):
        out = ssh("awk '/MemAvailable/{print $2}' /proc/meminfo")
        return int(out.strip()) / 1048576

    def _drain(self):
        for line in self.proc.stdout:
            self.logbuf.append(line.rstrip())
            if len(self.logbuf) > 400:
                del self.logbuf[:100]

    def kill_waiter(self):
        """kill any host-side `flock ... <this run's container>` process that is still queued for / holding the lock
        (e.g. after a client crash). Pattern trick [f]lock keeps pkill from matching its own command line."""
        ssh(f"pkill -f '[f]lock {LOCKFILE} .*{self.name}'; rm -f {self._go_file()} {self._mem_file()}; true", check=False)

    def _mem_file(self):
        return f'/tmp/qlab-mem-{self.name}'

    def _go_file(self):
        return f'/tmp/qlab-go-{self.name}'

    def start(self, wait=True, lock=True, session=False):
        """Start Qdrant as a FOREGROUND `docker run --rm` held under the host-wide flock (never -d): the lock is held
        for the whole life of the container; stop() releases it. Blocks (polling) until the lock is granted.
        session=True: the docker run sits in a host-side loop under ONE flock hold so restart() can restart the container
        (optionally with another memory cap) without letting another agent take the lock in between. The loop ends when
        stop() removes the go-file; `timeout 1800` and a 6-restart cap guarantee the lock can never be held forever."""
        ssh(f'mkdir -p {self.storage}')
        ssh(f'docker rm -f {self.name} >/dev/null 2>&1; true')
        port_args = f'-p {HOST_IP}:{self.port}:6333 -p {HOST_IP}:{self.port + 1}:6334'
        common = (f'--cpus={self.cpus} --cpuset-cpus={self.cpuset} -e QDRANT__TELEMETRY_DISABLED=true '
                  f'{port_args} -v {self.storage}:/qdrant/storage {IMAGE}')
        self.session = session
        if session:
            ssh(f'echo {self.mem} > {self._mem_file()}; rm -f {self._go_file()}')
            loop = (f'GO={self._go_file()}; touch $GO; n=0; '
                    f'while [ -e $GO ] && [ $n -lt 6 ]; do n=$((n+1)); M=$(cat {self._mem_file()}); '
                    f'docker run --rm --name {self.name} --memory=$M --memory-swap=$M {common}; sleep 2; done; rm -f $GO')
            cmd = f"flock {LOCKFILE} timeout 1800 bash -c '{loop}'"
        else:
            docker = f'docker run --rm --name {self.name} --memory={self.mem} --memory-swap={self.mem} {common}'
            cmd = f'flock {LOCKFILE} {docker}' if lock else docker
        t_req = perf_counter()
        self.logbuf = []
        self.proc = subprocess.Popen(SSH_BASE + [cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._drain, daemon=True).start()
        self.qd.conn = None
        last_log = perf_counter()
        try:
            while True:
                if self.proc.poll() is not None:
                    raise RuntimeError(f'docker run exited rc={self.proc.returncode}: {" | ".join(self.logbuf[-5:])}')
                out = ssh(f"docker inspect {self.name} --format '{{{{.Id}}}} {{{{.State.Pid}}}}' 2>/dev/null; true").split()
                if len(out) == 2:
                    break
                if perf_counter() - last_log > 120:
                    last_log = perf_counter()
                    log(f'  waiting for {LOCKFILE} ({perf_counter() - t_req:.0f}s)')
                time.sleep(3)
        except BaseException:
            self.kill_waiter()
            raise
        self.t_lock_wait = perf_counter() - t_req
        self.cid = out[0]
        t0 = perf_counter()
        if wait:
            wait_ready(self.qd)
            self.t_start_to_ready = perf_counter() - t0
        self.qpid = ssh(f'pgrep -P {out[1]}').split()[0]
        return self.t_start_to_ready

    def restart(self, mem=None, kill=False):
        """session mode only: stop the container and let the host loop start a fresh one (same lock hold).
        kill=True: SIGKILL instead of a graceful stop (crash simulation).
        Returns seconds from `docker stop` to /readyz (shutdown + start + collection load)."""
        assert getattr(self, 'session', False)
        if mem:
            self.mem = mem
            ssh(f'echo {mem} > {self._mem_file()}')
        old = self.cid
        t0 = perf_counter()
        self.qd.conn = None
        if kill:
            ssh(f'docker kill {self.name} >/dev/null 2>&1; true', timeout=120)
        else:
            ssh(f'docker stop -t 120 {self.name} >/dev/null 2>&1; true', timeout=300)
        t_stopped = perf_counter() - t0
        while perf_counter() - t0 < 600:
            out = ssh(f"docker inspect {self.name} --format '{{{{.Id}}}} {{{{.State.Pid}}}} {{{{.State.Running}}}}' 2>/dev/null; true").split()
            if len(out) == 3 and out[0] != old and out[2] == 'true':
                break
            if self.proc.poll() is not None:
                raise RuntimeError(f'session loop ended during restart: {" | ".join(self.logbuf[-5:])}')
            time.sleep(1)
        self.cid = out[0]
        t1 = perf_counter()
        wait_ready(self.qd)
        self.qpid = ssh(f'pgrep -P {out[1]}').split()[0]
        return {'shutdown_s': t_stopped, 'start_to_ready_s': perf_counter() - t1}

    def stop(self):
        t0 = perf_counter()
        if getattr(self, 'session', False):
            ssh(f'rm -f {self._go_file()}; true')
        ssh(f'docker stop -t 120 {self.name} >/dev/null 2>&1; true', timeout=300)
        p = getattr(self, 'proc', None)
        if p is not None and p.poll() is None:
            exists = ssh(f"docker ps -aq --filter name=^{self.name}$").strip()
            if not exists:
                self.kill_waiter()  # never got the lock (or container already gone): do not wait for it
            try:
                p.wait(timeout=120)  # foreground docker run / session loop returns -> flock released
            except subprocess.TimeoutExpired:
                self.kill_waiter()
                p.kill()
        for _ in range(60):
            if not ssh(f"docker ps -aq --filter name=^{self.name}$").strip():
                break
            time.sleep(1)
        self.kill_waiter()
        self.qd.conn = None
        return perf_counter() - t0

    def rmstorage(self):
        ssh(f'rm -rf {SCRATCH}/{self.run}')

    def snapshot(self):
        """RSS / page faults / io / cgroup memory+cpu, as ints (bytes, counts, usec)."""
        cmd = (f'ID={self.cid}; QP={self.qpid}; CG=/sys/fs/cgroup/docker/$ID; '
               'echo "##status"; grep -E "^(VmRSS|VmHWM|RssAnon|RssFile|RssShmem|VmSwap|Threads):" /proc/$QP/status; '
               'echo "##stat"; cat /proc/$QP/stat; '
               'echo "##io"; cat /proc/$QP/io; '
               'echo "##cgmem"; echo "current $(cat $CG/memory.current)"; echo "peak $(cat $CG/memory.peak 2>/dev/null)"; '
               'grep -E "^(anon|file|file_mapped|file_dirty|active_file|inactive_file|shmem|pgfault|pgmajfault) " $CG/memory.stat; '
               'echo "##cgev"; cat $CG/memory.events; '
               'echo "##cgcpu"; grep -E "usage_usec|user_usec|system_usec|nr_throttled|throttled_usec" $CG/cpu.stat; '
               'echo "##host"; cat /proc/loadavg; grep -E "MemAvailable|MemFree|^Cached|SwapFree" /proc/meminfo')
        out = ssh(cmd)
        snap, sec = {}, None
        for line in out.splitlines():
            if line.startswith('##'):
                sec = line[2:]
                continue
            if sec == 'stat':
                f = line.split(')')[-1].split()
                snap['minflt'], snap['majflt'] = int(f[7]), int(f[9])  # fields 10 and 12 of stat
            elif sec == 'host' and ':' not in line:
                snap['loadavg'] = line.split()[:3]
            else:
                parts = line.replace(':', ' ').split()
                if len(parts) >= 2 and parts[1].isdigit():
                    val = int(parts[1])
                    if len(parts) > 2 and parts[2] == 'kB':
                        val *= 1024
                    snap[f'{sec}.{parts[0]}'] = val
        return snap

    def smaps_top(self, n=14):
        """Resident / anonymous KB per mapped file (or [anon]/[heap]) of the qdrant process, biggest first."""
        cmd = ("awk '/^[0-9a-f]+-[0-9a-f]+ /{name=$6; if(name==\"\") name=\"[anon]\"} /^Rss:/{rss[name]+=$2} "
               "/^Anonymous:/{an[name]+=$2} /^Swap:/{sw[name]+=$2} END{for(k in rss) printf \"%d %d %d %s\\n\", rss[k], an[k], sw[k], k}' "
               f"/proc/{self.qpid}/smaps | sort -rn | head -{n}")
        out = ssh(cmd)
        rows = []
        for line in out.splitlines():
            p = line.split(' ', 3)
            if len(p) == 4:
                rows.append({'rss_kb': int(p[0]), 'anon_kb': int(p[1]), 'swap_kb': int(p[2]), 'name': p[3]})
        return rows

    def docker_stats(self):
        out = ssh(f"docker stats --no-stream --format '{{{{.MemUsage}}}}|{{{{.CPUPerc}}}}' {self.name}")
        return out.strip()

    def disk(self, coll=COLL):
        """Per-file listing of the collection folder: (rel path, apparent bytes, allocated bytes)."""
        out = ssh(f"cd {self.storage}/collections/{coll} 2>/dev/null && find . -type f -printf '%s %b %p\\n'")
        files = []
        for line in out.splitlines():
            s, b, p = line.split(' ', 2)
            files.append((p, int(s), int(b) * 512))
        top = ssh(f"du -sb {self.storage} | cut -f1; du -s --block-size=1 {self.storage} | cut -f1")
        top = [int(x) for x in top.split()]
        return files, {'storage_apparent': top[0], 'storage_allocated': top[1]}


# ----------------------------------------------------------------------------------
# disk categorisation
# ----------------------------------------------------------------------------------
def categorize(path):
    """Map a file path inside collections/<c>/ to a coarse bucket."""
    p = path.lstrip('./')
    if '/wal/' in '/' + p or p.startswith('0/wal') or '/wal/' in p:
        return 'wal'
    if 'temp_segments' in p:
        return 'temp_segments'
    m = re.match(r'^0/segments/([^/]+)/(.*)$', p)
    if not m:
        return 'collection_meta'
    rest = m.group(2)
    low = rest.lower()
    if low.startswith('payload_index') or '/payload_index/' in low:
        return 'payload_index'
    if low.startswith('payload_storage') or low.startswith('payload'):
        return 'payload_storage'
    if low.startswith('vector_storage') or low.startswith('vector_data'):
        sub = low
        if 'quantiz' in sub:
            return 'quantized_vectors'
        if 'hnsw' in sub or 'graph' in sub or 'links' in sub or 'vector_index' in sub:
            return 'hnsw'
        return 'vectors_original'
    if 'quantiz' in low:
        return 'quantized_vectors'
    if low.startswith('vector_index') or 'hnsw' in low or 'graph' in low or 'links' in low:
        return 'hnsw'
    if 'id_tracker' in low or 'mapping' in low or 'versions' in low:
        return 'id_tracker'
    return 'segment_other'


def disk_summary(files):
    buckets = {}
    for p, a, al in files:
        b = categorize(p)
        d = buckets.setdefault(b, {'apparent': 0, 'allocated': 0, 'files': 0})
        d['apparent'] += a
        d['allocated'] += al
        d['files'] += 1
    return buckets


# ----------------------------------------------------------------------------------
# dataset access (synthetic and real share one format: vectors f32 + chunks jsonl)
# ----------------------------------------------------------------------------------
class Dataset:
    def __init__(self, vec_path, chunks_path, dim=DIM, n_rows=None):
        self.vec_path, self.chunks_path, self.dim = vec_path, chunks_path, dim
        size = os.path.getsize(vec_path)
        self.n_rows = n_rows or size // (4 * dim)
        self.mm = np.memmap(vec_path, dtype='<f4', mode='r', shape=(self.n_rows, dim))
        self._offs = None

    def offsets(self):
        if self._offs is None:
            cache = self.chunks_path + '.offs.npy'
            if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(self.chunks_path):
                self._offs = np.load(cache)
            else:
                offs = [0]
                with open(self.chunks_path, 'rb') as f:
                    for line in f:
                        offs.append(offs[-1] + len(line))
                self._offs = np.array(offs, dtype=np.int64)
                np.save(cache, self._offs)
        return self._offs

    def payloads(self, rows):
        """bytes of the payload JSON (one object) for each requested row, in order."""
        offs = self.offsets()
        out = []
        with open(self.chunks_path, 'rb') as f:
            for r in rows:
                f.seek(int(offs[r]))
                out.append(f.readline().rstrip(b'\n'))
        return out

    def vectors(self, rows, dim=None):
        rows = np.asarray(rows)
        order = np.argsort(rows)  # memmap fancy indexing is faster when sorted
        v = np.empty((len(rows), self.dim), dtype=np.float32)
        v[order] = self.mm[rows[order]]
        if dim and dim < self.dim:
            v = v[:, :dim]
            v = v / np.linalg.norm(v, axis=1, keepdims=True)
        return np.ascontiguousarray(v, dtype=np.float32)


class PoolDataset(Dataset):
    """Vectors from a raw f32 file; payload of row i = a real NOMAD payload (field `payload` of chunks_*.jsonl lines,
    a pool of real objects) with a unique document_id. Payload bytes and compressibility are therefore real."""

    def __init__(self, vec_path, pool_path, dim=DIM, n_rows=None, max_pool=30000):
        Dataset.__init__(self, vec_path, pool_path, dim, n_rows)
        self.pool = []
        with open(pool_path, 'rb') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                p = d.get('payload') if isinstance(d, dict) else None
                if not isinstance(p, dict) or 'text' not in p:
                    continue
                did = p.get('document_id', '')
                s = json.dumps(p, ensure_ascii=False, separators=(',', ':'))
                key = '"document_id":"%s"' % did
                if did and key in s:
                    pre, post = s.split(key, 1)
                    self.pool.append((pre.encode(), post.encode()))
                if len(self.pool) >= max_pool:
                    break
        if not self.pool:
            raise RuntimeError('empty payload pool')

    def payloads(self, rows):
        out = []
        P = len(self.pool)
        for r in rows:
            pre, post = self.pool[(int(r) * 2654435761) % P]
            did = str(uuid.UUID(int=(int(r) * 0x9E3779B97F4A7C15 + 12345) % (1 << 128), version=4))
            out.append(pre + b'"document_id":"' + did.encode() + b'"' + post)
        return out



ID_MODE = {'mode': 'uuid'}  # 'uuid' (what NOMAD sends: random UUID4 strings) | 'int' (plain u64 ids)
_M122 = 1 << 122
_K = (0x2545F4914F6CDD1DA3B5C1E7F0A4D9B7 % _M122) | 1   # odd => invertible mod 2^122
_KINV = pow(_K, -1, _M122)


def row_uuid(row):
    """JSON id literal for a dataset row. uuid mode: a bijective, random-looking UUID4 (so the id tracker sees
    random keys exactly like NOMAD's randomUUID(), yet recall can map a returned id back to its row)."""
    if ID_MODE['mode'] == 'int':
        return str(int(row) + 1)
    x = ((int(row) + 1) * _K) % _M122
    lo, mid, hi = x & ((1 << 62) - 1), (x >> 62) & 0xFFF, x >> 74
    u = (hi << 80) | (0x4 << 76) | (mid << 64) | (0b10 << 62) | lo
    return '"' + str(uuid.UUID(int=u)) + '"'


def uuid_row(s):
    if isinstance(s, int):
        return s - 1
    u = int(s.replace('-', ''), 16)
    lo, mid, hi = u & ((1 << 62) - 1), (u >> 64) & 0xFFF, u >> 80
    x = (hi << 74) | (mid << 62) | lo
    return (x * _KINV) % _M122 - 1


def vec_json(v):
    # 7 decimals: abs error 5e-8 per component (unit-norm 768-d => cosine error ~1e-7), keeps request bodies small
    return json.dumps(np.round(np.asarray(v, dtype=np.float64), 7).tolist(), separators=(',', ':'))


def points_body(rows, vecs, payloads, id_offset=0):
    parts = []
    for r, v, p in zip(rows, vecs, payloads):
        parts.append(b'{"id":' + row_uuid(int(r) + id_offset).encode() + b',"vector":' + vec_json(v).encode()
                     + b',"payload":' + p + b'}')
    return b'{"points":[' + b','.join(parts) + b']}'


# ----------------------------------------------------------------------------------
# collection creation (NOMAD-exact baseline + variants)
# ----------------------------------------------------------------------------------
def create_collection(qd, coll=COLL, dim=DIM, create=None, indexes=True):
    """create: dict merged into the PUT body (vectors/params extras). Baseline = NOMAD's call."""
    body = {'vectors': {'size': dim, 'distance': 'Cosine'}}
    create = json.loads(json.dumps(create or {}))
    vec_extra = create.pop('vectors', {})
    body['vectors'].update(vec_extra)
    body.update(create)
    qd.ok('PUT', f'/collections/{coll}', body)
    if indexes:  # NOMAD _ensureCollection(): 3 keyword indexes + 1 bool index, on the EMPTY collection
        schema = indexes if isinstance(indexes, dict) else {
            'source': 'keyword', 'content_type': 'keyword', 'collection': 'keyword', 'active': 'bool'}
        for f, s in schema.items():
            qd.ok('PUT', f'/collections/{coll}/index?wait=true', {'field_name': f, 'field_schema': s})
    return body


def wait_green(qd, coll=COLL, stable=5, timeout=7200, poll=1.0, verbose=None):
    """Block until status green + optimizer ok for `stable` consecutive polls. Returns (seconds, info)."""
    t0 = perf_counter()
    ok = 0
    last = None
    t_log = t0
    while perf_counter() - t0 < timeout:
        info = qd.info(coll)
        sig = (info['status'], str(info['optimizer_status']), info['segments_count'])
        if info['status'] == 'green' and info['optimizer_status'] == 'ok' and sig == last:
            ok += 1
            if ok >= stable:
                return perf_counter() - t0, info
        else:
            ok = 0
        last = sig
        if verbose and perf_counter() - t_log > 60:
            t_log = perf_counter()
            verbose(f"  waiting for optimizer: status={info['status']} segments={info['segments_count']} "
                    f"indexed={info['indexed_vectors_count']}/{info['points_count']}")
        time.sleep(poll)
    raise TimeoutError('optimizer did not finish')


# ----------------------------------------------------------------------------------
# ingest
# ----------------------------------------------------------------------------------
def collection_exists(qd, coll=COLL):
    st, js, _ = qd.req('GET', f'/collections/{coll}')
    return st == 200



def body_cache_path(cache_dir, tag, i):
    return f'{cache_dir}/{tag}/{i:06d}.json'


def build_batch_body(ds, chunk, dim, id_offset=0):
    vecs = ds.vectors(chunk, dim)
    pays = ds.payloads(chunk)
    return points_body(chunk, vecs, pays, id_offset)


def ingest_range(qd, ds, rows, start, end, coll=COLL, dim=DIM, mode='bulk', batch=1000, small_range=(1, 5), seed=1,
                 deadline=None, cache_dir=None, cache_tag=None, id_offset=0, report_every=50000, tag='', row_base=0):
    """Upsert rows[start:end] with wait=true; stop early at `deadline` (a perf_counter value). Returns (stats, next_index).
    mode 'small': 1-5 points per call (NOMAD embedAndStoreText: one section = one upsert). mode 'bulk': fixed batches;
    bulk request bodies are cached on disk (cache_dir/cache_tag/<batch no>.json, batch no counted from row_base)."""
    rng = random.Random(seed + start)
    i, calls, lat = start, 0, []
    t_start = perf_counter()
    t_report, next_rep, t_build, pts = t_start, start + report_every, 0.0, 0
    while i < end:
        if deadline is not None and perf_counter() > deadline:
            break
        b = rng.randint(*small_range) if mode == 'small' else min(batch, end - i)
        chunk = rows[i:i + b]
        t0 = perf_counter()
        body = None
        cpath = None
        if cache_dir and mode == 'bulk' and (i - row_base) % batch == 0 and len(chunk) == batch:
            cpath = body_cache_path(cache_dir, cache_tag, (i - row_base) // batch)
            if os.path.exists(cpath):
                with open(cpath, 'rb') as f:
                    body = f.read()
        if body is None:
            body = build_batch_body(ds, chunk, dim, id_offset)
            if cpath:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath + '.tmp', 'wb') as f:
                    f.write(body)
                os.replace(cpath + '.tmp', cpath)
        t_build += perf_counter() - t0
        st, data, dt = qd.raw('PUT', f'/collections/{coll}/points?wait=true', body)
        if st != 200:
            raise RuntimeError(f'upsert failed {st}: {data[:300]}')
        lat.append(dt)
        calls += 1
        i += len(chunk)
        pts += len(chunk)
        if report_every and i >= next_rep:
            now = perf_counter()
            log(f'  {tag} ingested {i}/{end} ({report_every / (now - t_report):.0f} pts/s window)')
            t_report = now
            next_rep += report_every
    wall = perf_counter() - t_start
    if not lat:
        return {'points': 0, 'calls': 0}, i
    lat = np.array(lat)
    return {
        'points': pts, 'calls': calls, 'wall_s': wall, 'client_build_s': t_build, 'server_wall_s': float(lat.sum()),
        'points_per_s_total': pts / wall, 'points_per_s_server': pts / float(lat.sum()),
        'calls_per_s_server': calls / float(lat.sum()),
        'call_ms_p50': float(np.percentile(lat, 50) * 1e3), 'call_ms_p95': float(np.percentile(lat, 95) * 1e3),
        'call_ms_p99': float(np.percentile(lat, 99) * 1e3), 'call_ms_max': float(lat.max() * 1e3),
        'mode': mode, 'batch': batch if mode == 'bulk' else f'{small_range[0]}-{small_range[1]}',
    }, i



def ingest(qd, ds, rows, coll=COLL, dim=DIM, mode='bulk', batch=500, small_range=(1, 5), seed=1, limit_points=None,
           report_every=20000, tag='', id_offset=0, cache_dir=None, cache_tag=None):
    """Upsert `rows` (dataset row indices) with wait=true. mode 'bulk' (fixed batch) | 'small' (1-5 points/call,
    NOMAD-style one section per call). In bulk mode request bodies are cached on disk (cache_dir/cache_tag) so every
    variant re-sends byte-identical bodies and the (slow, python) JSON building is paid once."""
    rng = random.Random(seed)
    n = len(rows) if limit_points is None else min(len(rows), limit_points)
    i, calls, lat = 0, 0, []
    t_start = perf_counter()
    t_report = t_start
    next_rep = report_every
    t_build = 0.0
    while i < n:
        b = rng.randint(*small_range) if mode == 'small' else batch
        chunk = rows[i:i + b]
        t0 = perf_counter()
        body = None
        cpath = body_cache_path(cache_dir, cache_tag, i // batch) if (cache_dir and mode == 'bulk') else None
        if cpath and os.path.exists(cpath):
            with open(cpath, 'rb') as f:
                body = f.read()
        if body is None:
            body = build_batch_body(ds, chunk, dim, id_offset)
            if cpath:
                os.makedirs(os.path.dirname(cpath), exist_ok=True)
                with open(cpath + '.tmp', 'wb') as f:
                    f.write(body)
                os.replace(cpath + '.tmp', cpath)
        t_build += perf_counter() - t0
        st, data, dt = qd.raw('PUT', f'/collections/{coll}/points?wait=true', body)
        if st != 200:
            raise RuntimeError(f'upsert failed {st}: {data[:300]}')
        lat.append(dt)
        calls += 1
        i += len(chunk)
        if report_every and i >= next_rep:
            now = perf_counter()
            log(f'  {tag} ingested {i}/{n} ({(report_every / (now - t_report)):.0f} pts/s window)')
            t_report = now
            next_rep += report_every
    wall = perf_counter() - t_start
    lat = np.array(lat)
    return {
        'points': n, 'calls': calls, 'wall_s': wall, 'client_build_s': t_build,
        'server_wall_s': float(lat.sum()),
        'points_per_s_total': n / wall, 'points_per_s_server': n / float(lat.sum()),
        'calls_per_s_server': calls / float(lat.sum()),
        'call_ms_p50': float(np.percentile(lat, 50) * 1e3), 'call_ms_p95': float(np.percentile(lat, 95) * 1e3),
        'call_ms_p99': float(np.percentile(lat, 99) * 1e3), 'call_ms_max': float(lat.max() * 1e3),
        'mode': mode, 'batch': batch if mode == 'bulk' else f'{small_range[0]}-{small_range[1]}',
    }


# ----------------------------------------------------------------------------------
# queries, latency, recall
# ----------------------------------------------------------------------------------
FILTER_V135 = {'must_not': [{'key': 'active', 'match': {'value': False}}]}  # what NOMAD v1.35.0 sends
FILTER_TASK = {'must_not': [{'key': 'collection', 'match': {'value': 'eval'}},
                            {'key': 'active', 'match': {'value': False}}]}  # shape named in the assignment


def query_bodies(qvecs, params=None, filt=FILTER_V135, limit=15, threshold=0.3, with_payload=True):
    out = []
    for v in qvecs:
        b = {'vector': None, 'limit': limit, 'score_threshold': threshold, 'with_payload': with_payload,
             'filter': filt}
        if params:
            b['params'] = params
        s = json.dumps(b)
        s = s.replace('"vector": null', '"vector": ' + vec_json(v), 1)
        out.append(s.encode())
    return out


def run_queries(qd, bodies, coll=COLL, keep=True):
    lat, srv, res = [], [], []
    for b in bodies:
        st, data, dt = qd.raw('POST', f'/collections/{coll}/points/search', b)
        if st != 200:
            raise RuntimeError(f'search failed {st}: {data[:300]}')
        lat.append(dt)
        if keep:
            js = json.loads(data)
            srv.append(js.get('time', 0.0))
            res.append([(h['id'], h['score']) for h in js['result']])
    return np.array(lat), np.array(srv), res


def lat_stats(lat, srv=None):
    d = {'n': int(len(lat)), 'p50_ms': float(np.percentile(lat, 50) * 1e3),
         'p95_ms': float(np.percentile(lat, 95) * 1e3), 'p99_ms': float(np.percentile(lat, 99) * 1e3),
         'mean_ms': float(lat.mean() * 1e3), 'max_ms': float(lat.max() * 1e3)}
    if srv is not None and len(srv):
        d['server_p50_ms'] = float(np.percentile(srv, 50) * 1e3)
        d['server_p95_ms'] = float(np.percentile(srv, 95) * 1e3)
    return d


def recall_at(res, gt_idx, gt_scores, ks=(10, 15), threshold=0.3):
    """res: list (per query) of [(uuid, score)]; gt_idx/gt_scores: (Q,K) exact top-K rows/scores."""
    out = {}
    for k in ks:
        vals = []
        for q, hits in enumerate(res):
            gt = gt_idx[q][:k][gt_scores[q][:k] >= threshold]
            if len(gt) == 0:
                continue
            got = {uuid_row(h[0]) for h in hits[:k]}
            vals.append(len(got & set(gt.tolist())) / len(gt))
        out[f'recall@{k}'] = float(np.mean(vals)) if vals else None
        out[f'recall@{k}_min'] = float(np.min(vals)) if vals else None
    out['mean_hits'] = float(np.mean([len(h) for h in res]))
    return out


def exact_topk(mm, rows, qvecs, k=15, block=20000):
    """Exact cosine top-k of qvecs over dataset rows (numpy brute force). Returns (idx rows, scores)."""
    qn = qvecs / np.linalg.norm(qvecs, axis=1, keepdims=True)
    best_s = np.full((len(qvecs), k), -2.0, dtype=np.float32)
    best_i = np.full((len(qvecs), k), -1, dtype=np.int64)
    rows = np.asarray(rows)
    for s in range(0, len(rows), block):
        r = rows[s:s + block]
        order = np.argsort(r)
        v = np.empty((len(r), mm.shape[1]), dtype=np.float32)
        v[order] = mm[r[order]]
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        sc = qn @ v.T
        kk = min(k, sc.shape[1])
        part = np.argpartition(-sc, kk - 1, axis=1)[:, :kk]
        ps = np.take_along_axis(sc, part, axis=1)
        ci = np.concatenate([best_i, r[part]], axis=1)
        cs = np.concatenate([best_s, ps], axis=1)
        top = np.argsort(-cs, axis=1)[:, :k]
        best_i = np.take_along_axis(ci, top, axis=1)
        best_s = np.take_along_axis(cs, top, axis=1)
    return best_i, best_s


def dump(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=1, default=str)
