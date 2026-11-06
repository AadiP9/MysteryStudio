"""Writer -> deterministic fact checks -> critic -> editor loop. Rejects scripts that miss the bar."""
from __future__ import annotations

import json
import re

from rapidfuzz import fuzz

from .config import log

WRITER_SYSTEM = """You are an award-winning documentary scriptwriter for vertical mystery videos
(YouTube Shorts / Reels). You write for the EAR: short sentences, concrete details, calm authority.

STORY SHAPE (adapt timings to the story; total 35-90 seconds when read aloud at ~2.3 words/second):
1. HOOK (first line, <=3 seconds): an impossible-sounding, specific, TRUE detail or a gripping question.
   Never start with "Today", "In this video", "Have you ever" or a date-only line.
2. Establish the mystery fast (who, where, the strange thing).
3. Build tension with 3-5 concrete pieces of evidence, each one raising a new question.
4. One unexpected development ("But then...") around 60% in.
5. The reveal OR the unanswered question that still haunts investigators.
6. Final line: memorable, and invites a comment naturally (a real question, not "like and subscribe").

RULES:
- Separate fact from theory: use "investigators believed", "one theory holds", "no one has proved".
- Never imply guilt of a real, named person unless a conviction/official finding is in the source.
  For unsolved cases do not name unconvicted suspects.
- No gore, no graphic detail, respectful of victims. No invented dialogue for real people.
- Use only facts present in the SOURCE TEXT for real cases. Do not invent anything.
- Numbers: write them as digits ("1971", "$200,000"); the voice engine reads them correctly.
- Each scene = 1-2 sentences of narration (6-22 words) plus a visual.
- IMAGE PROMPTS: atmospheric, cinematic, symbolic scenes of places, objects, weather, documents,
  silhouettes seen from behind or far away. NEVER faces, NEVER real people, NEVER readable text.
  Describe: subject, setting, lighting, camera angle. Vary shots (wide, close-up, overhead, detail)."""

SCENE_SPEC = """Return JSON with exactly this structure:
{
 "title": "<=70 chars, curiosity-driven, truthful, no ALL CAPS",
 "scenes": [
   {"narration": "...", "image_prompt": "...",
    "on_screen_text": "<optional: a short date/place/number card like 'NOVEMBER 24, 1971' or '$200,000'; '' if none>",
    "text_style": "kicker|big",
    "impact": false}
 ],
 "claims": [ {"claim": "<a factual statement used in the script>",
              "source_quote": "<EXACT contiguous words copied from the SOURCE TEXT that support it, max 200 chars>"} ],
 "description": "<2-3 sentences, no spoilers of the final reveal>",
 "hashtags": ["#mystery", "..."],
 "tags": ["keyword", "..."]
}
Set "impact": true on at most 3 scenes (the hook, the twist, the final reveal).
For FICTION, "claims" must be an empty list."""

CRITIC_SYSTEM = """You are a ruthless retention editor and fact-checker for short documentary videos.
Score 1-10 (be harsh; 8 means genuinely excellent):
 hook_strength, retention, clarity, suspense, accuracy, originality.
Accuracy: for REAL cases, compare every factual claim in the narration against SOURCE TEXT;
any claim that is not supported, any overstated certainty, or any implied guilt of an unconvicted
person => accuracy <= 4 and list it in "problems". For FICTION, accuracy = internal consistency and that nothing
is presented as real.
Return JSON: {"hook_strength":n,"retention":n,"clarity":n,"suspense":n,"accuracy":n,"originality":n,
"problems":["specific problem with the exact line"],"fixes":["specific rewrite instruction"]}"""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", re.sub(r"\s+", " ", s.lower())).strip()


def word_count(script: dict) -> int:
    return sum(len(s["narration"].split()) for s in script["scenes"])


def deterministic_checks(script: dict, topic: dict, qcfg: dict) -> list[str]:
    """Cheap, non-LLM guards that catch hallucinations before spending a critic call."""
    problems = []
    wc = word_count(script)
    if wc < qcfg["min_words"]:
        problems.append(f"Script is too short ({wc} words); needs at least {qcfg['min_words']}.")
    if wc > qcfg["max_words"]:
        problems.append(f"Script is too long ({wc} words); must be at most {qcfg['max_words']}.")
    if len(script["scenes"]) < 6:
        problems.append("Need at least 6 scenes.")
    if sum(1 for s in script["scenes"] if s.get("impact")) > 3:
        problems.append("At most 3 scenes may have impact=true.")
    first = script["scenes"][0]["narration"].lower()
    if re.match(r"^(today|in this video|have you ever|welcome)", first):
        problems.append("Hook starts with a banned opener.")
    if topic["kind"] == "real":
        src = _norm(topic["source_text"])
        claims = script.get("claims") or []
        if len(claims) < 4:
            problems.append("Provide at least 4 claims with exact source_quote values.")
        for c in claims:
            q = _norm(c.get("source_quote", ""))
            ok = bool(q) and (q in src or fuzz.partial_ratio(q, src) >= qcfg["claim_match_threshold"])
            if not ok:
                problems.append(f"Claim not found in source text: '{c.get('claim', '')[:120]}'")
        # every number in the narration should exist in the source
        narr = " ".join(s["narration"] for s in script["scenes"])
        for num in set(re.findall(r"\d[\d,\.]*\d|\d", narr)):
            if num.replace(",", "") not in src.replace(",", ""):
                problems.append(f"Number '{num}' does not appear in the source text.")
    for s in script["scenes"]:
        if re.search(r"\b(blood|gore|corpse|mutilat)", s["image_prompt"].lower()):
            problems.append("Image prompt contains graphic terms; use symbolic imagery instead.")
    return problems


def _material(topic: dict) -> str:
    if topic["kind"] == "real":
        return (f"REAL CASE: {topic['title']} (status: {topic['status']})\nSUGGESTED ANGLE: {topic['angle']}\n"
                f"SOURCE TEXT (the only allowed source of facts):\n\"\"\"\n{topic['source_text']}\n\"\"\"")
    return f"FICTION. Title idea: {topic['title']}\nPremise: {topic['premise']}\n(Original fiction. Tell it as a story.)"


def _critic(llm, topic, script, temp) -> dict:
    body = f"{_material(topic)}\n\nSCRIPT TO REVIEW:\n{json.dumps(script, ensure_ascii=False)}"
    return llm.json(body, system=CRITIC_SYSTEM, temperature=temp)


def _scores(c: dict) -> list[float]:
    return [float(c[k]) for k in ("hook_strength", "retention", "clarity", "suspense", "accuracy", "originality")]


def write_script(llm, cfg, topic: dict, identity: dict) -> dict:
    q, lcfg = cfg["quality"], cfg["llm"]
    prompt = (f"{_material(topic)}\n\nCHANNEL IDENTITY: {identity['brief']}\n\n{SCENE_SPEC}\n"
              "Write the best possible script for this.")
    script = llm.json(prompt, system=WRITER_SYSTEM, temperature=lcfg["temperature_writer"])
    history = []
    for rev in range(q["max_revisions"] + 1):
        problems = deterministic_checks(script, topic, q)
        critic = None
        if not problems:
            critic = _critic(llm, topic, script, lcfg["temperature_critic"])
            sc = _scores(critic)
            avg = sum(sc) / len(sc)
            log.info("Critic round %d: %s avg=%.2f", rev, [int(x) for x in sc], avg)
            if min(sc) >= q["min_each_score"] and avg >= q["min_avg_score"] and critic["accuracy"] >= 8:
                script["_quality"] = {"scores": critic, "avg": avg, "revisions": rev}
                return script
            problems = list(critic.get("problems", [])) + list(critic.get("fixes", []))
        history.append(problems)
        if rev == q["max_revisions"]:
            break
        log.info("Revising script (round %d): %s", rev + 1, problems[:3])
        fix = (f"{_material(topic)}\n\nCURRENT SCRIPT:\n{json.dumps(script, ensure_ascii=False)}\n\n"
               "PROBLEMS TO FIX (all of them):\n- " + "\n- ".join(problems[:14]) +
               f"\n\n{SCENE_SPEC}\nRewrite the full script fixing every problem. Keep what works; "
               "make the hook and the twist sharper. Every claim quote must be exact source text.")
        script = llm.json(fix, system=WRITER_SYSTEM, temperature=lcfg["temperature_writer"])
    raise ScriptRejected(f"Script for '{topic['title']}' failed quality gate after "
                         f"{q['max_revisions']} revisions. Last problems: {history[-1][:5]}")


class ScriptRejected(RuntimeError):
    pass
