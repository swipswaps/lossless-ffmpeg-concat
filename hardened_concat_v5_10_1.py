#!/usr/bin/env python3
import subprocess
import json
import sys
import signal
import platform
import shutil
import os
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
# RUNNER – no interactive 'q'
# ------------------------------------------------------------
def run_stream(cmd, label=""):
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
        while True:
            line = p.stderr.readline()
            if not line:
                break
            print(line.rstrip())
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
    # For all unknown or older Intel GPUs, use the stutter‑free 'fast' profile
    if gpu["vendor"] == "intel" and gpu["generation"] in ("ivybridge", "sandybridge", "unknown_intel"):
        return "--profile=fast"
    if gpu["vendor"] == "intel":
        return "--vo=gpu --hwdec=auto"
    return "--vo=gpu"

# ------------------------------------------------------------
# VLC CONFIGURATION FIX (SAFE PYTHON)
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

    settings = {
        "avcodec-hw": "vaapi",
        "vout": "opengl"
    }

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
# PROBE (unchanged)
# ------------------------------------------------------------
def get_duration(file):
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", file]
    try:
        out = subprocess.check_output(cmd, text=True)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None

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
# NORMALIZATION, CONCAT, STRATEGY, RE-ENCODE (same as before)
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

def choose_strategy(metas, force_ts):
    if force_ts:
        return "TS_FALLBACK"
    for m in metas:
        if m.get("error"):
            continue
        if m.get("risky"):
            print(f"[DECISION] {m['file']} is risky (GoPro/JPEG-range) → forcing TS fallback")
            return "TS_FALLBACK"
    return "DIRECT"

def fast_reencode(input_file, output_file):
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
        run_stream(cmd, label="qsv_reencode")

    elif method == "vaapi":
        cmd = [
            "ffmpeg", "-i", input_file,
            "-vaapi_device", "/dev/dri/renderD128",
            "-c:v", "h264_vaapi",
            "-qp", "18",
            "-c:a", "copy",
            output_file
        ]
        run_stream(cmd, label="vaapi_reencode")

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
        run_stream(cmd, label="ultrafast_reencode")

    print(f"\n✅ Playable copy created: {output_file}")

def post_concat_menu(video_file, gpu):
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
        fast_reencode(video_file, output)
    elif choice == "3":
        fix_vlc_config()
    else:
        print("Exiting.")

def main():
    if len(sys.argv) < 3:
        print("Usage: v5_10.py output.mp4 input1.mp4 [input2.mp4 ...] [--force-ts]")
        print("  --force-ts  : skip auto-detection, always use TS fallback")
        sys.exit(1)

    args = sys.argv[1:]
    force_ts = "--force-ts" in args
    if force_ts:
        args.remove("--force-ts")
    if len(args) < 2:
        print("Need output.mp4 and at least one input file.")
        sys.exit(1)

    out = args[0]
    files = args[1:]

    gpu = get_gpu_info()
    print(f"System: {platform.system()} {platform.release()}, GPU: {gpu['vendor']} {gpu['generation']}")

    try:
        print("\n[v5.10] NORMALIZATION PHASE")
        normalized = [normalize(f) for f in files if Path(f).exists()]

        print("\n[v5.10] ANALYSIS PHASE")
        metas = [safe_probe(f) for f in normalized]
        for m in metas:
            print("[META]", m)

        strategy = choose_strategy(metas, force_ts)
        print(f"\n[v5.10] STRATEGY: {strategy}")

        if strategy == "DIRECT":
            concat_direct(normalized, out)
        else:
            concat_ts(normalized, out)

        print(f"\n[v5.10] DONE: {out}")
        post_concat_menu(out, gpu)

    except Exception as e:
        print(f"\n[ERROR] {e}")
        kill_all()
        sys.exit(1)

if __name__ == "__main__":
    main()