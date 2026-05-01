#!/usr/bin/env python3

import subprocess
import json
import sys
import os
from pathlib import Path

# ---------------------------
# FFPROBE CORE
# ---------------------------

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr)
    return p.stdout


def probe(file):
    vcmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate,pix_fmt",
        "-of", "json", file
    ]

    acmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,channels",
        "-of", "json", file
    ]

    v = json.loads(run(vcmd))["streams"][0]
    a_raw = json.loads(run(acmd))
    a = a_raw["streams"][0] if "streams" in a_raw else {}

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


# ---------------------------
# VALIDATION ENGINE
# ---------------------------

def diff(base, other):
    out = {}
    for k in base:
        if k == "file":
            continue
        if base[k] != other[k]:
            out[k] = (base[k], other[k])
    return out


def analyze(files):
    data = [probe(f) for f in files]
    base = data[0]
    results = []

    for d in data:
        results.append((d, diff(base, d)))

    return results


# ---------------------------
# SIMPLE TUI (NO DEPENDENCIES)
# ---------------------------

def clear():
    os.system("clear")


def print_header():
    print("LOSSLESS CONCAT TOOL v2")
    print("-" * 40)


def render(results, selected):
    clear()
    print_header()

    print("\nFILES:\n")

    for i, (meta, d) in enumerate(results):
        status = "OK" if not d else "FAIL"
        prefix = "▶" if i == selected else " "

        print(f"{prefix} {i+1}. {Path(meta['file']).name:<25} [{status}]")

    print("\nControls: ↑ ↓ Enter = view details | q = quit")


def show_details(meta, diffs):
    clear()
    print("DETAIL VIEW")
    print("-" * 40)
    print(f"File: {meta['file']}\n")

    for k, v in meta.items():
        if k != "file":
            print(f"{k:12}: {v}")

    if diffs:
        print("\nDIFFS:")
        for k, v in diffs.items():
            print(f"  {k}: {v[0]} != {v[1]}")
    else:
        print("\nCOMPATIBLE ✓")

    input("\nPress Enter...")


# ---------------------------
# CONCAT ENGINE
# ---------------------------

def write_list(files):
    with open("files.txt", "w") as f:
        for x in files:
            f.write(f"file '{x}'\n")


def concat(files, out):
    write_list(files)
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", "files.txt",
        "-c", "copy",
        out
    ])


# ---------------------------
# MAIN LOOP
# ---------------------------

def main():
    if len(sys.argv) < 3:
        print("Usage: concat_tui.py output.mp4 input1.mp4 input2.mp4 ...")
        sys.exit(1)

    out = sys.argv[1]
    files = sys.argv[2:]

    results = analyze(files)
    selected = 0

    while True:
        render(results, selected)

        key = input().strip()

        if key == "q":
            break
        elif key == "":
            show_details(*results[selected])
        elif key == "j":
            selected = min(len(results) - 1, selected + 1)
        elif key == "k":
            selected = max(0, selected - 1)
        elif key == "c":
            concat(files, out)
            print("\nDONE:", out)
            break


if __name__ == "__main__":
    main()