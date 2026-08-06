#!/usr/bin/env python3
"""Download a (Plaud) audio URL and transcribe it locally with Whisper.

Presigned URLs expire fast — call this IMMEDIATELY after obtaining the URL.

Usage:
  python3 whisper_transcribe.py --url "<presigned_url>" --id <file_id> --out <dir> [--lang auto]
  python3 whisper_transcribe.py --audio <local.mp3>     --id <file_id> --out <dir> [--lang auto]

Output: <out>/<id>.json  = {"id", "text", "segments":[{"start": sec, "text": ...}]}
Engine: mlx_whisper (Apple Silicon) → openai-whisper (fallback).
Language: --lang auto (default) detects the language from MID-FILE samples (20/50/80%),
never from the first 30s (intros/music routinely fool detection into ja/ko hallucination
loops). Pass an explicit code (ko/en/ja/...) only when you know the language.
A repetition sanity check warns when the output looks like a hallucination loop.
Already-existing output files are skipped (safe to rerun/resume).
"""
import argparse, json, os, platform, subprocess, sys, tempfile

def log(msg):
    print(msg, flush=True)

def download(url: str, dest: str) -> None:
    r = subprocess.run(["curl", "-sL", "--max-time", "600", "-o", dest, url])
    if r.returncode != 0 or not os.path.exists(dest):
        sys.exit(f"ERROR: download failed (curl rc={r.returncode})")
    size = os.path.getsize(dest)
    head = open(dest, "rb").read(200)
    if size < 1_000_000 and (head.startswith(b"<?xml") or b"ExpiredToken" in head or b"<Error>" in head):
        sys.exit("ERROR: presigned URL expired (got XML error, not audio). "
                 "Re-fetch the URL with get_file and download IMMEDIATELY.")
    if size < 100_000:
        sys.exit(f"ERROR: downloaded file too small ({size} bytes) — probably not valid audio.")
    log(f"downloaded {size // 1024 // 1024}MB")


def detect_language(audio: str) -> str:
    """Detect language by transcribing three 30s MID-FILE samples and majority-voting.
    The first 30s of meeting audio (silence/music/greetings) routinely fools
    single-shot detection — mid-file speech is far more reliable."""
    try:
        dur = float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", audio], capture_output=True, text=True).stdout.strip())
    except (ValueError, FileNotFoundError):
        dur = 0
    if dur >= 120:
        offsets = [int(dur * f) for f in (0.2, 0.5, 0.8)]
    elif dur > 0:
        offsets = [int(dur * 0.5)]
    else:
        # duration unknown (no ffprobe) — fixed mid-file guesses; failed clips just skip
        offsets = [60, 300, 900]
    votes = []
    for off in offsets:
        clip = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        clip.close()
        try:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(off),
                            "-t", "30", "-i", audio, "-ac", "1", "-ar", "16000", clip.name],
                           stdin=subprocess.DEVNULL, check=True)
            res = transcribe(clip.name, None)
            lg = res.get("language")
            if lg:
                votes.append(lg)
        except Exception:
            pass
        finally:
            os.remove(clip.name)
    if not votes:
        return None
    win = max(set(votes), key=votes.count)
    log(f"language detected: {win} (votes: {votes})")
    return win

def repetition_ratio(segs) -> float:
    """Fraction of segments that repeat their predecessor — hallucination smell."""
    texts = [s["text"] for s in segs if s.get("text")]
    if len(texts) < 10:
        return 0.0
    rep = sum(1 for a, b in zip(texts, texts[1:]) if a == b or (len(a) > 6 and a in b))
    return rep / len(texts)

def transcribe(audio: str, lang: str):
    # 1) mlx_whisper — fast on Apple Silicon GPUs
    try:
        import mlx_whisper  # type: ignore
        log("engine: mlx_whisper (large-v3-turbo)")
        # condition_on_previous_text=False stops runaway hallucination loops
        # (repeated tokens like "drains drains…") on noisy/low-mic audio — the
        # decoder no longer feeds a garbled prior back into itself.
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
            language=lang, condition_on_previous_text=False)
    except ImportError:
        pass
    # 2) openai-whisper — portable fallback
    try:
        import whisper  # type: ignore
        log("engine: openai-whisper (medium)")
        model = whisper.load_model("medium")
        return model.transcribe(audio, language=lang)
    except ImportError:
        pass
    arm_mac = platform.system() == "Darwin" and platform.machine() == "arm64"
    hint = "pip3 install mlx-whisper" if arm_mac else "pip3 install openai-whisper"
    sys.exit(f"ERROR: no whisper engine installed. Install one first:\n  {hint}\n"
             "(ffmpeg is also required: brew install ffmpeg / apt install ffmpeg)")

def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="presigned audio URL (downloaded immediately)")
    src.add_argument("--audio", help="local audio file path")
    ap.add_argument("--id", required=True, help="recording id (output filename)")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--lang", default="auto", help="language code, or 'auto' for mid-file sample detection (default: auto)")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    outp = os.path.join(a.out, f"{a.id}.json")
    if os.path.exists(outp):
        log(f"skip: {outp} already exists")
        return

    tmp = None
    audio = a.audio
    try:
        if a.url:
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.close()
            audio = tmp.name
            download(a.url, audio)
        lang = a.lang
        if lang == "auto":
            lang = detect_language(audio)
        res = transcribe(audio, lang)
        segs = [{"start": round(s["start"], 1), "end": round(s.get("end", s["start"]), 1),
                 "text": s["text"].strip()}
                for s in res.get("segments", [])]
        rr = repetition_ratio(segs)
        if rr > 0.3:
            log(f"WARNING: repetition ratio {rr:.0%} — output may be a hallucination loop. "
                f"Language used: {lang}. Re-run with an explicit --lang of the actual "
                f"spoken language and compare.")
        json.dump({"id": a.id, "text": res.get("text", ""),
                   "language": lang, "repetition_ratio": round(rr, 3),
                   "segments": segs},
                  open(outp, "w"), ensure_ascii=False)
        log(f"OK: {outp} ({len(segs)} segments, lang={lang})")
    finally:
        if tmp and os.path.exists(tmp.name):
            os.remove(tmp.name)

if __name__ == "__main__":
    main()
