#!/usr/bin/env python3

import curses
import subprocess
import json
import sys
from pathlib import Path

# ---------------------------
# FFPROBE
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
        "channels": a.get("channels"),
    }


def diff(base, other):
    d = {}
    for k in base:
        if k == "file":
            continue
        if base[k] != other[k]:
            d[k] = (base[k], other[k])
    return d


# ---------------------------
# CONCAT ENGINE
# ---------------------------

def concat(files, out):
    with open("files.txt", "w") as f:
        for x in files:
            f.write(f"file '{x}'\n")

    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0",
        "-i", "files.txt",
        "-c", "copy",
        out
    ])


# ---------------------------
# UI
# ---------------------------

class App:
    def __init__(self, stdscr, files, output):
        self.stdscr = stdscr
        self.files = files
        self.output = output
        self.data = [probe(f) for f in files]
        self.base = self.data[0]
        self.selected = 0
        self.mode = "list"  # list | detail

    def render(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        self.stdscr.addstr(0, 0, "LOSSLESS CONCAT TOOL v3", curses.A_BOLD)
        self.stdscr.addstr(1, 0, "-" * (w - 1))

        if self.mode == "list":
            self.render_list()
        else:
            self.render_detail()

        self.stdscr.refresh()

    def render_list(self):
        for i, d in enumerate(self.data):
            dmap = diff(self.base, d)
            status = "OK" if not dmap else "FAIL"
            prefix = "▶" if i == self.selected else " "

            line = f"{prefix} {i+1}. {Path(d['file']).name} [{status}]"
            self.stdscr.addstr(3 + i, 0, line)

        self.stdscr.addstr(15, 0,
            "↑↓ move | Enter detail | c concat | q quit"
        )

    def render_detail(self):
        d = self.data[self.selected]
        dmap = diff(self.base, d)

        self.stdscr.addstr(3, 0, f"FILE: {d['file']}")
        y = 5

        for k, v in d.items():
            self.stdscr.addstr(y, 0, f"{k}: {v}")
            y += 1

        self.stdscr.addstr(y + 1, 0, "DIFFS:")
        y += 2

        if not dmap:
            self.stdscr.addstr(y, 0, "COMPATIBLE ✓")
        else:
            for k, v in dmap.items():
                self.stdscr.addstr(y, 0, f"{k}: {v[0]} != {v[1]}")
                y += 1

        self.stdscr.addstr(20, 0, "Back: ESC")

    def run(self):
        while True:
            self.render()
            key = self.stdscr.getch()

            # navigation
            if self.mode == "list":
                if key == curses.KEY_DOWN:
                    self.selected = min(len(self.data) - 1, self.selected + 1)
                elif key == curses.KEY_UP:
                    self.selected = max(0, self.selected - 1)
                elif key == ord("\n"):
                    self.mode = "detail"
                elif key == ord("c"):
                    concat(self.files, self.output)
                    break
                elif key == ord("q"):
                    break

            else:
                if key == 27:  # ESC
                    self.mode = "list"


# ---------------------------
# MAIN
# ---------------------------

def main(stdscr):
    if len(sys.argv) < 3:
        print("usage: concat_tui_v3.py output.mp4 input1.mp4 ...")
        return

    output = sys.argv[1]
    files = sys.argv[2:]

    curses.curs_set(0)
    stdscr.keypad(True)

    app = App(stdscr, files, output)
    app.run()


if __name__ == "__main__":
    curses.wrapper(main)