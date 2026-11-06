"""Original dark-ambient score + sound effects, synthesised with numpy (no copyright claims, ever)."""
from __future__ import annotations

import numpy as np

SR = 24000


def _lowpass(x: np.ndarray, k: int) -> np.ndarray:
    c = np.cumsum(np.insert(x, 0, 0.0))
    y = (c[k:] - c[:-k]) / k
    return np.pad(y, (k // 2, len(x) - len(y) - k // 2))


def drone(duration: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(duration * SR)
    t = np.arange(n) / SR
    root = rng.choice([55.0, 49.0, 51.9, 58.3, 46.2])       # low A/G/Ab/Bb/F#
    minor = [1.0, 1.189, 1.498, 2.0]                        # root, m3, 5th, octave
    out = np.zeros(n)
    for i, ratio in enumerate(minor):
        f = root * ratio * (1 + rng.uniform(-0.002, 0.002))
        lfo = 0.5 + 0.5 * np.sin(2 * np.pi * rng.uniform(0.04, 0.11) * t + rng.uniform(0, 6.28))
        amp = [0.55, 0.12, 0.18, 0.10][i]
        out += amp * lfo * (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t))
    sub = 0.35 * np.sin(2 * np.pi * (root / 2) * t)
    wind = _lowpass(rng.normal(0, 1, n), 60) * 2.2
    wind *= 0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6))
    # soft heartbeat-like pulse that gets slightly faster toward the end
    pulse = np.zeros(n)
    bpm_t = 0.0
    while bpm_t < duration:
        i = int(bpm_t * SR)
        L = int(0.22 * SR)
        if i + L < n:
            env = np.exp(-np.linspace(0, 9, L))
            pulse[i:i + L] += 0.20 * env * np.sin(2 * np.pi * 48 * np.arange(L) / SR)
        bpm_t += 1.5 - 0.5 * (bpm_t / duration)
    mix = out + sub + wind * 0.25 + pulse
    fade = int(2.0 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)
    mix[-fade:] *= np.linspace(1, 0, fade)
    return (mix / (np.max(np.abs(mix)) + 1e-9)).astype(np.float32)


def impact(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(1.6 * SR)
    t = np.arange(n) / SR
    f = 80 * np.exp(-t * 3.0) + 38
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.6)
    hit = _lowpass(rng.normal(0, 1, n), 12) * np.exp(-t * 14) * 1.4
    y = boom + hit
    return (y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def riser(duration: float = 1.4) -> np.ndarray:
    n = int(duration * SR)
    t = np.arange(n) / SR
    f = 120 * np.exp(t / duration * np.log(9))
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / duration) ** 2.2
    return (y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def _envelope(x: np.ndarray, win: float = 0.12) -> np.ndarray:
    k = max(1, int(win * SR))
    env = _lowpass(np.abs(x), k)
    return env / (np.max(env) + 1e-9)


def mix(narration: np.ndarray, scene_times: list[dict], impacts: list[int], seed: int) -> np.ndarray:
    """Narration + ducked drone + impacts at flagged scene starts. Output float32 at 24 kHz."""
    n = len(narration)
    music = drone(n / SR + 1, seed)[:n] * 0.30
    duck = 1.0 - 0.62 * np.clip(_envelope(narration) * 3.0, 0, 1)
    duck = _lowpass(duck, int(0.15 * SR))
    music = music * duck
    fx = np.zeros(n, dtype=np.float32)
    for k, i in enumerate(impacts):
        s = int(scene_times[i]["start"] * SR)
        hit = impact(seed + k) * 0.55
        fx[s:s + len(hit)] += hit[: max(0, n - s)] if s < n else 0
        if i > 0:                                     # riser leading into the impact
            r = riser() * 0.16
            e = s
            b = max(0, e - len(r))
            fx[b:e] += r[len(r) - (e - b):]
    out = narration * 1.0 + music + fx * 0.8
    peak = np.max(np.abs(out)) + 1e-9
    return (out / peak * 0.95).astype(np.float32)
