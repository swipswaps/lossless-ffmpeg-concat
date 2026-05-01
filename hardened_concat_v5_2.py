#!/usr/bin/env python3
import subprocess
import json
import sys
import os
import time
import signal
from pathlib import Path
from datetime import datetime

# =========================================================
# GLOBAL PROCESS TRACKING (for safe CTRL+C cleanup)
# =========================================================

ACTIVE_PROCS = []


def kill_all():
    for p in ACTIVE_PROCS:
        try:
            p.kill()
        except Exception:
            pass


signal.signal(signal.SIGINT, lambda s, f: (_ for _ in ()).throw(KeyboardInterrupt))


# =========================================================
# STREAMING RUNNER (CRITICAL FIX)
# =========================================================

def run_stream(cmd, label=""):
    """
    Streams stdout/stderr live (no buffering blindness)
    """
    print(f"\n[RUN] {label}")
    print("CMD:", " ".join(cmd), "\n")

    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    ACTIVE_PROCS.append(p)

    try:
        # stream stderr (ffmpeg uses stderr for progress)
        while True:
            line = p.stderr.readline()
            if not line:
                break
            print(line.rstrip())

        p.wait()
        return p.returncode

    except KeyboardInterrupt:
        print("\n[CTRL+C] stopping ffmpeg safely...")
        p.kill()
        kill_all()
        sys.exit(130)


# =========================================================
# PROBE WITH DURATION (FOR ETA)
# =========================================================

def get_duration(file):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        file
    ]

    try:
        out = subprocess.check_output(cmd, text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


# =========================================================
# SAFE PROBE
# =========================================================

def ffprobe(file, stream_type):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", stream_type,
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,channels",
        "-of", "json",
        file
    ]

    try:
        out = subprocess.check_output(cmd, text=True)
        data = json.loads(out)
        return data["streams"][0] if data.get("streams") else None
    except Exception:
        return None


def safe_probe(file):
    if not Path(file).exists():
        return {"file": file, "error": "MISSING_FILE"}

    v = ffprobe(file, "v:0")
    a = ffprobe(file, "a:0")

    if not v:
        return {"file": file, "error": "VIDEO_PROBE_FAIL"}

    return {
        "file": file,
        "vcodec": v.get("codec_name"),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": v.get("r_frame_rate"),
        "acodec": a.get("codec_name") if a else None,
        "channels": a.get("channels") if a else None,
        "error": None
    }


# =========================================================
# NORMALIZATION (NOW WITH VISIBILITY + ETA PREP)
# =========================================================

def normalize(file):
    out = str(Path(file).with_suffix("")) + ".norm.mp4"

    duration = get_duration(file)
    if duration:
        print(f"[NORMALIZE] {file} (~{duration:.1f}s)")
    else:
        print(f"[NORMALIZE] {file} (unknown duration)")

    cmd = [
        "ffmpeg", "-y",
        "-i", file,
        "-c", "copy",
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-stats",          # IMPORTANT: enables progress output
        out
    ]

    run_stream(cmd, label=f"normalize {file}")

    return out


# =========================================================
# CONCAT (STREAMING)
# =========================================================

def write_list(files):
    path = "concat_files.txt"
    with open(path, "w") as f:
        for x in files:
            f.write(f"file '{x}'\n")
    return path


def concat_direct(files, out):
    list_file = write_list(files)

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c", "copy",
        "-stats",
        out
    ]

    run_stream(cmd, label="concat_direct")


def concat_ts(files, out):
    ts_files = []

    for f in files:
        ts = f + ".ts"
        run_stream([
            "ffmpeg", "-y",
            "-i", f,
            "-c", "copy",
            "-f", "mpegts",
            ts
        ], label=f"ts_wrap {f}")
        ts_files.append(ts)

    cmd = [
        "ffmpeg", "-y",
        "-i", "concat:" + "|".join(ts_files),
        "-c", "copy",
        "-stats",
        out
    ]

    run_stream(cmd, label="concat_ts")


# =========================================================
# PIPELINE
# =========================================================

def main():
    if len(sys.argv) < 3:
        print("Usage: v5_2.py output.mp4 input1.mp4 ...")
        sys.exit(1)

    out = sys.argv[1]
    files = sys.argv[2:]

    try:
        print("\n[v5.2] NORMALIZATION PHASE")
        normalized = [normalize(f) for f in files if Path(f).exists()]

        print("\n[v5.2] ANALYSIS PHASE")
        for f in normalized:
            meta = safe_probe(f)
            print("[META]", meta)

        print("\n[v5.2] CONCAT PHASE")
        concat_direct(normalized, out)

        print("\nDONE:", out)

    except KeyboardInterrupt:
        print("\n[ABORT] user interrupt")
        kill_all()
        sys.exit(130)


if __name__ == "__main__":
    main()