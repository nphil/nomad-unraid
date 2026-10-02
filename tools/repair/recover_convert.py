#!/usr/bin/env python3
"""Rebuild the lost id table of NOMAD's big Qdrant segment from the optimizer's leftover builder folder.

Usage: recover_convert.py <dest segment dir>   (run on the Unraid host; reads only, from the pristine array copy)

Facts (verified before writing this):
  * builder id_tracker.mappings = immutable format: u64 count, then per point 1 type byte (1=uuid) + 16 uuid bytes + u32 internal id.
  * Qdrant 1.16.3 mutable id tracker (what a plain, appendable segment loads) = append-only file of records
    type byte (2=InsertUuid) + 16 uuid bytes + u32 internal id, little endian. Versions = u64 per internal id (same as the builder's).
  * builder internal id == entry index for all 3,989,177 entries, all ids unique, nothing deleted, all versions 2472778.
"""
import json, os, shutil, struct, sys

OLD = "/mnt/disk2/Stash/Nomad/qdrant/collections/nomad_knowledge_base/0"
B2 = OLD + "/temp_segments.HOLD-builder-DO-NOT-DELETE/segment_builder_n3vl4Q"
STALE = OLD + "/segments/c98bf53f-759c-4d00-9749-5b1c1fcf4033"
dest = sys.argv[1]
os.makedirs(dest + "/payload_index", exist_ok=True)

with open(B2 + "/id_tracker.mappings", "rb") as f:
    n = struct.unpack("<Q", f.read(8))[0]
    data = f.read()
assert len(data) == n * 21, (len(data), n)
buf = bytearray(data)
assert set(buf[0::21]) == {1}, "unexpected id type bytes"
# internal ids must be 0..n-1 in order (so that the builder's vector/payload storages line up with them)
for i in range(0, n, 250000):
    j = min(i + 250000, n)
    for k in range(i, j):
        assert struct.unpack_from("<I", buf, k * 21 + 17)[0] == k, ("internal id mismatch at", k)
dele = open(B2 + "/id_tracker.deleted", "rb").read()
assert sum(bin(b).count("1") for b in dele) == 0, "builder has deleted points; conversion would need Delete records"
buf[0::21] = b"\x02" * n  # immutable 'uuid' (1)  ->  mutable 'InsertUuid' (2)
vsize = os.path.getsize(B2 + "/id_tracker.versions")
assert vsize == n * 8, (vsize, n)

with open(dest + "/mutable_id_tracker.mappings", "wb") as f:
    f.write(buf); f.flush(); os.fsync(f.fileno())
shutil.copyfile(B2 + "/id_tracker.versions", dest + "/mutable_id_tracker.versions")
shutil.copyfile(STALE + "/payload_index/config.json", dest + "/payload_index/config.json")  # appendable index types, fields: content_type, source, active, collection
seg = json.load(open(STALE + "/segment.json"))
assert seg["config"]["vector_data"][""]["index"]["type"] == "plain" and seg["version"] == 2472778
json.dump(seg, open(dest + "/segment.json", "w"), separators=(",", ":"))
# version.info last: Qdrant skips a segment without it (proves the segment was fully written)
shutil.copyfile(STALE + "/version.info", dest + "/version.info")
for p in ("mutable_id_tracker.mappings", "mutable_id_tracker.versions", "segment.json", "version.info"):
    print("wrote", p, os.path.getsize(dest + "/" + p))
print("points:", n)
