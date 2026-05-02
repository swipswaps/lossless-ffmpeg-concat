#!/usr/bin/env python3
"""
Lossless FFmpeg concat tool v5.11
- Pre-flight compatibility report (--check-only)
- Disk space check
- Automatic TS fallback for risky files (--force-direct to override)
- Missing dependency detection
- Dry-run mode (--dry-run)
- Save/load project file (--save/--load)
- Interactive ordering (if no input files provided)
- Progress bar for re-encode step (--progress)
"""

import subprocess
import json
import sys
import signal
import platform
import shutil
import os
import math
import time
from pathlib import Path

ACTIVE_PROCS = []

def kill_all():
    for p in ACTIVE_PROCS:
        try:
            p.kill()
        except Exception:
            pass

def signal_handler(sig, frame):
    print("\n[INTERRUPT] Stopping all ffmpeg processes...")
    kill_all()
    sys.exit(130)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ------------------------------------------------------------
# DEPENDENCY CHECK
# ------------------------------------------------------------
def check_deps():
    missing = []
    for cmd in ["ffmpeg", "ffprobe"]:
        if shutil.which(cmd) is None:
            missing.append(cmd)
    if missing:
        print(f"ERROR: Missing required tools: {', '.join(missing)}")
        print("Please install ffmpeg:")
        print("  Fedora: sudo dnf install ffmpeg")
        print("  Debian/Ubuntu: sudo apt install ffmpeg")
        print("  macOS: brew install ffmpeg")
        sys.exit(1)

# ------------------------------------------------------------
# RUNNER – with optional progress bar for re-encode
# ------------------------------------------------------------
def run_stream(cmd, label="", progress=False, total_duration=None):
    print(f"\n[RUN] {label}")
    print("CMD:", " ".join(cmd), "\n")
    p = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    ACTIVE_PROCS.append(p)
    try:
        last_line = ""
        start_time = time.time()
        while True:
            line = p.stderr.readline()
            if not line:
                break
            line = line.rstrip()
            if progress and total_duration and ("out_time_ms" in line or "time=" in line):
                # Parse time (ffmpeg progress)
                import re
                time_match = re.search(r'time=([0-9:.]+)', line)
                if time_match:
                    t = time_match.group(1)
                    # HH:MM:SS.mm
                    parts = t.split(':')
                    seconds = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                    percent = (seconds / total_duration) * 100
                    elapsed = time.time() - start_time
                    eta = (elapsed / max(seconds, 0.001)) * (total_duration - seconds) if seconds > 0 else 0
                    bar_len = 40
                    filled = int(bar_len * seconds / total_duration)
                    bar = '█' * filled + '░' * (bar_len - filled)
                    sys.stdout.write(f"\rProgress: |{bar}| {percent:.1f}%  ETA: {eta:.0f}s   ")
                    sys.stdout.flush()
            print(line)
        if progress and total_duration:
            sys.stdout.write("\n")
            sys.stdout.flush()
        p.wait()
        if p.returncode != 0:
            raise RuntimeError(f"ffmpeg exited with code {p.returncode}")
        return p.returncode
    except KeyboardInterrupt:
        signal_handler(None, None)
        return 1
    finally:
        if p in ACTIVE_PROCS:
            ACTIVE_PROCS.remove(p)

# ------------------------------------------------------------
# SYSTEM & ENCODER DETECTION
# ------------------------------------------------------------
def get_gpu_info():
    gpu = {"vendor": "unknown", "generation": "unknown"}
    try:
        lspci = subprocess.run(["lspci", "-v"], capture_output=True, text=True)
        for line in lspci.stdout.splitlines():
            if "VGA" in line and "Intel" in line:
                gpu["vendor"] = "intel"
                if "Ivy Bridge" in line:
                    gpu["generation"] = "ivybridge"
                elif "Sandy Bridge" in line:
                    gpu["generation"] = "sandybridge"
                elif "Haswell" in line:
                    gpu["generation"] = "haswell"
                elif "Skylake" in line:
                    gpu["generation"] = "skylake"
                else:
                    gpu["generation"] = "unknown_intel"
                break
    except Exception:
        pass
    return gpu

def check_encoder(name):
    try:
        result = subprocess.run(["ffmpeg", "-encoders"], capture_output=True, text=True)
        return name in result.stdout
    except Exception:
        return False

def check_handbrake():
    return shutil.which("HandBrakeCLI") is not None

def suggest_mpv_flags(gpu):
    if gpu["vendor"] == "intel" and gpu["generation"] in ("ivybridge", "sandybridge", "unknown_intel"):
        return "--profile=fast"
    if gpu["vendor"] == "intel":
        return "--vo=gpu --hwdec=auto"
    return "--vo=gpu"

# ------------------------------------------------------------
# VLC CONFIGURATION FIX (same as before)
# ------------------------------------------------------------
def fix_vlc_config():
    config_path = Path.home() / ".config/vlc/vlcrc"
    if not config_path.exists():
        print(f"VLC config not found at {config_path}. Creating empty config.")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.touch()

    backup = config_path.with_suffix(".rc.backup")
    shutil.copy2(config_path, backup)
    print(f"Backed up original config to {backup}")

    with open(config_path, "r") as f:
        lines = f.readlines()

    settings = {"avcodec-hw": "vaapi", "vout": "opengl"}
    new_lines = []
    updated_keys = set()
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=")[0] if "=" in stripped else None
        if key in settings:
            new_lines.append(f"{key}={settings[key]}\n")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in settings.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}\n")

    with open(config_path, "w") as f:
        f.writelines(new_lines)

    print("VLC configuration updated:")
    for k, v in settings.items():
        print(f"  - {k} = {v}")

    env_line = 'export LIBVA_DRIVER_NAME=i965'
    rc_files = [Path.home() / ".bashrc", Path.home() / ".profile"]
    env_already = False
    for rc in rc_files:
        if rc.exists() and env_line in rc.read_text():
            env_already = True
            break

    if not env_already:
        print("\nTo fully fix VA-API driver issues, add the following line to your ~/.bashrc or ~/.profile:")
        print(f"  {env_line}")
        answer = input("Add it now to ~/.bashrc? [y/N]: ").strip().lower()
        if answer == "y":
            with open(Path.home() / ".bashrc", "a") as f:
                f.write(f"\n# Force i965 VA-API driver (fixes VLC hardware decoding)\n{env_line}\n")
            print("Added to ~/.bashrc. Please log out and back in (or source ~/.bashrc).")
        else:
            print("You can add it manually later.")
    print("\nRestart VLC for changes to take effect.")

# ------------------------------------------------------------
# PROBE (enhanced for pre-flight report)
# ------------------------------------------------------------
def get_duration(file):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file]
    try:
        out = subprocess.check_output(cmd, text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None

def get_file_size(file):
    return Path(file).stat().st_size

def ffprobe_all(file):
    cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", file]
    try:
        out = subprocess.check_output(cmd, text=True)
        return json.loads(out)
    except Exception:
        return None

def safe_probe(file):
    if not Path(file).exists():
        return {"file": file, "error": "MISSING_FILE"}
    data = ffprobe_all(file)
    if not data or "streams" not in data:
        return {"file": file, "error": "PROBE_FAIL"}
    v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    if not v:
        return {"file": file, "error": "VIDEO_PROBE_FAIL"}
    risky = False
    if data.get("format", {}).get("tags", {}).get("firmware", "").startswith("HD"):
        risky = True
    if v.get("pix_fmt") in ("yuvj420p", "yuvj422p", "yuvj444p"):
        risky = True
    return {
        "file": file,
        "vcodec": v.get("codec_name"),
        "width": v.get("width"),
        "height": v.get("height"),
        "fps": v.get("r_frame_rate"),
        "acodec": a.get("codec_name") if a else None,
        "channels": a.get("channels") if a else None,
        "risky": risky,
        "pix_fmt": v.get("pix_fmt"),
        "error": None
    }

# ------------------------------------------------------------
# NORMALIZATION
# ------------------------------------------------------------
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
        "-stats",
        out
    ]
    run_stream(cmd, label=f"normalize {file}")
    return out

# ------------------------------------------------------------
# CONCAT (lossless)
# ------------------------------------------------------------
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
        "-fflags", "+genpts+igndts",
        "-avoid_negative_ts", "make_zero",
        "-copytb", "1",
        "-vsync", "0",
        "-fps_mode", "passthrough",
        "-max_interleave_delta", "0",
        "-movflags", "+faststart+empty_moov",
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
    concat_str = "|".join(ts_files)
    cmd = [
        "ffmpeg", "-y",
        "-i", f"concat:{concat_str}",
        "-c", "copy",
        "-fflags", "+genpts",
        "-avoid_negative_ts", "make_zero",
        "-copytb", "1",
        "-max_interleave_delta", "0",
        "-stats",
        out
    ]
    run_stream(cmd, label="concat_ts")

def choose_strategy(metas, force_ts, force_direct):
    if force_ts:
        return "TS_FALLBACK"
    if force_direct:
        return "DIRECT"
    for m in metas:
        if m.get("error"):
            continue
        if m.get("risky"):
            print(f"[DECISION] {m['file']} is risky (GoPro/JPEG-range) → using TS fallback")
            return "TS_FALLBACK"
    return "DIRECT"

# ------------------------------------------------------------
# DISK SPACE CHECK
# ------------------------------------------------------------
def check_disk_space(files, output_file):
    total_input_size = sum(get_file_size(f) for f in files if Path(f).exists())
    # Estimate output size = sum of input sizes + 10% overhead (for container)
    estimated_output = total_input_size * 1.1
    output_path = Path(output_file)
    free_space = shutil.disk_usage(output_path.parent).free
    if free_space < estimated_output:
        print(f"WARNING: Free disk space ({free_space // (1024**2)} MB) is less than estimated output size ({estimated_output // (1024**2)} MB).")
        print("Proceed at your own risk. (Use --force to skip this check)")
        answer = input("Continue anyway? [y/N]: ").strip().lower()
        if answer != 'y':
            sys.exit(1)
    else:
        print(f"Disk space OK: {free_space // (1024**2)} MB free, need ~{estimated_output // (1024**2)} MB.")

# ------------------------------------------------------------
# PRE-FLIGHT COMPATIBILITY REPORT (--check-only)
# ------------------------------------------------------------
def compatibility_report(files):
    print("\n" + "="*60)
    print("PRE-FLIGHT COMPATIBILITY REPORT")
    print("="*60)
    metas = [safe_probe(f) for f in files]
    base = None
    issues = []
    for m in metas:
        if m.get("error"):
            print(f"✗ {m['file']}: {m['error']}")
            issues.append((m['file'], m['error']))
            continue
        if base is None:
            base = m
            print(f"✓ {m['file']} (reference)")
        else:
            diff = {}
            for k in ["vcodec", "width", "height", "fps", "acodec", "channels", "pix_fmt"]:
                if m.get(k) != base.get(k):
                    diff[k] = (base.get(k), m.get(k))
            if diff:
                print(f"✗ {m['file']}")
                for k, (ref, val) in diff.items():
                    print(f"    {k}: {ref} != {val}")
                issues.append((m['file'], diff))
            else:
                print(f"✓ {m['file']}")
    print("\n" + "-"*60)
    if issues:
        print("⚠️  Issues found. Concat may fail or produce glitches.")
        print("Recommended: use TS fallback (--force-ts) or re-encode mismatched files.")
    else:
        print("✅ All files are compatible. Direct concat should work.")
    print("="*60)
    return issues

# ------------------------------------------------------------
# FAST RE-ENCODE (with progress bar)
# ------------------------------------------------------------
def fast_reencode(input_file, output_file, progress=False):
    print("\nAvailable fast encoding methods:")
    methods = []
    if check_handbrake():
        methods.append(("HandBrakeCLI", "handbrake"))
    if check_encoder("h264_qsv"):
        methods.append(("Intel QuickSync (h264_qsv)", "qsv"))
    if check_encoder("h264_vaapi"):
        methods.append(("VA-API (h264_vaapi)", "vaapi"))
    methods.append(("Ultrafast software (libx264 ultrafast)", "ultrafast"))

    for i, (name, _) in enumerate(methods, 1):
        print(f"  {i}. {name}")

    choice = input(f"Choose method [1-{len(methods)}]: ").strip()
    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(methods):
            raise ValueError
    except ValueError:
        print("Invalid choice, skipping re-encode.")
        return

    method = methods[idx][1]
    print(f"\n[RE-ENCODE] Using {methods[idx][0]}...")

    total_duration = get_duration(input_file) if progress else None

    if method == "handbrake":
        cmd = [
            "HandBrakeCLI",
            "-i", input_file,
            "-o", output_file,
            "--preset=Very Fast 1080p30",
            "--encoder=x264",
            "--quality=18",
            "--audio-copy-mask=aac"
        ]
        subprocess.run(cmd)

    elif method == "qsv":
        cmd = [
            "ffmpeg", "-i", input_file,
            "-c:v", "h264_qsv",
            "-preset", "veryfast",
            "-global_quality", "18",
            "-c:a", "copy",
            output_file
        ]
        run_stream(cmd, label="qsv_reencode", progress=progress, total_duration=total_duration)

    elif method == "vaapi":
        cmd = [
            "ffmpeg", "-i", input_file,
            "-vaapi_device", "/dev/dri/renderD128",
            "-c:v", "h264_vaapi",
            "-qp", "18",
            "-c:a", "copy",
            output_file
        ]
        run_stream(cmd, label="vaapi_reencode", progress=progress, total_duration=total_duration)

    else:  # ultrafast
        cmd = [
            "ffmpeg", "-i", input_file,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            output_file
        ]
        run_stream(cmd, label="ultrafast_reencode", progress=progress, total_duration=total_duration)

    print(f"\n✅ Playable copy created: {output_file}")

# ------------------------------------------------------------
# INTERACTIVE ORDERING (when no input files provided)
# ------------------------------------------------------------
def interactive_order_files():
    import tempfile
    print("\nInteractive File Ordering")
    print("Enter file paths (one per line). Empty line to finish.")
    files = []
    while True:
        path = input(f"File {len(files)+1}: ").strip()
        if not path:
            break
        if not Path(path).exists():
            print("File not found, try again.")
            continue
        files.append(path)
    if not files:
        print("No files provided. Exiting.")
        sys.exit(1)
    # Show current order
    print("\nCurrent order:")
    for i, f in enumerate(files, 1):
        print(f"{i}. {f}")
    print("\nCommands: [num] to move, [s] to swap, [q] to quit, [enter] to accept")
    while True:
        cmd = input("> ").strip()
        if cmd == "":
            break
        if cmd == "q":
            sys.exit(0)
        if cmd == "s":
            a = int(input("First index: ")) - 1
            b = int(input("Second index: ")) - 1
            files[a], files[b] = files[b], files[a]
        elif cmd.isdigit():
            idx = int(cmd) - 1
            new_pos = int(input("Move to position (1..n): ")) - 1
            if 0 <= idx < len(files) and 0 <= new_pos < len(files):
                f = files.pop(idx)
                files.insert(new_pos, f)
            else:
                print("Invalid index.")
        else:
            print("Unknown command")
        print("New order:")
        for i, f in enumerate(files, 1):
            print(f"{i}. {f}")
    return files

# ------------------------------------------------------------
# SAVE/LOAD PROJECT
# ------------------------------------------------------------
def save_project(files, output, force_ts, force_direct, dry_run, check_only, progress, filename):
    project = {
        "files": files,
        "output": output,
        "force_ts": force_ts,
        "force_direct": force_direct,
        "dry_run": dry_run,
        "check_only": check_only,
        "progress": progress
    }
    with open(filename, "w") as f:
        json.dump(project, f, indent=2)
    print(f"Project saved to {filename}")

def load_project(filename):
    with open(filename, "r") as f:
        return json.load(f)

# ------------------------------------------------------------
# POST-CONCAT MENU
# ------------------------------------------------------------
def post_concat_menu(video_file, gpu, progress=False):
    flags = suggest_mpv_flags(gpu)
    print("\n" + "="*60)
    print("POST-CONCAT OPTIONS")
    print("="*60)
    print(f"File: {video_file}")
    meta = safe_probe(video_file)
    if meta.get("pix_fmt", "").startswith("yuvj"):
        print("⚠️  Video uses JPEG color range (may stutter on some players).")
    print(f"\n✅ Proven smooth playback command for your system:\n   mpv {flags} \"{video_file}\"")

    print("\nOptions:")
    print("  [1] Play now with optimal settings (no re-encode)")
    print("  [2] Create a fast re-encoded copy (hardware/HandBrake)")
    print("  [3] Fix VLC hardware decoding for this system (apply once)")
    print("  [4] Skip (exit)")

    choice = input("Your choice [1/2/3/4]: ").strip()
    if choice == "1":
        subprocess.run(["mpv", *flags.split(), video_file])
    elif choice == "2":
        output = video_file.replace(".mp4", "_playable.mp4")
        fast_reencode(video_file, output, progress=progress)
    elif choice == "3":
        fix_vlc_config()
    else:
        print("Exiting.")

# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
def main():
    check_deps()

    # Parse arguments with argparse
    import argparse
    parser = argparse.ArgumentParser(description="Lossless FFmpeg concat tool v5.11")
    parser.add_argument("output", nargs="?", help="Output file (required unless --load)")
    parser.add_argument("inputs", nargs="*", help="Input files")
    parser.add_argument("--force-ts", action="store_true", help="Force TS fallback")
    parser.add_argument("--force-direct", action="store_true", help="Force direct concat (override risky detection)")
    parser.add_argument("--dry-run", action="store_true", help="Print commands and estimate, do not execute")
    parser.add_argument("--check-only", action="store_true", help="Only run compatibility report and exit")
    parser.add_argument("--progress", action="store_true", help="Show progress bar during re-encode")
    parser.add_argument("--save", metavar="FILE", help="Save project to JSON file")
    parser.add_argument("--load", metavar="FILE", help="Load project from JSON file")
    args = parser.parse_args()

    # Handle load/save
    if args.load:
        proj = load_project(args.load)
        files = proj["files"]
        output = proj["output"]
        force_ts = proj.get("force_ts", False)
        force_direct = proj.get("force_direct", False)
        dry_run = proj.get("dry_run", False)
        check_only = proj.get("check_only", False)
        progress = proj.get("progress", False)
    else:
        if not args.output:
            parser.error("output file required (unless --load)")
        output = args.output
        if args.inputs:
            files = args.inputs
        else:
            # Interactive ordering mode
            files = interactive_order_files()
        force_ts = args.force_ts
        force_direct = args.force_direct
        dry_run = args.dry_run
        check_only = args.check_only
        progress = args.progress

    if args.save:
        save_project(files, output, force_ts, force_direct, dry_run, check_only, progress, args.save)

    # Pre-flight check
    if check_only:
        compatibility_report(files)
        sys.exit(0)

    # Disk space check
    if not dry_run:
        check_disk_space(files, output)

    gpu = get_gpu_info()
    print(f"System: {platform.system()} {platform.release()}, GPU: {gpu['vendor']} {gpu['generation']}")

    try:
        print("\n[v5.11] NORMALIZATION PHASE")
        normalized = []
        for f in files:
            if not Path(f).exists():
                print(f"[SKIP] missing file: {f}")
                continue
            normalized.append(normalize(f))

        print("\n[v5.11] ANALYSIS PHASE")
        metas = [safe_probe(f) for f in normalized]
        for m in metas:
            print("[META]", m)

        strategy = choose_strategy(metas, force_ts, force_direct)
        print(f"\n[v5.11] STRATEGY: {strategy}")

        if dry_run:
            print("\n[DRY RUN] Would execute:")
            if strategy == "DIRECT":
                list_file = write_list(normalized)
                print(f"  ffmpeg -f concat -safe 0 -i {list_file} -map 0:v:0 -map 0:a? -c copy -fflags +genpts+igndts ... {output}")
            else:
                print(f"  TS fallback: convert each to .ts, then concat, then remux to {output}")
            total_size = sum(get_file_size(f) for f in normalized if Path(f).exists())
            print(f"  Estimated output size: ~{total_size*1.1 // (1024**2)} MB")
            sys.exit(0)

        if strategy == "DIRECT":
            concat_direct(normalized, output)
        else:
            concat_ts(normalized, output)

        print(f"\n[v5.11] DONE: {output}")
        post_concat_menu(output, gpu, progress=progress)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        kill_all()
        sys.exit(1)

if __name__ == "__main__":
    main()