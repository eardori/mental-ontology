#!/usr/bin/env python3
"""Local speaker diarization (sherpa-onnx) — first pass over a 16kHz mono WAV.

Runs pyannote-segmentation-3.0 + campplus embeddings to produce speaker regions.
Its default clustering over-segments on 2-person calls, so treat this as a first
pass and refine with recluster.py (length-weighted agglomerative, cosine 0.45).

Usage:  python3 diarize.py <in.wav 16kHz mono> <out.json> [seg_threshold=0.5]
Output: [{"start","end","speaker"}, ...]

Models: place the sherpa-onnx models under a dir resolved (in order) from
env DIAR_MODELS, ~/.cache/mental-ontology/diar-models, or ~/.cache/onda-diar/models. Needs: sherpa-onnx-pyannote-segmentation-3-0/model.onnx
and campplus.onnx. Deps: sherpa-onnx, soundfile, numpy.
"""
import sys, json, os
import numpy as np
import soundfile as sf
import sherpa_onnx
wav_path, out_path = sys.argv[1], sys.argv[2]
threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
base = (os.environ.get("DIAR_MODELS")
        or next((p for p in [os.path.expanduser("~/.cache/mental-ontology/diar-models"),
                             os.path.expanduser("~/.cache/onda-diar/models")] if os.path.isdir(p)),
                os.path.expanduser("~/.cache/mental-ontology/diar-models")))
samples, sr = sf.read(wav_path, dtype="float32")
if samples.ndim > 1: samples = samples.mean(axis=1)
assert sr == 16000
config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
    segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=f"{base}/sherpa-onnx-pyannote-segmentation-3-0/model.onnx"), num_threads=8),
    embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=f"{base}/campplus.onnx", num_threads=8),
    clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=threshold),
    min_duration_on=0.3, min_duration_off=0.5)
assert config.validate()
sd = sherpa_onnx.OfflineSpeakerDiarization(config)
segments = sd.process(samples).sort_by_start_time()
json.dump([{"start": s.start, "end": s.end, "speaker": s.speaker} for s in segments], open(out_path, "w"))
print(out_path, len(segments), "segments")
