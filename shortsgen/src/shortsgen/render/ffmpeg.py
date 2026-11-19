"""Locate and run ffmpeg/ffprobe. Arguments are always passed as a list (no shell)."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


class FFmpegError(RuntimeError):
    def __init__(self, args: list[str], stderr: str):
        super().__init__(f"ffmpeg failed: {stderr[-2000:]}")
        self.args_list = args
        self.stderr = stderr


@lru_cache(maxsize=None)
def binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local, "Microsoft", "WinGet", "Links", f"{name}.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "*", "bin", f"{name}.exe"),
    ]
    for pat in patterns:
        hits = glob.glob(pat)
        if hits:
            return hits[0]
    raise FileNotFoundError(f"{name} not found; install FFmpeg (winget install Gyan.FFmpeg)")


def run(args: list[str], cwd: Path | None = None) -> None:
    cmd = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.stderr)


def probe(path: Path) -> dict:
    cmd = [binary("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.stderr)
    return json.loads(proc.stdout)


def decode_audio(path: Path, rate: int = 48000) -> bytes:
    cmd = [binary("ffmpeg"), "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(rate), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise FFmpegError(cmd, proc.stderr.decode("utf-8", "replace"))
    return proc.stdout
