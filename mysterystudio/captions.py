"""ASS captions: 3-word chunks, active word highlighted, positioned above the platform UI."""
from __future__ import annotations

import re
from pathlib import Path


def _ass_time(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _bgr(hex_rgb: str) -> str:
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H00{b}{g}{r}&"


def word_timings(text: str, start: float, speech: float) -> list[tuple[str, float, float]]:
    """Distribute words across the spoken duration, weighted by length and punctuation pauses."""
    words = text.split()
    if not words:
        return []
    weights = []
    for w in words:
        wt = len(re.sub(r"\W", "", w)) + 1.5
        if w.endswith((",", ";", ":")):
            wt += 2.5
        elif w.endswith((".", "?", "!", "...")):
            wt += 4.5
        weights.append(wt)
    total, t, out = sum(weights), start, []
    for w, wt in zip(words, weights):
        d = speech * wt / total
        out.append((w, t, t + d))
        t += d
    return out


def build_ass(cfg, script: dict, timeline: list[dict], path: Path) -> Path:
    c = cfg["captions"]
    W, H = cfg["video"]["width"], cfg["video"]["height"]
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Cap,{c['font']},{c['size']},{_bgr(c['base_color'])},{_bgr(c['base_color'])},&H00000000&,&H96000000&,0,0,0,0,100,100,2,0,1,7,3,2,90,90,{c['margin_bottom']},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = []
    n = c["words_per_chunk"]
    act, base = _bgr(c["active_color"]), _bgr(c["base_color"])
    for sc, tl in zip(script["scenes"], timeline):
        wt = word_timings(sc["narration"], tl["start"], tl["speech"])
        chunks = [wt[i:i + n] for i in range(0, len(wt), n)]
        for ch in chunks:
            for k, (w, s, e) in enumerate(ch):
                # each word-event shows the whole chunk with the active word highlighted
                end = ch[k + 1][1] if k + 1 < len(ch) else e
                parts = []
                for j, (ww, _, _) in enumerate(ch):
                    col = act if j == k else base
                    parts.append(f"{{\\c{col}}}{ww.upper().replace('{', '').replace('}', '')}")
                text = r"{\fad(40,0)}" + " ".join(parts) if k == 0 else " ".join(parts)
                lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(max(end, s + 0.05))},Cap,,0,0,0,,{text}")
    path.write_text(hdr + "\n".join(lines) + "\n", encoding="utf-8")
    return path
