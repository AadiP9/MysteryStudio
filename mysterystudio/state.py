"""Per-channel JSON ledger. One file per channel so parallel jobs never conflict in git."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import STATE_DIR


class State:
    def __init__(self, channel: str, directory: Path | None = None):
        self.dir = directory or STATE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{channel}.json"
        self.data = {"published": [], "used_topics": [], "topic_pool": [],
                     "comments_done": {}, "failures": []}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self) -> None:
        d = self.data
        d["published"] = d["published"][-400:]
        d["used_topics"] = d["used_topics"][-1500:]
        d["failures"] = d["failures"][-60:]
        if len(d["comments_done"]) > 6000:   # keep newest
            items = sorted(d["comments_done"].items(), key=lambda kv: kv[1])[-4000:]
            d["comments_done"] = dict(items)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # --- helpers
    def slot_done(self, date: str, slot: int) -> bool:
        return any(p.get("date") == date and p.get("slot") == slot for p in self.data["published"])

    def count_published(self) -> int:
        return len(self.data["published"])

    def add_published(self, **rec) -> None:
        rec.setdefault("ts", int(time.time()))
        self.data["published"].append(rec)
        self.save()

    def topic_used(self, title: str) -> bool:
        t = title.strip().lower()
        return any(t == u.strip().lower() for u in self.data["used_topics"])

    def mark_topic(self, title: str) -> None:
        self.data["used_topics"].append(title)

    def log_failure(self, stage: str, msg: str) -> None:
        self.data["failures"].append({"ts": int(time.time()), "stage": stage, "msg": msg[:400]})
