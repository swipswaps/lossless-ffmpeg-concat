#!/usr/bin/env python3
import asyncio
import subprocess
from safe_core import safe_probe
from pathlib import Path

# -----------------------------
# ASYNC SCANNER
# -----------------------------

async def probe_async(file):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, safe_probe, file)


async def scan(files):
    tasks = [probe_async(f) for f in files]
    return await asyncio.gather(*tasks)


# -----------------------------
# COMPATIBILITY ENGINE
# -----------------------------

def analyze(results):
    base = None
    issues = []

    for r in results:
        if r.get("error"):
            issues.append((r["file"], r["error"]))
            continue

        if base is None:
            base = r
            continue

        diff = {}
        for k in ["vcodec", "width", "height", "fps", "acodec"]:
            if r.get(k) != base.get(k):
                diff[k] = (base.get(k), r.get(k))

        if diff:
            issues.append((r["file"], diff))

    return issues


# -----------------------------
# AUTO REPAIR LOGIC
# -----------------------------

def suggest_fallback(issues):
    if not issues:
        return "DIRECT_CONCAT"

    for _, issue in issues:
        if issue == "MISSING_FILE":
            return "FAIL_FAST"

    return "TS_FALLBACK"


# -----------------------------
# PIPELINE ENTRY
# -----------------------------

async def run_pipeline(files):
    print("[SCAN] async probing files...")

    results = await scan(files)

    print("[ANALYZE] computing compatibility...")
    issues = analyze(results)

    mode = suggest_fallback(issues)

    print("\nRESULT MODE:", mode)

    if issues:
        print("\nISSUES:")
        for f, i in issues:
            print(" -", f, "=>", i)

    return mode, results, issues