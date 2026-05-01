#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from pathlib import Path

def run(cmd):
    """Run shell command and return stdout"""
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Command failed:\n{' '.join(cmd)}\n{result.stderr}")
        sys.exit(1)
    return result.stdout


def ffprobe_stream(file):
    """Extract key stream info"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,pix_fmt",
        "-of", "json",
        file
    ]
    data = json.loads(run(cmd))
    v = data["streams"][0]

    cmd_audio = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries",
        "stream=codec_name,channels",
        "-of", "json",
        file
    ]
    data_a = json.loads(run(cmd_audio))
    a = data_a["streams"][0] if data_a.get("streams") else {}

    return {
        "file": file,
        "vcodec": v.get("codec_name"),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": v.get("r_frame_rate"),
        "pix_fmt": v.get("pix_fmt"),
        "acodec": a.get("codec_name"),
        "channels": a.get("channels")
    }


def compare_streams(streams):
    """Check if all streams match first file"""
    base = streams[0]
    mismatches = []

    for s in streams[1:]:
        diff = {}
        for k in base:
            if k == "file":
                continue
            if s[k] != base[k]:
                diff[k] = (base[k], s[k])

        mismatches.append((s["file"], diff))

    return mismatches


def print_table(streams, mismatches):
    print("\n=== STREAM INFO ===\n")
    header = f"{'FILE':20} {'VCODEC':8} {'RES':12} {'FPS':10} {'ACODEC':8} {'CH':4}"
    print(header)
    print("-" * len(header))

    for s in streams:
        res = f"{s['width']}x{s['height']}"
        print(f"{Path(s['file']).name:20} {s['vcodec']:8} {res:12} {s['fps']:10} {s['acodec']:8} {str(s['channels']):4}")

    print("\n=== COMPATIBILITY CHECK ===\n")
    safe = True
    for fname, diff in mismatches:
        if diff:
            safe = False
            print(f"[FAIL] {fname}")
            for k, v in diff.items():
                print(f"  - {k}: {v[0]} != {v[1]}")
    if safe:
        print("[OK] All files compatible for direct concat")

    return safe


def write_concat_list(files, path="files.txt"):
    with open(path, "w") as f:
        for file in files:
            f.write(f"file '{file}'\n")
    return path


def concat_direct(files, output):
    listfile = write_concat_list(files)
    cmd = [
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", listfile,
        "-c", "copy",
        output
    ]
    print("\n[INFO] Running direct concat...\n")
    subprocess.run(cmd)


def concat_ts(files, output):
    ts_files = []

    print("\n[INFO] Using TS fallback method...\n")

    for f in files:
        ts = f + ".ts"
        cmd = [
            "ffmpeg", "-y",
            "-i", f,
            "-c", "copy",
            "-bsf:v", "h264_mp4toannexb",
            "-f", "mpegts",
            ts
        ]
        subprocess.run(cmd)
        ts_files.append(ts)

    concat_str = "|".join(ts_files)

    cmd = [
        "ffmpeg",
        "-i", f"concat:{concat_str}",
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        output
    ]
    subprocess.run(cmd)


def main():
    if len(sys.argv) < 3:
        print("Usage: ./concat_tool.py output.mp4 input1.mp4 input2.mp4 ...")
        sys.exit(1)

    output = sys.argv[1]
    files = sys.argv[2:]

    streams = [ffprobe_stream(f) for f in files]
    mismatches = compare_streams(streams)

    safe = print_table(streams, mismatches)

    if safe:
        concat_direct(files, output)
    else:
        print("\n[WARN] Mismatch detected → using TS fallback (still lossless)\n")
        concat_ts(files, output)

    print("\n[DONE] Output:", output)


if __name__ == "__main__":
    main()