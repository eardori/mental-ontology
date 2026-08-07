#!/usr/bin/env python3
"""Re-cluster diarize.py regions with length-weighted agglomerative clustering.

sherpa's default clustering over-splits (e.g. 40 speakers on a 2-person call).
This re-embeds each region with campplus and re-clusters with cosine distance
(threshold 0.45 works well for Korean; lower = more speakers), dropping regions
shorter than MIN_DUR and absorbing tiny minority clusters. Output matches
diarize.py's schema so merge_diar.py can consume it.

Usage:  python3 recluster.py <in.wav 16kHz mono> <regions.json from diarize.py> <out.json> [cosine_threshold=0.45]
Models: same resolution as diarize.py (env DIAR_MODELS / ~/.cache/mental-ontology/diar-models / ~/.cache/onda-diar/models). Needs campplus.onnx.
Deps: sherpa-onnx, soundfile, numpy, scikit-learn.
"""
import sys, json, os
import numpy as np
import soundfile as sf
import sherpa_onnx
from sklearn.cluster import AgglomerativeClustering
wav_path, regions_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
dist_th = float(sys.argv[4]) if len(sys.argv) > 4 else 0.45
MIN_DUR = 1.5
base = (os.environ.get("DIAR_MODELS")
        or next((p for p in [os.path.expanduser("~/.cache/mental-ontology/diar-models"),
                             os.path.expanduser("~/.cache/onda-diar/models")] if os.path.isdir(p)),
                os.path.expanduser("~/.cache/mental-ontology/diar-models")))
samples, sr = sf.read(wav_path, dtype="float32")
if samples.ndim > 1: samples = samples.mean(axis=1)
regions = json.load(open(regions_json))
ex = sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=f"{base}/campplus.onnx", num_threads=8))
embs, durs = [], []
for r in regions:
    seg = samples[int(r["start"]*sr):int(r["end"]*sr)]
    st = ex.create_stream(); st.accept_waveform(sr, seg); st.input_finished()
    e = np.array(ex.compute(st), dtype=np.float32); n = np.linalg.norm(e)
    embs.append(e/n if n > 0 else e); durs.append(r["end"]-r["start"])
embs, durs = np.stack(embs), np.array(durs)
long_idx = np.where(durs >= MIN_DUR)[0]
if len(long_idx) < 2: long_idx = np.arange(len(embs))
labels_long = AgglomerativeClustering(n_clusters=None, distance_threshold=dist_th, metric="cosine", linkage="average").fit_predict(embs[long_idx])
n_c = labels_long.max()+1
cents = np.zeros((n_c, embs.shape[1]), dtype=np.float32)
for c in range(n_c):
    idx = long_idx[labels_long == c]; w = durs[idx]
    cents[c] = (embs[idx]*w[:,None]).sum(0)/w.sum(); cents[c] /= (np.linalg.norm(cents[c]) or 1.0)
labels = (embs @ cents.T).argmax(1)
talk = np.array([durs[labels==c].sum() for c in range(n_c)])
major = np.where(talk >= max(8.0, 0.02*durs.sum()))[0]
if len(major)==0: major = np.array([talk.argmax()])
sim = cents @ cents[major].T
remap = {c: int(major[sim[c].argmax()]) for c in range(n_c)}
labels = np.array([remap[l] for l in labels])
lab_of = {int(c): i for i, c in enumerate(major)}
labels = np.array([lab_of[int(l)] for l in labels])
tot = [(durs[labels==i].sum(), i) for i in range(len(major))]
order = {c: i for i, (_, c) in enumerate(sorted(tot, reverse=True))}
json.dump([{"start": r["start"], "end": r["end"], "speaker": int(order[labels[i]])} for i, r in enumerate(regions)], open(out_path, "w"))
print(out_path, len(regions), "segs", len(major), "speakers")
