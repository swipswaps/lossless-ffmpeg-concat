#!/usr/bin/env python3
import argparse
import asyncio
import logging
import sys
import subprocess

from pipeline_v4 import run_pipeline

# -----------------------------
# LOGGING
# -----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)

# -----------------------------
# CONCAT ENGINE
# -----------------------------

def concat_direct(files, out):
    logging.info("Running direct concat")
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", write_list(files),
        "-c", "copy", out
    ])


def concat_ts(files, out):
    logging.info("Running TS fallback concat")

    ts_files = []
    for f in files:
        ts = f + ".ts"
        subprocess.run([
            "ffmpeg", "-y", "-i", f,
            "-c", "copy",
            "-f", "mpegts", ts
        ])
        ts_files.append(ts)

    subprocess.run([
        "ffmpeg",
        "-i", "concat:" + "|".join(ts_files),
        "-c", "copy",
        out
    ])


def write_list(files):
    path = "files.txt"
    with open(path, "w") as f:
        for x in files:
            f.write(f"file '{x}'\n")
    return path


# -----------------------------
# MAIN
# -----------------------------

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("files", nargs="+")

    args = parser.parse_args()

    mode, results, issues = await run_pipeline(args.files)

    if mode == "FAIL_FAST":
        logging.error("Missing files detected — aborting")
        sys.exit(2)

    if mode == "DIRECT_CONCAT":
        concat_direct(args.files, args.output)
        sys.exit(0)

    if mode == "TS_FALLBACK":
        concat_ts(args.files, args.output)
        sys.exit(0)

    logging.error("Unknown mode")
    sys.exit(3)


if __name__ == "__main__":
    asyncio.run(main())