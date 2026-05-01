#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path

# -----------------------------
# SAFE EXECUTION CORE
# -----------------------------

class ProbeError(Exception):
    pass


def run(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        if p.returncode != 0:
            raise ProbeError(p.stderr.strip())

        return p.stdout

    except FileNotFoundError:
        raise ProbeError(f"Command not found: {cmd[0]}")


def safe_probe(file):
    """
    Never throws. Always returns structured result.
    """
    file = str(file)

    if not Path(file).exists():
        return {
            "file": file,
            "error": "MISSING_FILE"
        }

    try:
        vcmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate",
            "-of", "json",
            file
        ]

        acmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,channels",
            "-of", "json",
            file
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
            "acodec": a.get("codec_name"),
            "channels": a.get("channels"),
            "error": None
        }

    except Exception as e:
        return {
            "file": file,
            "error": str(e)
        }