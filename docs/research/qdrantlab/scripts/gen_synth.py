#!/usr/bin/env python3
"""Synthetic NOMAD-shaped dataset: unit-norm 768-d clustered vectors + ZIM-chunk-like payloads.

Output (same format as the real dataset from NomadZimStats/NomadIndexAgent):
  <out>_vectors.f32   float32 little endian, shape [N, 768]
  <out>_chunks.jsonl  one payload JSON object per line (row i = line i)

Vectors are *clustered with low-rank noise and a shared mean direction* (like real sentence embeddings:
neighbours at cosine 0.5-0.8, random pairs ~0.2) so that score_threshold 0.3 behaves like in production.
They are NOT used for quantisation-recall conclusions (real vectors are used for that).
"""
import argparse
import json
import random
import sys
import time
import uuid

import numpy as np

STOP = ('the of and to in is was for as on with by that this it from at are were be an or which has have had not '
        'but also their its his her they he she we you i can will would may more other than into most such these '
        'those been there when who what where how about after before over between under during each some any all '
        'both only own same so very just then them our your out up down off again further once here why do does '
        'did doing because until while above below through against being having').split()

ARCHIVES = [
    ('wikipedia_en_all_maxi_2026-02.zim', 'Wikipedia', 'Wikipedia', 'Kiwix', '2026-02-04', 'eng',
     'Wikipedia is a free online encyclopedia, created and edited by volunteers around the world and hosted by the '
     'Wikimedia Foundation. Offline copy with images for Kiwix readers.'),
    ('wikibooks_en_all_maxi_2026-01.zim', 'Wikibooks', 'Wikibooks', 'Kiwix', '2026-01-18', 'eng',
     'Wikibooks is a Wikimedia community for creating open-content textbooks and manuals that anyone can edit.'),
    ('wikipedia_en_medicine_maxi_2026-01.zim', 'Wikipedia (Medicine)', 'Wikipedia', 'Kiwix', '2026-01-11', 'eng',
     'Medical articles from English Wikipedia selected by WikiProject Medicine, packaged for offline reading.'),
    ('diy.stackexchange.com_en_all_2026-08.zim', 'Home Improvement Stack Exchange', 'Stack Exchange', 'Kiwix',
     '2026-08-14', 'eng',
     'Questions and answers for contractors and serious DIYers: home repair, construction, plumbing, wiring and tools.'),
    ('electronics.stackexchange.com_en_all_2026-08.zim', 'Electrical Engineering Stack Exchange', 'Stack Exchange',
     'Kiwix', '2026-08-14', 'eng',
     'Questions and answers for electronics and electrical engineering professionals, students, and enthusiasts.'),
    ('ifixit_en_all_2025-12.zim', 'iFixit', 'iFixit', 'Kiwix', '2025-12-03', 'eng',
     'Repair guides for everything, written by everyone: phones, laptops, appliances, cars and more.'),
    ('raspberrypi.stackexchange.com_en_all_2026-08.zim', 'Raspberry Pi Stack Exchange', 'Stack Exchange', 'Kiwix',
     '2026-08-14', 'eng', 'Questions and answers for users and developers of hardware and software for Raspberry Pi.'),
    ('mechanics.stackexchange.com_en_all_2026-08.zim', 'Motor Vehicle Maintenance & Repair Stack Exchange',
     'Stack Exchange', 'Kiwix', '2026-08-14', 'eng',
     'Questions and answers for mechanics and DIY enthusiasts to discuss vehicle maintenance and repair.'),
]
ARCH_W = [60, 6, 8, 5, 5, 4, 3, 3]
SECTIONS = ['Overview', 'History', 'Description', 'Background', 'Applications', 'Reception', 'Etymology', 'Usage',
            'Properties', 'Design', 'Troubleshooting', 'Answer', 'Question', 'Step 1', 'Legacy', 'Variants']


def make_vocab(rng, n):
    cons = ['b', 'c', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm', 'n', 'p', 'r', 's', 't', 'v', 'w', 'th', 'ch', 'sh',
            'st', 'tr', 'pr', 'gr', 'cl', 'br', 'pl', 'sp', 'qu']
    vow = ['a', 'e', 'i', 'o', 'u', 'ea', 'ou', 'io', 'ai', 'ee', 'oo', 'ia']
    words = set()
    out = []
    while len(out) < n:
        k = int(rng.choice([1, 2, 2, 3, 3, 4]))
        w = ''.join(rng.choice(cons) + rng.choice(vow) for _ in range(k))
        if rng.random() < 0.4:
            w += rng.choice(['n', 's', 'r', 't', 'l', 'd', 'ng', 'nt', 'st'])
        if len(w) > 2 and w not in words:
            words.add(w)
            out.append(w)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=1_001_000)
    ap.add_argument('--out', default='/data/home/tmp/nomadindex/qdrantlab/work/syn')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--clusters', type=int, default=3000)
    ap.add_argument('--rank', type=int, default=96)
    ap.add_argument('--text-median', type=float, default=700)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    rnd = random.Random(a.seed)

    D = 768
    U, _ = np.linalg.qr(rng.standard_normal((D, a.rank)))
    U = U.astype(np.float32)
    mean_dir = rng.standard_normal(D).astype(np.float32)
    mean_dir /= np.linalg.norm(mean_dir)
    centers = rng.standard_normal((a.clusters, D)).astype(np.float32)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)

    vocab = STOP + make_vocab(np.random.RandomState(a.seed), 40000)
    cum = np.cumsum(1.0 / (np.arange(len(vocab)) + 2.0) ** 1.02)
    cum = (cum / cum[-1]).tolist()
    stopset = set(STOP)
    titles_vocab = vocab[len(STOP) + 200:len(STOP) + 20000]

    t0 = time.time()
    vf = open(a.out + '_vectors.f32', 'wb')
    cf = open(a.out + '_chunks.jsonl', 'w')
    n_done, doc = 0, None
    sizes, tlens, klens = [], [], []
    BLK = 50000
    created = 1790000000000
    while n_done < a.n:
        m = min(BLK, a.n - n_done)
        k = rng.integers(0, a.clusters, size=m)
        z = rng.standard_normal((m, a.rank)).astype(np.float32) @ U.T
        z /= np.linalg.norm(z, axis=1, keepdims=True)
        x = 0.45 * mean_dir + 0.75 * centers[k] + 0.50 * z
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        vf.write(x.astype('<f4').tobytes())
        for i in range(m):
            if doc is None or doc['left'] == 0:
                arch = rnd.choices(range(len(ARCHIVES)), weights=ARCH_W)[0]
                nchunks = rnd.choice([1, 1, 1, 2, 2, 3, 4, 6, 9])
                title = ' '.join(rnd.choice(titles_vocab) for _ in range(rnd.randint(1, 4))).title()
                doc = {'arch': arch, 'n': nchunks, 'left': nchunks, 'title': title, 'id': str(uuid.UUID(int=rnd.getrandbits(128), version=4)),
                       'path': title.replace(' ', '_'), 'strategy': 'structured' if nchunks > 1 else 'simple'}
            ci = doc['n'] - doc['left']
            doc['left'] -= 1
            L = int(min(3000, max(300, rnd.lognormvariate(np.log(a.text_median), 0.75))))
            words, tot = [], 0
            ws = rnd.choices(vocab, cum_weights=cum, k=int(L / 5.2) + 40)
            sent, paras, cur = 0, [], []
            for w in ws:
                if tot >= L:
                    break
                if not cur:
                    w = w.capitalize()
                cur.append(w)
                tot += len(w) + 1
                if len(cur) >= rnd.randint(8, 22):
                    paras.append(' '.join(cur) + '.')
                    cur = []
                    sent += 1
            if cur:
                paras.append(' '.join(cur) + '.')
            text = ''
            for j, s in enumerate(paras):
                text += s + (('\n\n' if (j + 1) % 4 == 0 else ' ') if j + 1 < len(paras) else '')
            text = text.strip()
            sect = rnd.choice(SECTIONS) if ci or doc['n'] > 1 else 'Introduction'
            arch = ARCHIVES[doc['arch']]
            kw, seen = [], set()
            for tok in (doc['title'] + ' ' + text).split(' '):
                t = ''.join(ch for ch in tok if ch.isalnum() or ch == '_').lower()
                if len(t) > 2 and t not in stopset and t not in seen:
                    seen.add(t)
                    kw.append(t)
            payload = {
                'source': '/app/storage/zim/' + arch[0],
                'content_type': 'zim_article',
                'article_title': doc['title'],
                'article_path': doc['path'],
                'section_title': sect,
                'full_title': f"{doc['title']} - {sect}",
                'hierarchy': f"{doc['title']} > {sect}",
                'section_level': rnd.choice([2, 2, 3, 3, 4]),
                'document_id': doc['id'],
                'archive_title': arch[1], 'archive_creator': arch[2], 'archive_publisher': arch[3],
                'archive_date': arch[4], 'archive_language': arch[5], 'archive_description': arch[6],
                'extraction_strategy': doc['strategy'],
                'text': text, 'chunk_index': ci, 'total_chunks': doc['n'],
                'keywords': ' '.join(kw), 'char_count': len(text), 'created_at': created + rnd.randint(0, 10**9),
                'active': True,
            }
            s = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            cf.write(s + '\n')
            sizes.append(len(s.encode()))
            tlens.append(len(text))
            klens.append(len(payload['keywords']))
        n_done += m
        print(f'{n_done}/{a.n} rows  {time.time() - t0:.0f}s  mean_json={np.mean(sizes):.0f}B', flush=True)
    vf.close()
    cf.close()
    meta = {'rows': n_done, 'mean_payload_json_bytes': float(np.mean(sizes)), 'p50_payload_json_bytes': float(np.median(sizes)),
            'mean_text_chars': float(np.mean(tlens)), 'mean_keywords_chars': float(np.mean(klens)), 'seed': a.seed,
            'clusters': a.clusters, 'rank': a.rank}
    json.dump(meta, open(a.out + '_meta.json', 'w'), indent=1)
    print(meta)


if __name__ == '__main__':
    main()
