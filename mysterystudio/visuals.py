"""Scene imagery. Free AI stills (Pollinations/FLUX) with a procedural atmospheric fallback that never fails."""
from __future__ import annotations

import hashlib
import time
import urllib.parse

import cv2
import numpy as np
import requests

from .config import USER_AGENT, log

SRC_W, SRC_H = 1296, 2304          # 20% larger than 1080x1920 so the camera can move


# ------------------------------------------------------------------ procedural
def _noise(h, w, cells, rng):
    small = rng.random((max(2, int(cells * h / w)), cells)).astype(np.float32)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC)


def _fog(h, w, rng, strength=0.5):
    f = sum(_noise(h, w, c, rng) * a for c, a in ((3, .5), (7, .3), (15, .2)))
    return np.clip((f - f.min()) / (np.ptp(f) + 1e-6), 0, 1) * strength


def _base_sky(h, w, rng, palette):
    top, bot = np.array(palette[0], np.float32), np.array(palette[1], np.float32)
    g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    img = top * (1 - g) + bot * g
    img = np.broadcast_to(img, (h, w, 3)).copy()
    # moon / light source glow
    cx, cy = int(w * rng.uniform(.25, .75)), int(h * rng.uniform(.14, .32))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    img += (np.exp(-d / (w * .12))[..., None] * np.array([150, 170, 175], np.float32) * .55)
    cv2.circle(img, (cx, cy), int(w * .035), (235, 240, 235), -1, cv2.LINE_AA)
    return img


def _skyline(h, w, rng):
    img = _base_sky(h, w, rng, [(48, 30, 20), (90, 70, 50)])
    for layer, (col, hmax, ground) in enumerate([((58, 46, 38), .50, .62), ((18, 14, 12), .62, .74)]):
        x = 0
        while x < w:
            bw = int(rng.uniform(.06, .17) * w)
            bh = int(rng.uniform(.18, hmax) * h * (0.7 + 0.3 * layer))
            cv2.rectangle(img, (x, int(ground * h) - bh), (x + bw, h), col, -1)
            if layer == 1:
                for _ in range(int(bw * bh / 9000)):
                    wx, wy = x + int(rng.uniform(.08, .85) * bw), int(ground * h) - int(rng.uniform(.05, .95) * bh)
                    if rng.random() < .22:
                        cv2.rectangle(img, (wx, wy), (wx + 12, wy + 18), (90, 190, 235), -1)
            x += bw + int(rng.uniform(0, .02) * w)
        img += _fog(h, w, rng, 22)[..., None] * (1 - layer * .5)
    return img


def _forest(h, w, rng):
    img = _base_sky(h, w, rng, [(40, 28, 18), (70, 62, 45)])
    for layer, col in enumerate([(52, 48, 36), (30, 28, 20), (10, 10, 8)]):
        base = int(h * (.62 + .1 * layer))
        pts = [(0, h)]
        x = 0
        while x < w + 60:
            th = int(rng.uniform(.12, .38) * h * (1 + .25 * layer))
            tw = int(rng.uniform(.04, .09) * w * (1 + .3 * layer))
            tri = np.array([[x - tw, base], [x, base - th], [x + tw, base]], np.int32)
            cv2.fillPoly(img, [tri], col, cv2.LINE_AA)
            x += int(tw * rng.uniform(.8, 1.5))
        cv2.rectangle(img, (0, base), (w, h), col, -1)
        img += _fog(h, w, rng, 30)[..., None] * (1 - layer * .3)
    return img


def _corridor(h, w, rng):
    img = np.zeros((h, w, 3), np.float32) + 14
    vx, vy = int(w * rng.uniform(.42, .58)), int(h * .46)
    for k in range(1, 26):
        s = k / 25
        x0, x1 = int(vx - vx * s), int(vx + (w - vx) * s)
        y0, y1 = int(vy - vy * s), int(vy + (h - vy) * s)
        col = (int(22 + 18 * (1 - s)), int(26 + 16 * (1 - s)), int(30 + 12 * (1 - s)))
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 3, cv2.LINE_AA)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt((xx - vx) ** 2 + (yy - vy) ** 2)
    img += np.exp(-d / (w * .16))[..., None] * np.array([120, 190, 235], np.float32) * 1.1
    cv2.rectangle(img, (vx - 55, vy - 90), (vx + 55, vy + 90), (200, 235, 250), -1)
    img += _fog(h, w, rng, 40)[..., None]
    return img


def _water(h, w, rng):
    img = _base_sky(h, w, rng, [(40, 26, 16), (84, 66, 48)])
    hz = int(h * .56)
    img[hz:] = img[hz:] * .25 + np.array([26, 20, 14], np.float32)
    for _ in range(260):
        y = int(rng.uniform(hz, h))
        x = int(rng.uniform(0, w))
        L = int(rng.uniform(.03, .16) * w * (1 + (y - hz) / h))
        cv2.line(img, (x, y), (x + L, y), (90, 80, 62), 2, cv2.LINE_AA)
    img += _fog(h, w, rng, 34)[..., None] * np.linspace(1, .2, h, dtype=np.float32)[:, None, None]
    return img


def procedural(prompt: str, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = prompt.lower()
    if any(k in p for k in ("forest", "woods", "trees", "pine", "wilderness", "mountain")):
        fn = _forest
    elif any(k in p for k in ("corridor", "hallway", "room", "door", "house", "interior", "hotel", "cabin")):
        fn = _corridor
    elif any(k in p for k in ("sea", "ocean", "lake", "river", "ship", "water", "coast", "shore")):
        fn = _water
    else:
        fn = _skyline
    img = fn(SRC_H, SRC_W, rng)
    return np.clip(img, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ AI stills
def _cover(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = max(SRC_W / w, SRC_H / h)
    img = cv2.resize(img, (int(w * s) + 1, int(h * s) + 1), interpolation=cv2.INTER_CUBIC)
    y0, x0 = (img.shape[0] - SRC_H) // 2, (img.shape[1] - SRC_W) // 2
    return img[y0:y0 + SRC_H, x0:x0 + SRC_W]


def _pollinations(prompt: str, cfg, seed: int) -> np.ndarray | None:
    ic = cfg["images"]
    full = f"{prompt}. {' '.join(ic['style_suffix'].split())}"
    url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(full) +
           f"?width=1080&height=1920&model={ic['pollinations_model']}&nologo=true&seed={seed}&private=true")
    for attempt in range(2):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=ic["timeout_seconds"])
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if img is not None and img.shape[0] > 400 and float(img.std()) > 12:
                    return _cover(img)
            log.warning("Pollinations HTTP %s (attempt %d)", r.status_code, attempt + 1)
        except Exception as e:
            log.warning("Pollinations error: %s", str(e)[:120])
        time.sleep(4)
    return None


def scene_images(cfg, script: dict) -> list[np.ndarray]:
    out = []
    base_seed = int(hashlib.md5(script["title"].encode()).hexdigest()[:8], 16)
    for i, sc in enumerate(script["scenes"]):
        img = None
        for prov in cfg["images"]["providers"]:
            if prov == "pollinations":
                img = _pollinations(sc["image_prompt"], cfg, base_seed + i)
            elif prov == "procedural":
                img = procedural(sc["image_prompt"], base_seed + i)
            if img is not None:
                log.info("Scene %d image via %s", i, prov)
                break
        out.append(img)
        time.sleep(1.0)
    return out
