# Lossless FFmpeg Concat Tool v2

A terminal-based interactive tool for **safe MP4 validation and lossless concatenation**.

---

## Features

- Interactive terminal UI (no dependencies)
- ffprobe-based validation
- Per-file compatibility diff view
- Lossless concat using ffmpeg (-c copy)
- Manual inspection before execution

---

## Install

```bash
sudo dnf install ffmpeg
chmod +x concat_tui.py
Usage
./concat_tui.py output.mp4 input1.mp4 input2.mp4
Controls
j → down
k → up
Enter → inspect file
c → concatenate
q → quit
Behavior
Compatible files → safe concat
Mismatches → shown in detail view
No re-encoding ever
Philosophy

This tool assumes:

FFmpeg is correct — but unsafe without inspection

So it adds a validation layer before execution.