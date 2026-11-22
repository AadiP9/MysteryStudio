"""Image sources: real Wikimedia photos (real cases) + free AI generators (Cloudflare / Hugging Face)."""
from __future__ import annotations

import base64
import os
import re
import urllib.parse

import cv2
import numpy as np
import requests

from .config import USER_AGENT, log

WIKI_API = "https://en.wikipedia.org/w/api.php"
OK_LICENSE = re.compile(r"public domain|pd-|cc0|cc[- ]by(?!.*nc)|cc[- ]by-sa|attribution", re.I)
BAD_NAME = re.compile(r"\.(svg|gif|tif|tiff|webm|ogv|pdf)$|logo|flag|icon|signature|map|coat_of_arms|"
                      r"commons-|wiki|symbol|autopsy|body|corpse|crime_scene", re.I)


def _get(url, **kw):
    kw.setdefault("timeout", 30)
    kw.setdefault("headers", {"User-Agent": USER_AGENT})
    return requests.get(url, **kw)


def _decode(content: bytes):
    img = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if img is not None and img.shape[0] > 300 and float(img.std()) > 10:
        return img
    return None


# ------------------------------------------------------------------ real photos
def wiki_title_from_url(url: str) -> str | None:
    m = re.search(r"/wiki/([^?#]+)", url or "")
    return urllib.parse.unquote(m.group(1)).replace("_", " ") if m else None


def wikipedia_photos(title: str, limit: int = 6) -> list[tuple[np.ndarray, str]]:
    """Freely licensed images from the article. Returns [(bgr_image, credit_line)]."""
    out = []
    try:
        r = _get(WIKI_API, params={"action": "query", "format": "json", "generator": "images", "titles": title,
                                   "gimlimit": 40, "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                                   "iiurlwidth": 1100}).json()
        pages = list((r.get("query") or {}).get("pages", {}).values())
    except Exception as e:
        log.warning("Wikipedia image lookup failed: %s", str(e)[:120])
        return out
    for p in pages:
        if len(out) >= limit:
            break
        info = (p.get("imageinfo") or [{}])[0]
        name = p.get("title", "")
        if BAD_NAME.search(name) or info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < 500 or info.get("height", 0) < 400:
            continue
        meta = info.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not OK_LICENSE.search(lic):
            continue
        try:
            img = _decode(_get(info.get("thumburl") or info["url"]).content)
        except Exception:
            img = None
        if img is None:
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()[:60]
        out.append((img, f"{name.replace('File:', '')[:60]} ({lic}{', ' + artist if artist else ''}), via Wikimedia Commons"))
    log.info("Wikipedia: %d usable real photos for '%s'", len(out), title)
    return out


# ------------------------------------------------------------------ AI generators
def cloudflare(prompt: str, timeout: int = 60):
    acc, tok = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    if not (acc and tok):
        return None
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout,
                          json={"prompt": prompt[:2000], "steps": 6})
        if r.status_code == 200:
            b64 = (r.json().get("result") or {}).get("image")
            if b64:
                return _decode(base64.b64decode(b64))
        log.warning("Cloudflare AI HTTP %s %s", r.status_code, r.text[:120])
    except Exception as e:
        log.warning("Cloudflare AI error: %s", str(e)[:120])
    return None


def huggingface(prompt: str, timeout: int = 90):
    tok = os.getenv("HF_TOKEN")
    if not tok:
        return None
    url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    try:
        r = requests.post(url, headers={"Authorization": f"Bearer {tok}"}, timeout=timeout,
                          json={"inputs": prompt[:1500], "parameters": {"width": 768, "height": 1344}})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return _decode(r.content)
        log.warning("HuggingFace HTTP %s %s", r.status_code, r.text[:120])
    except Exception as e:
        log.warning("HuggingFace error: %s", str(e)[:120])
    return None


def pixabay(query: str, timeout: int = 30):
    key = os.getenv("PIXABAY_KEY")
    if not key:
        return None
    try:
        r = _get("https://pixabay.com/api/", params={"key": key, "q": " ".join(query.split()[:6]),
                                                       "image_type": "photo", "orientation": "vertical",
                                                       "safesearch": "true", "per_page": 5}, timeout=timeout).json()
        for h in r.get("hits", []):
            img = _decode(_get(h["largeImageURL"]).content)
            if img is not None:
                return img
    except Exception as e:
        log.warning("Pixabay error: %s", str(e)[:120])
    return None
