"""Gemini wrapper: JSON output, retries with backoff, automatic fallback model."""
from __future__ import annotations

import json
import os
import re
import time

from .config import log


class LLMError(RuntimeError):
    pass


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(1))


class LLM:
    def __init__(self, cfg):
        self.cfg = cfg
        self.models = [cfg["llm"]["model"], *cfg["llm"].get("fallback_models", [])]
        self._client = None
        self._discovered = None

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types as _t
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not key:
                raise LLMError("GEMINI_API_KEY is not set")
            self._client = genai.Client(api_key=key, http_options=_t.HttpOptions(timeout=150_000))  # 150 s per call, never hang
        return self._client

    @staticmethod
    def _is_gone(msg: str) -> bool:
        m = msg.lower()
        return ("404" in m or "not_found" in m or "no longer available" in m or "is not found" in m
                or "not supported for generatecontent" in m)

    def discover_models(self) -> list[str]:
        """Ask the API which text models this key can use right now (newest 'flash' first).
        Protects the pipeline from Google retiring a model name again."""
        if self._discovered is not None:
            return self._discovered
        found = []
        try:
            for m in self.client.models.list():
                name = (getattr(m, "name", "") or "").replace("models/", "")
                actions = getattr(m, "supported_actions", None) or []
                if actions and "generateContent" not in actions:
                    continue
                mm = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-(flash|flash-lite)", name)
                if mm:
                    found.append((float(mm.group(1)), mm.group(2) == "flash", name))
        except Exception as e:
            log.warning("Could not list Gemini models: %s", str(e)[:200])
        found.sort(reverse=True)        # newest version first, plain flash before flash-lite
        self._discovered = [n for _, _, n in found]
        log.info("Discovered Gemini models: %s", self._discovered[:6])
        return self._discovered

    def json(self, prompt: str, system: str | None = None, temperature: float = 0.7, tries: int = 3):
        from google.genai import types
        last = None
        _ = self.client            # fail fast (no retries) if the API key is missing
        tried = []
        queue = list(self.models)
        discovered_added = False
        while queue:
            model = queue.pop(0)
            if model in tried:
                continue
            tried.append(model)
            for attempt in range(tries):
                try:
                    r = self.client.models.generate_content(
                        model=model, contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system, temperature=temperature,
                            response_mime_type="application/json"))
                    if model != self.models[0]:
                        log.info("Using Gemini model %s", model)
                    return _extract_json(r.text)
                except Exception as e:
                    last = e
                    msg = str(e)
                    log.warning("LLM %s attempt %d failed: %s", model, attempt + 1, msg[:200])
                    if "API key" in msg or "PERMISSION" in msg or "401" in msg or "403" in msg:
                        raise LLMError(f"Gemini authentication problem: {msg[:300]}") from e
                    if self._is_gone(msg):
                        break            # model retired / unavailable: retrying will never help
                    if "504" in msg or "DEADLINE" in msg.upper() or "timed out" in msg.lower() or "timeout" in msg.lower():
                        break            # this model is too slow right now: switch to the next one at once
                    time.sleep(min(60, 8 * (2 ** attempt)))
            if not queue and not discovered_added:
                discovered_added = True
                queue.extend(self.discover_models()[:4])
        raise LLMError(f"All Gemini models failed. Last error: {last}")
