# Lossless FFmpeg Concat Tool

A Linux-first CLI tool for **safe, lossless MP4 concatenation** with automatic validation and fallback.

---

## Features

- Uses `ffprobe` to inspect all input files
- Displays stream comparison table
- Detects mismatches before concat
- Automatically selects:
  - Direct concat (`-f concat`)
  - TS fallback (for timestamp issues)
- **No re-encoding (`-c copy` only)**

---

## Requirements

- Linux (tested on Fedora)
- `ffmpeg` + `ffprobe`

Install:

```bash
sudo dnf install ffmpeg
Usage
chmod +x concat_tool.py
./concat_tool.py output.mp4 input1.mp4 input2.mp4 input3.mp4
Output Example
=== STREAM INFO ===

FILE                 VCODEC   RES          FPS        ACODEC   CH
----------------------------------------------------------------
part1.mp4            h264     1920x1080    30/1       aac      2
part2.mp4            h264     1920x1080    30/1       aac      2

=== COMPATIBILITY CHECK ===

[OK] All files compatible for direct concat
Behavior
Condition	Action
All streams match	Direct concat
Any mismatch	TS fallback
Timestamp issues	TS fallback
Notes
True seamless concat requires identical streams
TS fallback handles most real-world edge cases
Still lossless
License

MIT