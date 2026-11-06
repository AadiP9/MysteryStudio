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

    @property
    def client(self):
        if self._client is None:
            from google import genai
            key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if not key:
                raise LLMError("GEMINI_API_KEY is not set")
            self._client = genai.Client(api_key=key)
        return self._client

    def json(self, prompt: str, system: str | None = None, temperature: float = 0.7, tries: int = 3):
        from google.genai import types
        last = None
        _ = self.client            # fail fast (no retries) if the API key is missing
        for model in self.models:
            for attempt in range(tries):
                try:
                    r = self.client.models.generate_content(
                        model=model, contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system, temperature=temperature,
                            response_mime_type="application/json"))
                    return _extract_json(r.text)
                except Exception as e:
                    last = e
                    msg = str(e)
                    log.warning("LLM %s attempt %d failed: %s", model, attempt + 1, msg[:200])
                    if "API key" in msg or "PERMISSION" in msg or "401" in msg or "403" in msg:
                        raise LLMError(f"Gemini authentication problem: {msg[:300]}") from e
                    time.sleep(min(60, 8 * (2 ** attempt)))
        raise LLMError(f"All Gemini models failed. Last error: {last}")
