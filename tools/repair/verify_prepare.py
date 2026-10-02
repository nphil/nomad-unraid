#!/usr/bin/env python3
"""Embed verification queries with the production nomic endpoint (NOMAD's prefix). Runs anywhere with network to llama-swap."""
import json, urllib.request
BASE = "http://192.168.1.69:9292"
Q = [("orig-boil", "how long should I boil water to make it safe to drink"), ("diy-switch", "how do I wire a three-way light switch"),
     ("electronics-reg", "why does my linear voltage regulator get so hot"), ("ifixit-battery", "how to replace the battery in an iPhone 8"),
     ("medicine-bp", "what are the symptoms of high blood pressure"), ("wikibooks-python", "python list comprehension tutorial"),
     ("wikipedia-napoleon", "who was Napoleon Bonaparte"), ("arduino-pwm", "arduino pwm frequency change timer"),
     ("cooking-cast-iron", "how do I season a cast iron skillet"), ("gutenberg", "a story about a whaling ship and a white whale")]
out = []
for name, q in Q:
    body = {"model": "nomic-embed-text:v1.5", "input": ["search_query: " + q], "encoding_format": "float"}
    req = urllib.request.Request(BASE + "/v1/embeddings", data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    out.append({"name": name, "text": q, "vec": json.load(urllib.request.urlopen(req, timeout=120))["data"][0]["embedding"]})
import os
OUT = next(d for d in ("/mnt/nvme/appdata/cody/home/tmp/nomadindex/repair/results", "/data/home/tmp/nomadindex/repair/results") if os.path.isdir(d)) + "/verify_queries.json"
json.dump(out, open(OUT, "w")); print("embedded", len(out), "queries, dim", len(out[0]["vec"]))
