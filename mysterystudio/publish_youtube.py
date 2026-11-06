"""YouTube upload via Data API v3 (resumable). Each channel has its OWN Google Cloud project + OAuth token,
so each channel gets its own 10,000-unit daily quota (an upload costs 1,600)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .config import log, secret
from .errors import AuthError, QuotaError

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


def service(prefix: str):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=secret(f"{prefix}_REFRESH_TOKEN"),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=secret(f"{prefix}_CLIENT_ID"), client_secret=secret(f"{prefix}_CLIENT_SECRET"),
                        scopes=SCOPES)
    try:
        creds.refresh(Request())
    except RefreshError as e:
        raise AuthError(f"{prefix}: Google refresh token rejected ({e}). Re-run scripts/youtube_auth.py "
                        f"for this channel and update the {prefix}_REFRESH_TOKEN secret. "
                        "(Tokens expire after 7 days if the OAuth app is still in 'Testing' mode - "
                        "publish the app to 'In production'.)") from e
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(cfg, prefix: str, video: Path, meta: dict, privacy: str) -> dict:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    p = cfg["publishing"]
    yt = service(prefix)
    tags, total = [], 0
    for t in meta["tags"]:
        if total + len(t) + 1 > 450:
            break
        tags.append(t[:60])
        total += len(t) + 1
    body = {"snippet": {"title": meta["title"], "description": meta["description"], "tags": tags,
                        "categoryId": p["youtube_category_id"],
                        "defaultLanguage": p["youtube_default_language"],
                        "defaultAudioLanguage": p["youtube_default_language"]},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": p["made_for_kids"],
                       "containsSyntheticMedia": p["contains_synthetic_media"]}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024,
                                                        resumable=True, mimetype="video/mp4"))
    resp, retries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            reason = str(e)
            if e.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                time.sleep(2 ** retries)
                continue
            if "quotaExceeded" in reason or "uploadLimitExceeded" in reason:
                raise QuotaError(f"{prefix}: YouTube quota/upload limit reached: {reason[:300]}") from e
            if e.resp.status in (401, 403) and "forbidden" in reason.lower():
                raise AuthError(f"{prefix}: YouTube rejected the request: {reason[:300]}") from e
            raise
    vid = resp["id"]
    actual = resp.get("status", {}).get("privacyStatus", privacy)
    log.info("YouTube upload OK: %s (privacy=%s)", vid, actual)
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}", "privacy": actual,
            "forced_private": privacy == "public" and actual == "private"}
