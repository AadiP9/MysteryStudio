"""Topic discovery + source gathering. Real cases are grounded in Wikipedia article text."""
from __future__ import annotations

import random
import re

import requests

from .config import USER_AGENT, log

WIKI_API = "https://en.wikipedia.org/w/api.php"
H = {"User-Agent": USER_AGENT}

POOL_PROMPT = """You help a documentary-style mystery channel choose cases.
CHANNEL FOCUS: {brief}

Return JSON: a list of {n} items, each {{"wiki_title": "<exact English Wikipedia article title>",
"angle": "<one sentence: the most gripping angle for a 45-75 second story>",
"status": "<unsolved|solved|disputed>"}}.

Rules:
- Only cases that have a real English Wikipedia article with substantial detail.
- Mix eras and countries; prefer cases with a surprising detail or twist.
- Avoid extremely graphic cases, child victims, ongoing trials and living private individuals.
- Do NOT include any of these already-used cases: {used}
- Do not repeat the same case twice."""

FICTION_PROMPT = """Invent {n} ORIGINAL psychological-mystery short story premises for vertical videos.
CHANNEL FOCUS: {brief}

Return JSON list of {n} items: {{"title": "<working title>", "premise": "<2-3 sentences: setting, the
unsettling event, and the twist that recontextualises it>"}}.
Rules: no real people or real events; no gore; fresh ideas, not clichés (no haunted dolls, no 'it was
the narrator all along' unless done with a new angle). Avoid these used titles: {used}"""


def wiki_extract(title: str, max_chars: int = 14000) -> dict | None:
    """Fetch plain-text article for a title; returns {title,url,text} or None."""
    r = requests.get(WIKI_API, headers=H, timeout=30, params={
        "action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
        "redirects": 1, "titles": title, "exsectionformat": "plain"})
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    for p in pages.values():
        text = p.get("extract") or ""
        if p.get("missing") is not None or len(text) < 2500:
            return None
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.split(r"\n(?:See also|References|External links|Further reading|Notes)\n", text)[0]
        t = p["title"]
        return {"title": t, "url": "https://en.wikipedia.org/wiki/" + t.replace(" ", "_"),
                "text": text[:max_chars]}
    return None


def wiki_search(query: str) -> str | None:
    r = requests.get(WIKI_API, headers=H, timeout=30, params={
        "action": "query", "format": "json", "list": "search", "srsearch": query, "srlimit": 1})
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def pick_real_topic(llm, state, identity: dict) -> dict:
    """Return {kind, title, angle, status, url, source_text}. Refills the pool via Gemini when empty."""
    for _ in range(2):
        pool = state.data["topic_pool"]
        random.shuffle(pool)
        while pool:
            item = pool.pop()
            if state.topic_used(item["wiki_title"]):
                continue
            art = wiki_extract(item["wiki_title"])
            if not art:
                found = wiki_search(item["wiki_title"])
                art = wiki_extract(found) if found else None
            if not art or state.topic_used(art["title"]):
                continue
            return {"kind": "real", "title": art["title"], "angle": item.get("angle", ""),
                    "status": item.get("status", "unknown"), "url": art["url"],
                    "source_text": art["text"]}
        log.info("Refilling topic pool via Gemini")
        used = ", ".join(state.data["used_topics"][-120:]) or "none"
        new = llm.json(POOL_PROMPT.format(brief=identity["brief"], n=25, used=used), temperature=1.0)
        state.data["topic_pool"] = [i for i in new if isinstance(i, dict) and i.get("wiki_title")]
        state.save()
    raise RuntimeError("Could not find an unused real case after refilling the pool")


def pick_fiction_topic(llm, state, identity: dict) -> dict:
    for _ in range(2):
        pool = [p for p in state.data["topic_pool"] if "premise" in p]
        random.shuffle(pool)
        while pool:
            item = pool.pop()
            state.data["topic_pool"] = [p for p in state.data["topic_pool"] if p is not item]
            if state.topic_used(item["title"]):
                continue
            return {"kind": "fiction", "title": item["title"], "premise": item["premise"],
                    "angle": item["premise"], "status": "fiction", "url": "", "source_text": ""}
        used = ", ".join(state.data["used_topics"][-80:]) or "none"
        new = llm.json(FICTION_PROMPT.format(brief=identity["brief"], n=15, used=used), temperature=1.0)
        state.data["topic_pool"] = [i for i in new if isinstance(i, dict) and i.get("premise")]
        state.save()
    raise RuntimeError("Could not generate an unused fiction premise")
