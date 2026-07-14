#!/usr/bin/env python3
"""Download a (Plaud) audio URL and transcribe it locally with Whisper.

Presigned URLs expire fast — call this IMMEDIATELY after obtaining the URL.

Usage:
  python3 whisper_transcribe.py --url "<presigned_url>" --id <file_id> --out <dir> [--lang ko]
  python3 whisper_transcribe.py --audio <local.mp3>     --id <file_id> --out <dir> [--lang ko]

Output: <out>/<id>.json  = {"id", "text", "segments":[{"start": sec, "text": ...}]}
Engine: mlx_whisper (Apple Silicon) → openai-whisper (fallback).
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

def transcribe(audio: str, lang: str):
    # 1) mlx_whisper — fast on Apple Silicon GPUs
    try:
        import mlx_whisper  # type: ignore
        log("engine: mlx_whisper (large-v3-turbo)")
        return mlx_whisper.transcribe(
            audio, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language=lang)
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
    ap.add_argument("--lang", default="ko", help="language code (default: ko)")
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
        res = transcribe(audio, a.lang)
        segs = [{"start": round(s["start"], 1), "text": s["text"].strip()}
                for s in res.get("segments", [])]
        json.dump({"id": a.id, "text": res.get("text", ""), "segments": segs},
                  open(outp, "w"), ensure_ascii=False)
        log(f"OK: {outp} ({len(segs)} segments)")
    finally:
        if tmp and os.path.exists(tmp.name):
            os.remove(tmp.name)

if __name__ == "__main__":
    main()
