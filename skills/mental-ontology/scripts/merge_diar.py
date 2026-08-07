#!/usr/bin/env python3
"""Merge a Whisper transcript with diarization regions into a labeled transcript.

For each Whisper segment, assigns the speaker whose diarization region overlaps it
most (falls back to nearest region), then coalesces consecutive same-speaker
segments and collapses runaway token repeats. Tolerates transcripts without "end".

Usage:  python3 merge_diar.py <whisper.json> <diar_re.json from recluster.py> <out.txt>
Output: lines like "[MM:SS - MM:SS] Speaker N: <utterance>" (relabel N→names afterward).
No third-party deps.
"""
import sys, json, re
wj, dj, out = sys.argv[1], sys.argv[2], sys.argv[3]
wsegs = json.load(open(wj))["segments"]
for i, w in enumerate(wsegs):  # tolerate transcripts without "end"
    if "end" not in w:
        w["end"] = wsegs[i+1]["start"] if i+1 < len(wsegs) else w["start"] + 5.0
dsegs = json.load(open(dj))
def fmt(t):
    t = int(t); h, m, s = t//3600, (t%3600)//60, t%60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
def collapse(text):
    return re.sub(r"((\S{1,8})([.,]?\s+))(?:\2\3){4,}", r"\1\1\2 … ", text)
def pick(s, e):
    best, ov = None, 0.0
    for d in dsegs:
        o = min(e, d["end"]) - max(s, d["start"])
        if o > ov: best, ov = d["speaker"], o
    if best is None and dsegs:
        mid = (s+e)/2
        best = min(dsegs, key=lambda d: min(abs(mid-d["start"]), abs(mid-d["end"])))["speaker"]
    return best or 0
blocks = []
for w in wsegs:
    text = collapse(w["text"].strip())
    if not text: continue
    spk = pick(w["start"], w["end"])
    if blocks and blocks[-1][2]==spk and w["start"]-blocks[-1][1] < 3.0:
        blocks[-1][1] = w["end"]; blocks[-1][3] += " " + text
    else:
        blocks.append([w["start"], w["end"], spk, text])
with open(out, "w") as f:
    for s, e, spk, text in blocks:
        f.write(f"[{fmt(s)} - {fmt(e)}] Speaker {spk+1}: {text}\n")
print(out, len(blocks), "turns")
