"""Comment monitor: fetch new comments -> Gemini triage -> reply / skip / flag for human -> remember."""
from __future__ import annotations

import time

import requests

from .config import log, secret
from .errors import AuthError

TRIAGE_SYSTEM = """You manage comments for a documentary-style mystery / true-crime video channel.
For EACH comment decide an action:
- "reply": genuine viewer comment (praise, question, theory, opinion). Write a short, warm, human reply
  (max 200 characters), in the SAME language as the comment, curious and conversational. Emojis sparingly.
- "skip": spam, links/ads, self-promotion, hate, harassment, bots, empty or meaningless comments.
- "flag": needs a human: legal threats, claims about real private people, accusations of guilt, requests to
  identify suspects, personal tragedies from relatives of victims, anything sensitive or complicated.
Rules for replies: never accuse any real person; never state facts that are not in the video summary;
never promise anything; no links; do not argue; do not ask for likes/subscribes.
Return JSON list: [{"id": "...", "action": "reply|skip|flag", "reply": "..."}] for every input id."""


def triage(llm, cfg, items: list[dict]) -> dict[str, dict]:
    if not items:
        return {}
    payload = [{"id": i["id"], "video_title": i["video_title"], "video_summary": i["summary"],
                "comment": i["text"][:500]} for i in items]
    style = cfg["comments"]["channel_owner_reply_style"]
    res = llm.json(f"Reply style: {style}\n\nCOMMENTS:\n{payload}", system=TRIAGE_SYSTEM, temperature=0.6)
    return {r["id"]: r for r in res if isinstance(r, dict) and "id" in r}


def _recent_videos(cfg, state, key: str, days: int):
    cutoff = time.time() - days * 86400
    return [p for p in state.data["published"]
            if p.get("ts", 0) >= cutoff and p.get("ids", {}).get(key)]


# ----------------------------------------------------------------- YouTube
def run_youtube(cfg, llm, state, prefix: str) -> dict:
    from googleapiclient.errors import HttpError

    from .publish_youtube import service
    yt = service(prefix)
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    recs = {p["ids"]["youtube"]: p for p in _recent_videos(cfg, state, "youtube", cfg["comments"]["lookback_days"])
            if p.get("privacy") == "public"}
    new = []
    try:
        for vid, rec in recs.items():
            r = yt.commentThreads().list(part="snippet", videoId=vid, order="time", maxResults=30,
                                         textFormat="plainText").execute()
            for th in r.get("items", []):
                top = th["snippet"]["topLevelComment"]
                cid = top["id"]
                sn = top["snippet"]
                if cid in state.data["comments_done"] or th["snippet"].get("totalReplyCount", 0) > 0:
                    state.data["comments_done"].setdefault(cid, int(time.time()))
                    continue
                if (sn.get("authorChannelId") or {}).get("value") == me:
                    continue
                new.append({"id": cid, "text": sn["textDisplay"], "video_title": rec["title"],
                            "summary": rec.get("summary", "")})
    except HttpError as e:
        if "commentsDisabled" not in str(e):
            raise
    return _answer(cfg, llm, state, new,
                   lambda cid, text: yt.comments().insert(
                       part="snippet", body={"snippet": {"parentId": cid, "textOriginal": text}}).execute())


# ----------------------------------------------------------------- Meta
def run_meta(cfg, llm, state) -> dict:
    token, page = secret("META_PAGE_TOKEN"), secret("META_PAGE_ID")
    ig = secret("META_IG_USER_ID")
    api = f"https://graph.facebook.com/{cfg['publishing']['meta_graph_version']}"

    def get(path, **params):
        r = requests.get(f"{api}/{path}", params={**params, "access_token": token}, timeout=60)
        j = r.json()
        if "error" in j:
            if j["error"].get("code") in (190, 102, 10, 200):
                raise AuthError(f"Meta token/permission problem: {j['error']}")
            raise RuntimeError(f"Meta API error: {j['error']}")
        return j

    def post(path, **data):
        r = requests.post(f"{api}/{path}", data={**data, "access_token": token}, timeout=60)
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"Meta reply failed: {j['error']}")
        return j

    my_ig = get(ig, fields="username").get("username", "")
    new, kind = [], {}
    for rec in _recent_videos(cfg, state, "instagram", cfg["comments"]["lookback_days"]):
        for c in get(f"{rec['ids']['instagram']}/comments", fields="id,text,username", limit=50).get("data", []):
            if c["id"] in state.data["comments_done"] or c.get("username") == my_ig:
                continue
            new.append({"id": c["id"], "text": c.get("text", ""), "video_title": rec["title"],
                        "summary": rec.get("summary", "")})
            kind[c["id"]] = "ig"
    for rec in _recent_videos(cfg, state, "facebook", cfg["comments"]["lookback_days"]):
        for c in get(f"{rec['ids']['facebook']}/comments", fields="id,message,from", filter="toplevel",
                     limit=50).get("data", []):
            if c["id"] in state.data["comments_done"] or (c.get("from") or {}).get("id") == page:
                continue
            new.append({"id": c["id"], "text": c.get("message", ""), "video_title": rec["title"],
                        "summary": rec.get("summary", "")})
            kind[c["id"]] = "fb"

    def reply(cid, text):
        if kind[cid] == "ig":
            post(f"{cid}/replies", message=text)
        else:
            post(f"{cid}/comments", message=text)
    return _answer(cfg, llm, state, new, reply)


# ----------------------------------------------------------------- shared
def _answer(cfg, llm, state, items, send) -> dict:
    cap = cfg["comments"]["max_replies_per_run"]
    items = items[:40]
    decisions = triage(llm, cfg, items[:cap * 2]) if items else {}
    stats = {"seen": len(items), "replied": 0, "skipped": 0, "flagged": []}
    for it in items:
        d = decisions.get(it["id"])
        if not d:
            continue
        if d["action"] == "reply" and d.get("reply") and stats["replied"] < cap:
            try:
                send(it["id"], d["reply"][:300])
                stats["replied"] += 1
                time.sleep(2)
            except Exception as e:
                log.warning("Reply failed for %s: %s", it["id"], str(e)[:200])
                continue
        elif d["action"] == "flag":
            stats["flagged"].append({"comment": it["text"][:200], "video": it["video_title"]})
        else:
            stats["skipped"] += 1
        state.data["comments_done"][it["id"]] = int(time.time())
    state.save()
    return stats
