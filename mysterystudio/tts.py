"""Narration: Kokoro (local, CPU, free) with Edge-TTS fallback. One clip per scene = exact timing."""
from __future__ import annotations

import asyncio
import re
import subprocess
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import MODEL_DIR, log

SR = 24000
KOKORO_URLS = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
_kokoro = None


def ensure_models() -> tuple[Path, Path]:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in KOKORO_URLS.items():
        p = MODEL_DIR / name
        if not p.exists() or p.stat().st_size < 1_000_000:
            log.info("Downloading %s ...", name)
            urllib.request.urlretrieve(url, p)
    return MODEL_DIR / "kokoro-v1.0.onnx", MODEL_DIR / "voices-v1.0.bin"


def _clean(text: str) -> str:
    text = text.replace("—", ", ").replace("–", "-").replace("…", "...")
    return re.sub(r"\s+", " ", text).strip()


def _kokoro_synth(text: str, voice: str, speed: float) -> np.ndarray:
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        m, v = ensure_models()
        _kokoro = Kokoro(str(m), str(v))
    samples, sr = _kokoro.create(text, voice=voice, speed=speed, lang="en-us")
    samples = np.asarray(samples, dtype=np.float32)
    if sr != SR:
        from scipy.signal import resample_poly
        samples = resample_poly(samples, SR, sr).astype(np.float32)
    return samples


def _edge_synth(text: str, voice: str, tmp: Path) -> np.ndarray:
    import edge_tts

    async def go():
        await edge_tts.Communicate(text, voice, rate="-6%").save(str(tmp.with_suffix(".mp3")))
    asyncio.run(go())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp.with_suffix(".mp3")),
                    "-ar", str(SR), "-ac", "1", str(tmp.with_suffix(".wav"))], check=True)
    data, _ = sf.read(str(tmp.with_suffix(".wav")), dtype="float32")
    return data


def _trim(x: np.ndarray, thresh: float = 0.004, keep: float = 0.04) -> np.ndarray:
    idx = np.where(np.abs(x) > thresh)[0]
    if len(idx) == 0:
        return x
    a = max(0, idx[0] - int(keep * SR))
    b = min(len(x), idx[-1] + int(keep * SR))
    return x[a:b]


def synth_scenes(cfg, script: dict, workdir: Path) -> dict:
    """Returns {'audio': float32 array (full narration timeline), 'scenes': [{start,dur,speech,...}]}"""
    t = cfg["tts"]
    pad, hook_pad = t["pad_seconds"], t["hook_pad_seconds"]
    chunks, timeline, cursor = [], [], 0.0
    n = len(script["scenes"])
    for i, sc in enumerate(script["scenes"]):
        text = _clean(sc["narration"])
        engine = t["engine"]
        try:
            if engine == "kokoro":
                wav = _kokoro_synth(text, t["kokoro_voice"], t["speed"])
            elif engine == "edge":
                wav = _edge_synth(text, t["edge_voice"], workdir / f"edge_{i}")
            else:
                wav = np.zeros(int(len(text.split()) / 2.4 * SR), dtype=np.float32)
        except Exception as e:
            if engine == "kokoro":
                log.warning("Kokoro failed (%s); falling back to Edge-TTS for scene %d", e, i)
                wav = _edge_synth(text, t["edge_voice"], workdir / f"edge_{i}")
            else:
                raise
        wav = _trim(wav) if engine != "fake" else wav
        p = hook_pad if i == 0 else pad
        if i == n - 1:
            p = 0.9   # hold on the last image
        silence = np.zeros(int(p * SR), dtype=np.float32)
        full = np.concatenate([wav, silence])
        timeline.append({"start": cursor, "speech": len(wav) / SR, "dur": len(full) / SR})
        cursor += len(full) / SR
        chunks.append(full)
    audio = np.concatenate(chunks)
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0:
        audio = audio / peak * 0.92 if peak > 0.92 else audio
    return {"audio": audio, "scenes": timeline, "total": cursor}
