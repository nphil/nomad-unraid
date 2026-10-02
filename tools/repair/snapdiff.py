#!/usr/bin/env python3
"""What did a ZFS snapshot end up pinning? usage: snapdiff.py <dataset> <mountpoint> <snapname>
Lists files removed / modified / created since the snapshot. Removed files are fully pinned by the snapshot (size read from the snapshot copy);
modified files are only partly pinned (their size is an upper bound)."""
import collections, os, subprocess, sys
ds, mp, snap = sys.argv[1:4]
out = subprocess.run(["zfs", "diff", "-H", f"{ds}@{snap}", ds], capture_output=True, text=True).stdout.splitlines()
cnt = collections.Counter(); size = collections.Counter(); cat = collections.Counter(); upper = collections.Counter()
def category(rel):
    parts = rel.split("/")
    if "wal" in parts: return "wal"
    if "segments" in parts:
        i = parts.index("segments"); return "segment " + (parts[i + 1][:8] if len(parts) > i + 1 else "?")
    return "other (" + parts[0] + ")"
for line in out:
    f = line.split("\t")
    if len(f) < 2: continue
    kind, path = f[0], f[-1]; rel = os.path.relpath(path, mp)
    if os.path.isdir(path) and kind in ("M", "+"): continue
    cnt[kind] += 1
    if kind == "-":
        try: sz = os.stat(f"{mp}/.zfs/snapshot/{snap}/{rel}").st_size
        except OSError: sz = 0
        if os.path.isdir(f"{mp}/.zfs/snapshot/{snap}/{rel}"): continue
        size["-"] += sz; cat[category(rel)] += sz
    elif kind == "M":
        try: sz = os.stat(path).st_size
        except OSError: sz = 0
        upper["M"] += sz
        if sz: cat["modified: " + category(rel)] += 0; upper[category(rel)] += sz
print("files by change type (since @%s): %s" % (snap, dict(cnt)))
print("removed files (fully pinned by the snapshot): %.0f MB" % (size["-"] / 1e6))
print("modified files, total size (upper bound of what is pinned): %.0f MB" % (upper["M"] / 1e6))
print("top removed by category:", [(k, round(v / 1e6)) for k, v in cat.most_common(8) if v and not k.startswith("modified")])
print("top modified by category (size, upper bound):", [(k, round(v / 1e6)) for k, v in upper.most_common(9) if k != "M"][:8])
