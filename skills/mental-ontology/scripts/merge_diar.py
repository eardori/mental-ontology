#!/usr/bin/env python3
"""Merge a Whisper transcript with diarization regions into a labeled transcript.

For each Whisper segment, assigns the speaker whose diarization region overlaps it
most (falls back to nearest region), then coalesces consecutive same-speaker
segments and collapses runaway token repeats. Tolerates transcripts without "end".

Usage:  python3 merge_diar.py <whisper.json> <diar_re.json from recluster.py> <out.txt>
                             [--labels labels.json from voiceprint.py identify]
Output: lines like "[MM:SS - MM:SS] Speaker N: <utterance>". With --labels, clusters
that voiceprint.py identified with `decision: auto` are written as the real name
instead ("[12:03 - 12:18] 정우진: ..."); everything else stays "Speaker N" for
Stage 3 to ask about. No third-party deps.
"""
import sys, json, re
argv, names = sys.argv[1:], {}
if "--labels" in argv:
    i = argv.index("--labels")
    if i + 1 >= len(argv):
        sys.exit("ERROR: --labels 뒤에 labels.json 경로가 필요합니다.")
    lab = json.load(open(argv[i + 1], encoding="utf-8"))
    names = {str(k): v for k, v in (lab.get("auto") or {}).items() if v}
    del argv[i:i + 2]          # so the flag never eats a positional slot
# A typo'd flag must not degrade into "everything is Speaker N, exit 0" — that looks
# exactly like a voiceprint step that ran and found nobody.
bad = [a for a in argv if a.startswith("--")]
if bad:
    sys.exit(f"ERROR: 알 수 없는 옵션 {bad} (지원: --labels <labels.json>)")
if len(argv) < 3:
    sys.exit("Usage: merge_diar.py <whisper.json> <diar_re.json> <out.txt> "
             "[--labels labels.json]")
wj, dj, out = argv[:3]
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
with open(out, "w", encoding="utf-8") as f:
    for s, e, spk, text in blocks:
        who = names.get(str(spk)) or f"Speaker {spk+1}"
        f.write(f"[{fmt(s)} - {fmt(e)}] {who}: {text}\n")
named = sorted({names[str(b[2])] for b in blocks if str(b[2]) in names})
print(out, len(blocks), "turns" + (f" · 자동 라벨: {', '.join(named)}" if named else ""))
