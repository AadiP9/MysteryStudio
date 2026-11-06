"""Frame-accurate renderer: Ken Burns camera, film grade, impact shake, text cards, crossfades -> ffmpeg."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import cv2
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

from .config import FONT_PATH, ROOT, log
from .visuals import SRC_H, SRC_W

MOTIONS = ["push", "pull", "pan_l", "pan_r", "push_up", "drift"]


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


class TextCard:
    """Pre-rendered RGBA text block that fades in and out; composited only in its bounding box."""

    def __init__(self, text: str, style: str, W: int, H: int):
        text = text.upper().strip()
        if style == "big":
            size, y_c = 190, int(H * 0.40)
        else:
            size, y_c = 74, int(H * 0.17)
        font = ImageFont.truetype(str(FONT_PATH), size)
        maxw = W - 180
        while font.getlength(text) > maxw and size > 46:
            size -= 6
            font = ImageFont.truetype(str(FONT_PATH), size)
        # wrap to two lines if still too wide
        lines = [text]
        if font.getlength(text) > maxw and " " in text:
            words, a, b = text.split(), [], []
            for w in words:
                (a if font.getlength(" ".join(a + [w])) <= maxw and not b else b).append(w)
            lines = [" ".join(a), " ".join(b)]
        lh = int(size * 1.15)
        top = y_c - lh * len(lines) // 2
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for k, ln in enumerate(lines):
            w = font.getlength(ln)
            xy = ((W - w) / 2, top + k * lh)
            d.text(xy, ln, font=font, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 255))
        if style != "big":
            y = top + lh * len(lines) + 12
            d.rectangle([W // 2 - 90, y, W // 2 + 90, y + 6], fill=(0, 215, 255, 255))
        arr = np.array(layer)
        ys = np.where(arr[..., 3].max(axis=1) > 0)[0]
        self.y0, self.y1 = max(0, ys.min() - 6), min(H, ys.max() + 6)
        reg = arr[self.y0:self.y1]
        self.alpha = (reg[..., 3:4].astype(np.float32) / 255.0)
        self.rgb = reg[..., :3][..., ::-1].astype(np.float32)   # BGR

    def apply(self, frame: np.ndarray, fade: float) -> None:
        if fade <= 0.01:
            return
        a = self.alpha * fade
        reg = frame[self.y0:self.y1]
        reg[:] = np.clip(reg.astype(np.float32) * (1 - a) + self.rgb * a, 0, 255).astype(np.uint8)


class Renderer:
    def __init__(self, cfg, script, images, timeline, workdir: Path):
        v = cfg["video"]
        self.cfg, self.script, self.images, self.tl = cfg, script, images, timeline
        self.W, self.H, self.fps = v["width"], v["height"], v["fps"]
        self.T = v["transition_seconds"]
        self.look = cfg["look"]
        rng = np.random.default_rng(int(hashlib.md5(script["title"].encode()).hexdigest()[:8], 16))
        self.rng = rng
        self.motions = [MOTIONS[(i + int(rng.integers(0, 6))) % 6] for i in range(len(images))]
        yy, xx = np.mgrid[0:self.H, 0:self.W].astype(np.float32)
        d = np.sqrt(((xx - self.W / 2) / (self.W / 2)) ** 2 + ((yy - self.H / 2) / (self.H / 2)) ** 2)
        vig = 1 - self.look["vignette"] * np.clip(d - 0.35, 0, 1) ** 1.6
        self.vig = np.repeat((vig * 255).astype(np.uint8)[..., None], 3, axis=2)
        # soft film grain: generated at half resolution (compresses far better than pixel noise)
        amp = self.look["grain"] * 255
        self.grain = []
        for _ in range(6):
            n = rng.normal(0, amp, (self.H // 2, self.W // 2)).astype(np.float32)
            n = cv2.resize(n, (self.W, self.H), interpolation=cv2.INTER_LINEAR)[..., None]
            n = np.repeat(n, 3, axis=2)
            self.grain.append((np.clip(n, 0, 255).astype(np.uint8), np.clip(-n, 0, 255).astype(np.uint8)))
        sat = self.look["saturation"]
        G = np.array([[0.114, 0.587, 0.299]] * 3, np.float32)
        M3 = (sat * np.eye(3, dtype=np.float32) + (1 - sat) * G)
        M3 = np.diag(np.array(self.look["tint"], np.float32)) @ M3 * 1.06
        self.cmat = np.hstack([M3, np.full((3, 1), -6.0, np.float32)])   # 3x4: matrix + offset
        self.cards = []
        for sc in script["scenes"]:
            t = (sc.get("on_screen_text") or "").strip()
            self.cards.append(TextCard(t, sc.get("text_style", "kicker"), self.W, self.H) if t else None)

    # --- one scene at local time t (seconds since scene start; may exceed dur during crossfade)
    def scene_frame(self, i: int, t: float) -> np.ndarray:
        dur = self.tl[i]["dur"] + self.T
        p = _ease(t / dur)
        zt = self.look["zoom_total"]
        m = self.motions[i]
        zoom = {"push": 1 + zt * p, "pull": 1 + zt * (1 - p), "push_up": 1 + zt * 0.8 * p,
                "pan_l": 1 + zt * 0.6, "pan_r": 1 + zt * 0.6, "drift": 1 + zt * 0.5 * (0.5 + p / 2)}[m]
        cw, ch = SRC_W / (zoom * 1.2), SRC_H / (zoom * 1.2)
        cx, cy = SRC_W / 2, SRC_H / 2
        free_x, free_y = (SRC_W - cw) / 2, (SRC_H - ch) / 2
        if m == "pan_l":
            cx += free_x * (0.8 - 1.6 * p)
        elif m == "pan_r":
            cx += free_x * (-0.8 + 1.6 * p)
        elif m == "push_up":
            cy += free_y * (0.7 - 1.4 * p)
        elif m == "drift":
            cx += free_x * 0.5 * np.sin(p * 3.0)
            cy += free_y * 0.4 * np.cos(p * 2.0)
        flash = 0.0
        if self.script["scenes"][i].get("impact") and t < 0.45:
            k = 1 - t / 0.45
            cx += np.sin(t * 90) * 16 * k
            cy += np.cos(t * 77) * 22 * k
            flash = 0.30 * k * k
        s = self.W / cw
        M = np.array([[s, 0, -(cx - cw / 2) * s], [0, s, -(cy - ch / 2) * s]], np.float32)
        img = cv2.warpAffine(self.images[i], M, (self.W, self.H), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REFLECT)
        card = self.cards[i]
        if card is not None:
            fade = min(1.0, max(0.0, (t - 0.25) / 0.35)) * min(1.0, max(0.0, (self.tl[i]["dur"] - t) / 0.3))
            card.apply(img, fade)
        if flash > 0.01:
            img = cv2.convertScaleAbs(img, alpha=1 + flash, beta=40 * flash)
        return img

    def grade(self, f: np.ndarray, n: int) -> np.ndarray:
        f = cv2.transform(f, self.cmat)                       # saturation + tint + contrast in one pass
        f = cv2.multiply(f, self.vig, scale=1 / 255.0)        # vignette
        pos, neg = self.grain[n % 6]
        if n % 2:
            pos, neg = cv2.flip(pos, 1), cv2.flip(neg, 1)
        return cv2.subtract(cv2.add(f, pos), neg)            # grain

    def frames(self):
        total = self.tl[-1]["start"] + self.tl[-1]["dur"]
        nframes = int(round(total * self.fps))
        starts = [s["start"] for s in self.tl]
        idx = 0
        for n in range(nframes):
            t = n / self.fps
            while idx + 1 < len(starts) and t >= starts[idx + 1]:
                idx += 1
            local = t - starts[idx]
            f = self.scene_frame(idx, local)
            if idx > 0 and local < self.T:
                a = _ease(local / self.T)
                prev = self.scene_frame(idx - 1, t - starts[idx - 1])
                f = cv2.addWeighted(prev, 1 - a, f, a, 0)
            yield self.grade(f, n)


def render_video(cfg, script, images, timeline, audio: np.ndarray, ass_path: Path, out_path: Path,
                 workdir: Path) -> Path:
    wav = workdir / "final_audio.wav"
    sf.write(str(wav), audio, 24000)
    r = Renderer(cfg, script, images, timeline, workdir)
    fonts = ROOT / "assets" / "fonts"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
           "-s", f"{r.W}x{r.H}", "-r", str(r.fps), "-i", "-", "-i", str(wav),
           "-vf", f"ass={ass_path.name}:fontsdir={fonts}",
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-maxrate", "6M", "-bufsize", "12M", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(ass_path.parent))
    try:
        for fr in r.frames():
            proc.stdin.write(fr.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while rendering the video")
    log.info("Rendered %s", out_path)
    return out_path
