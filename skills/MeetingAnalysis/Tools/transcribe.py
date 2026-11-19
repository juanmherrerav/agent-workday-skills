#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["faster-whisper>=1.1", "av>=14,<16"]  # av 19 dropped open(metadata_errors=) that faster-whisper passes
# ///
"""Transcribe one recording locally with faster-whisper. No ffmpeg needed.

faster-whisper decodes audio and video containers itself (PyAV). Backend order: CUDA, then Apple
MPS, then CPU int8. Rough speeds with large-v3-turbo: CUDA 10-25x realtime, Apple MPS ~2x,
CPU int8 ~0.5x (a one-hour meeting takes about two hours).

Usage:
    transcribe.py RECORDING --out-base DIR/transcript [--lang auto|en|es|...] [--model turbo|large-v3]

Writes <out-base>.txt ("[MM:SS] text" lines) and <out-base>.jsonl (one segment per line) and
prints one JSON line with duration, language, segment count and device. Exit 0 only when the
transcript is non-empty.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

MODELS = {
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
}


def stamp(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--out-base", type=Path, required=True)
    ap.add_argument("--lang", default="auto", help="auto (per-file detection), en, es, ...")
    ap.add_argument("--model", default="turbo", choices=sorted(MODELS))
    args = ap.parse_args()

    if not args.source.is_file():
        print(f"error: no such file: {args.source}", file=sys.stderr)
        return 1

    from faster_whisper import WhisperModel

    import ctranslate2

    backends = []
    if ctranslate2.get_cuda_device_count() > 0:
        backends.append(("cuda", "float16"))
    if sys.platform == "darwin":
        backends.append(("mps", "float16"))
    backends.append(("cpu", "int8"))

    t0 = time.time()
    for device, compute in backends:
        try:
            model = WhisperModel(MODELS[args.model], device=device, compute_type=compute,
                                 cpu_threads=os.cpu_count() or 4)
            segments, info = model.transcribe(
                str(args.source),
                language=None if args.lang == "auto" else args.lang,
                vad_filter=True,
                beam_size=5,
            )
            segments = list(segments)  # decoding is lazy; failures surface here, not above
            break
        except Exception as e:  # experimental backends (mps) can fail on some inputs
            print(f"warning: {device}/{compute} failed ({type(e).__name__}: {e}); trying next", file=sys.stderr)
    else:
        print("error: every backend failed", file=sys.stderr)
        return 1

    args.out_base.parent.mkdir(parents=True, exist_ok=True)
    txt = args.out_base.with_suffix(".txt")
    jsonl = args.out_base.with_suffix(".jsonl")
    n = 0
    with txt.open("w") as ft, jsonl.open("w") as fj:
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            n += 1
            ft.write(f"[{stamp(seg.start)}] {text}\n")
            fj.write(json.dumps({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text}) + "\n")

    print(json.dumps({
        "source": args.source.name,
        "duration_s": round(info.duration, 1),
        "language": info.language,
        "segments": n,
        "device": f"{device}/{compute}",
        "model": args.model,
        "elapsed_s": round(time.time() - t0, 1),
    }))
    return 0 if n else 2


if __name__ == "__main__":
    sys.exit(main())
