"""Instagram Reels + Facebook Page Reels through the Graph API, using resumable binary upload
(no public video URL needed). Uses a never-expiring Page access token."""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .config import log, secret
from .errors import AuthError

TIMEOUT = 120


def _check(r: requests.Response, what: str):
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:300]}
    if r.status_code >= 400 or "error" in j:
        err = j.get("error", j)
        code = err.get("code") if isinstance(err, dict) else None
        if code in (190, 102, 10, 200) or r.status_code == 401:
            raise AuthError(f"Meta {what}: token/permission problem: {err}. Re-run scripts/meta_setup.py.")
        raise RuntimeError(f"Meta {what} failed: {err}")
    return j


def _api(cfg) -> str:
    return f"https://graph.facebook.com/{cfg['publishing']['meta_graph_version']}"


def publish_instagram(cfg, video: Path, caption: str) -> dict:
    token, ig = secret("META_PAGE_TOKEN"), secret("META_IG_USER_ID")
    api = _api(cfg)
    r = requests.post(f"{api}/{ig}/media", timeout=TIMEOUT, data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2150],
        "share_to_feed": "true", "access_token": token})
    j = _check(r, "IG create container")
    cid, uri = j["id"], j["uri"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(uri, timeout=600, data=f, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
    _check(up, "IG upload")
    for _ in range(60):                                   # up to ~10 min of processing
        st = _check(requests.get(f"{api}/{cid}", timeout=TIMEOUT,
                                 params={"fields": "status_code,status", "access_token": token}), "IG status")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing failed: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Instagram processing timed out")
    pub = _check(requests.post(f"{api}/{ig}/media_publish", timeout=TIMEOUT,
                               data={"creation_id": cid, "access_token": token}), "IG publish")
    log.info("Instagram Reel published: %s", pub["id"])
    return {"id": pub["id"]}


def publish_facebook(cfg, video: Path, caption: str) -> dict:
    token, page = secret("META_PAGE_TOKEN"), secret("META_PAGE_ID")
    api = _api(cfg)
    start = _check(requests.post(f"{api}/{page}/video_reels", timeout=TIMEOUT, data={
        "upload_phase": "start", "access_token": token}), "FB reel start")
    vid, upload_url = start["video_id"], start["upload_url"]
    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(upload_url, timeout=600, data=f, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
    _check(up, "FB reel upload")
    fin = _check(requests.post(f"{api}/{page}/video_reels", timeout=TIMEOUT, data={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption[:2000], "access_token": token}), "FB reel finish")
    for _ in range(30):
        st = _check(requests.get(f"{api}/{vid}", timeout=TIMEOUT,
                                 params={"fields": "status", "access_token": token}), "FB status")
        phase = (st.get("status") or {}).get("video_status")
        if phase in ("ready", "published"):
            break
        if phase == "error":
            raise RuntimeError(f"Facebook processing failed: {st}")
        time.sleep(10)
    log.info("Facebook Reel published: %s (%s)", vid, fin)
    return {"id": vid}
