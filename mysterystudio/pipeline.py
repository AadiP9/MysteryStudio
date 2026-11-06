"""End-to-end production of ONE video for ONE channel (no publishing here)."""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import soundfile as sf

from . import captions, music, qc, render, research, scriptgen, tts, visuals
from .config import OUT_DIR, log


def build_metadata(cfg, script: dict, topic: dict) -> dict:
    tags = [t.strip("# ") for t in script.get("tags", [])][:15]
    hashtags = " ".join(h if h.startswith("#") else f"#{h}" for h in script.get("hashtags", [])[:5])
    lines = [script["description"].strip(), ""]
    if topic["kind"] == "real":
        lines += [f"Source: {topic['url']}", "Visuals are AI-generated, atmospheric illustrations - "
                  "not real footage of the events."]
    else:
        lines += ["This is an original work of fiction. Any resemblance to real events is coincidental.",
                  "Visuals are AI-generated."]
    lines += ["", "What do you think really happened? Tell us below.", "", f"{hashtags} #Shorts"]
    title = script["title"].strip()
    if topic["kind"] == "fiction" and "fiction" not in title.lower():
        title = title[:60].rstrip() + " (Fiction)"
    return {"title": title[:98], "description": "\n".join(lines)[:4800], "tags": tags,
            "caption": "\n".join(lines[:1] + [""] + [hashtags])[:2000]}


def produce(cfg, llm, state, channel_key: str, slot_tag: str, offline_script: dict | None = None) -> dict:
    ch = cfg["channels"][channel_key]
    identity = cfg["identities"][ch["identity"]]
    work = OUT_DIR / f"{channel_key}_{slot_tag}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    # 1. topic + script
    if offline_script:
        topic, script = offline_script["topic"], offline_script["script"]
    else:
        mode = identity["mode"]
        if mode == "mixed":
            mode = "fiction" if random.random() < identity.get("fiction_ratio", 0.25) else "real"
        picker = research.pick_fiction_topic if mode == "fiction" else research.pick_real_topic
        topic = picker(llm, state, identity)
        log.info("Topic: %s (%s)", topic["title"], topic["kind"])
        script = scriptgen.write_script(llm, cfg, topic, identity)
    (work / "script.json").write_text(json.dumps({"topic": {k: v for k, v in topic.items() if k != "source_text"},
                                                  "script": script}, indent=1, ensure_ascii=False), encoding="utf-8")

    # 2. narration
    nar = tts.synth_scenes(cfg, script, work)
    log.info("Narration %.1fs", nar["total"])

    # 3. music + fx
    impacts = [i for i, s in enumerate(script["scenes"]) if s.get("impact")]
    import hashlib
    seed = int(hashlib.md5(script["title"].encode()).hexdigest()[:6], 16) % 10_000
    audio = music.mix(nar["audio"], nar["scenes"], impacts, seed)
    sf.write(str(work / "narration.wav"), nar["audio"], 24000)

    # 4. visuals
    images = visuals.scene_images(cfg, script)

    # 5. captions + render
    ass = captions.build_ass(cfg, script, nar["scenes"], work / "captions.ass")
    out = work / "video.mp4"
    render.render_video(cfg, script, images, nar["scenes"], audio, ass, out, work)

    # 6. QC
    report = qc.check_video(cfg, out)
    log.info("QC passed: %s", report)

    meta = build_metadata(cfg, script, topic)
    (work / "metadata.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"video": out, "meta": meta, "topic": topic, "script": script, "qc": report, "work": work}
