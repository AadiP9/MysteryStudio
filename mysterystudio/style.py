"""Per-video style presets: every video gets its own grade, caption look, voice, score and story shape."""
from __future__ import annotations

import copy
import hashlib
import random

LOOKS = {
    "cold_noir":   dict(tint=[0.93, 1.00, 1.08], saturation=0.70, vignette=0.60, grain=0.012, zoom_total=0.14),
    "warm_amber":  dict(tint=[1.08, 1.00, 0.90], saturation=0.85, vignette=0.50, grain=0.010, zoom_total=0.12),
    "bleach":      dict(tint=[1.00, 1.00, 1.00], saturation=0.40, vignette=0.65, grain=0.016, zoom_total=0.16),
    "green_dread": dict(tint=[0.92, 1.07, 0.94], saturation=0.68, vignette=0.58, grain=0.012, zoom_total=0.14),
    "teal_orange": dict(tint=[1.06, 1.00, 1.06], saturation=0.95, vignette=0.45, grain=0.008, zoom_total=0.15),
    "crimson":     dict(tint=[1.10, 0.95, 0.92], saturation=0.80, vignette=0.62, grain=0.012, zoom_total=0.13),
}
CAPTIONS = {
    "bold_cyan":  dict(font="Anton", size=118, words_per_chunk=3, active_color="00D7FF", base_color="FFFFFF", margin_bottom=560),
    "bold_gold":  dict(font="Anton", size=124, words_per_chunk=2, active_color="FFC107", base_color="FFFFFF", margin_bottom=600),
    "calm_red":   dict(font="Anton", size=104, words_per_chunk=4, active_color="FF3B3B", base_color="F2F2F2", margin_bottom=520),
    "lime_punch": dict(font="Anton", size=130, words_per_chunk=2, active_color="9CFF3A", base_color="FFFFFF", margin_bottom=580),
}
VOICES = [("am_michael", 0.93), ("am_adam", 0.95), ("bm_george", 0.95), ("bm_lewis", 0.93),
          ("am_fenrir", 0.94), ("bm_fable", 0.96)]
MUSIC = ["dread", "cold", "tense", "haunt"]

STRUCTURES = {
    "real": [
        "COLD OPEN: start at the most chilling single moment, then rewind to how it began and build back to it.",
        "CHRONOLOGICAL COUNTDOWN: tell it as a ticking clock with timestamps ('11:42 PM', 'Three days later').",
        "THE QUESTION: pose one unanswerable question in the hook and let every scene add a clue that deepens it.",
        "TWO VERSIONS: present what officials said vs what the evidence suggests, ending on the gap between them.",
        "THE DETAIL: build the whole story around one small strange detail that never made sense.",
    ],
    "fiction": [
        "FOUND RECORD: tell it as a transcript, log or message thread that slowly reveals the horror.",
        "FIRST PERSON: a calm narrator describing something that went wrong, with a quiet final-line twist.",
        "RULES: the story is a set of rules someone must follow, and the last rule is the scariest.",
        "LOOP: the ending reveals the story has been repeating, rewriting the meaning of the hook.",
        "THE VISITOR: an ordinary place, one wrong thing arrives, escalate in three clear beats.",
    ],
}


def pick(title: str, rng_seed: int | None = None) -> dict:
    h = int(hashlib.md5(title.encode()).hexdigest()[:8], 16)
    r = random.Random(h if rng_seed is None else rng_seed)
    voice, speed = r.choice(VOICES)
    return {"look": r.choice(list(LOOKS)), "captions": r.choice(list(CAPTIONS)),
            "voice": voice, "speed": speed, "music": r.choice(MUSIC)}


def apply(cfg: dict, title: str) -> tuple[dict, dict]:
    """Return (cfg copy with the style baked in, style description)."""
    st = pick(title)
    c = copy.deepcopy(cfg)
    c["look"].update(LOOKS[st["look"]])
    c["captions"].update(CAPTIONS[st["captions"]])
    if c["tts"].get("engine") == "kokoro":
        c["tts"]["kokoro_voice"], c["tts"]["speed"] = st["voice"], st["speed"]
    c["music_mood"] = st["music"]
    return c, st


def structure_hint(kind: str) -> str:
    return random.choice(STRUCTURES["fiction" if kind == "fiction" else "real"])
