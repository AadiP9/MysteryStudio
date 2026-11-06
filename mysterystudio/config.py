"""Config loading, paths and logging helpers."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_PATH = ASSETS / "fonts" / "Anton-Regular.ttf"
STATE_DIR = ROOT / "state"
OUT_DIR = Path(os.getenv("MS_OUT_DIR", ROOT / "out"))
MODEL_DIR = Path(os.getenv("MS_MODEL_DIR", ROOT / "models"))
USER_AGENT = "MysteryStudio/1.0 (personal content project)"

log = logging.getLogger("ms")


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")


class Cfg(dict):
    """dict with attribute access; nested dicts are wrapped lazily."""

    def __getattr__(self, k):
        try:
            v = self[k]
        except KeyError as e:
            raise AttributeError(k) from e
        return Cfg(v) if isinstance(v, dict) else v


def load_config(path: str | Path | None = None) -> Cfg:
    p = Path(path or os.getenv("MS_CONFIG", ROOT / "config.yaml"))
    with open(p, encoding="utf-8") as f:
        return Cfg(yaml.safe_load(f))


def tz(cfg) -> ZoneInfo:
    return ZoneInfo(cfg["timezone"])


def secret(name: str, required: bool = True) -> str | None:
    v = os.getenv(name)
    if required and not v:
        raise RuntimeError(f"Missing required secret/environment variable: {name}")
    return v


def load_dotenv(path: Path | None = None) -> None:
    """Tiny .env loader for local runs (GitHub Actions injects secrets as real env vars)."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
