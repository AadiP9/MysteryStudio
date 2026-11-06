"""Automatic quality control. A video that fails here is never published."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np


class QCError(RuntimeError):
    pass


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def check_video(cfg, path: Path) -> dict:
    v = cfg["video"]
    pr = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    info = json.loads(pr.stdout or "{}")
    streams = {s["codec_type"]: s for s in info.get("streams", [])}
    dur = float(info.get("format", {}).get("duration", 0))
    problems = []
    if "video" not in streams:
        problems.append("no video stream")
    elif (int(streams["video"]["width"]), int(streams["video"]["height"])) != (v["width"], v["height"]):
        problems.append("wrong resolution")
    if "audio" not in streams:
        problems.append("no audio stream")
    if not v["min_seconds"] - 3 <= dur <= v["max_seconds"] + 5:
        problems.append(f"duration {dur:.1f}s outside {v['min_seconds']}-{v['max_seconds']}s")
    if path.stat().st_size > 250 * 1024 * 1024:
        problems.append("file larger than 250 MB")

    # black frames (ignoring the first/last fraction of a second)
    bd = _run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.6:pic_th=0.97", "-an", "-f", "null", "-"])
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", bd.stderr):
        s, e = float(m.group(1)), float(m.group(2))
        if s > 0.3 and e < dur - 0.3:
            problems.append(f"black frames {s:.1f}-{e:.1f}s")

    # audio level and silence
    vd = _run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"])
    mm = re.search(r"mean_volume: (-?[\d.]+) dB", vd.stderr)
    if not mm or float(mm.group(1)) < -32:
        problems.append("audio too quiet or silent")
    sd = _run(["ffmpeg", "-i", str(path), "-af", "silencedetect=n=-45dB:d=2.0", "-vn", "-f", "null", "-"])
    if "silence_start" in sd.stderr:
        problems.append("long silence inside the video")

    # visual sanity: sample frames must have content
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    flat = 0
    for k in range(1, 7):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * k / 7))
        ok, fr = cap.read()
        if not ok or float(np.std(fr)) < 8:
            flat += 1
    cap.release()
    if flat >= 2:
        problems.append("several flat/blank frames")
    if problems:
        raise QCError("; ".join(problems))
    return {"duration": dur, "mean_volume_db": float(mm.group(1)), "size_mb": path.stat().st_size / 1e6}
