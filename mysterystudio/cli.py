"""Command line entry points:  run | comments | report"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import traceback

from . import comments as comments_mod
from . import notify
from .config import OUT_DIR, STATE_DIR, load_config, load_dotenv, log, setup_logging, tz
from .errors import AuthError, QuotaError
from .llm import LLM
from .state import State


def _now(cfg):
    return dt.datetime.now(tz(cfg))


def cmd_run(args) -> int:
    # heavy imports live here so the light 'comments' / 'report' jobs install and start fast
    from . import pipeline, scriptgen
    from .publish_meta import publish_facebook, publish_instagram
    from .publish_youtube import upload as yt_upload
    from .qc import QCError
    cfg = load_config()
    ch = cfg["channels"][args.channel]
    state = State(args.channel)
    date = args.date or _now(cfg).date().isoformat()
    if not args.force and state.slot_done(date, args.slot):
        log.info("%s slot %s on %s already produced - skipping (duplicate protection)", args.channel, args.slot, date)
        return 0
    review_n = ch.get("review_first_n", cfg["review"]["first_n_videos"])
    review = state.count_published() < review_n
    llm = LLM(cfg)
    result, last_err = None, None
    for attempt in (1, 2):
        try:
            result = pipeline.produce(cfg, llm, state, args.channel, f"{date}_s{args.slot}")
            break
        except (scriptgen.ScriptRejected, QCError) as e:
            last_err = e
            log.warning("Attempt %d failed quality gate: %s", attempt, e)
            state.log_failure("quality", str(e))
            state.save()
        except Exception:
            notify.alert_error(args.channel, "production", traceback.format_exc())
            state.log_failure("production", traceback.format_exc()[-300:])
            state.save()
            return 1
    if result is None:
        notify.alert_error(args.channel, "quality-gate", f"Two attempts were rejected.\n{last_err}")
        return 1

    topic, meta, video, script = result["topic"], result["meta"], result["video"], result["script"]
    rec = {"date": date, "slot": args.slot, "title": meta["title"], "topic": topic["title"], "kind": topic["kind"],
           "summary": script.get("description", ""), "ids": {}, "review": review,
           "quality": script.get("_quality", {}).get("avg")}
    state.mark_topic(topic["title"])
    state.data["published"].append(rec)      # recorded BEFORE publishing => retries can never double-post
    state.save()
    (OUT_DIR / "last_run.json").write_text(json.dumps(
        {"channel": args.channel, "video": str(video), "review": review, "title": meta["title"]}))

    if args.dry_run:
        log.info("Dry run: video at %s, not publishing", video)
        return 0
    try:
        if ch["platform"] == "youtube":
            privacy = "private" if review else "public"
            res = yt_upload(cfg, ch["secret_prefix"], video, meta, privacy)
            rec["ids"]["youtube"], rec["privacy"], rec["url"] = res["id"], res["privacy"], res["url"]
            if res["forced_private"]:
                notify.send_email(
                    f"[MysteryStudio] {args.channel}: YouTube forced this video to PRIVATE",
                    "Your Google Cloud project is not audited yet, so YouTube locks API uploads to private.\n"
                    "Apply for the 'YouTube API Services - Audit and Quota Extension' form for this project "
                    "(see SETUP.md step 3). Until then, set videos to Public manually in YouTube Studio.\n"
                    f"Video: {res['url']}")
        else:
            if review:
                log.info("Review mode: Instagram/Facebook skipped; video kept as workflow artifact")
                rec["privacy"] = "review-skipped"
            else:
                errs = []
                for name, fn in (("instagram", publish_instagram), ("facebook", publish_facebook)):
                    try:
                        rec["ids"][name] = fn(cfg, video, meta["caption"])["id"]
                    except AuthError:
                        raise
                    except Exception as e:
                        errs.append(f"{name}: {e}")
                        state.log_failure(f"publish-{name}", str(e))
                rec["privacy"] = "public"
                if errs:
                    state.save()
                    notify.alert_error(args.channel, "meta-publish (partial)", "\n".join(errs))
                    return 1
        state.save()
        if review:
            notify.send_email(f"[MysteryStudio] Review video ready: {args.channel}",
                              f"Title: {meta['title']}\nQuality score: {rec['quality']}\n"
                              f"{rec.get('url', 'Download the video from the workflow run artifacts')}\n"
                              f"Run: {notify.run_url()}\n"
                              f"Review videos so far on this channel: {state.count_published()} / {review_n}")
        return 0
    except (AuthError, QuotaError) as e:
        state.log_failure("publish", str(e))
        state.save()
        notify.alert_error(args.channel, "publish (needs your attention)", str(e))
        return 1
    except Exception:
        state.log_failure("publish", traceback.format_exc()[-300:])
        state.save()
        notify.alert_error(args.channel, "publish", traceback.format_exc())
        return 1


def cmd_comments(args) -> int:
    cfg = load_config()
    ch = cfg["channels"][args.channel]
    state = State(args.channel)
    llm = LLM(cfg)
    try:
        stats = (comments_mod.run_youtube(cfg, llm, state, ch["secret_prefix"]) if ch["platform"] == "youtube"
                 else comments_mod.run_meta(cfg, llm, state))
    except (AuthError, QuotaError) as e:
        notify.alert_error(args.channel, "comments (needs your attention)", str(e))
        return 1
    except Exception:
        notify.alert_error(args.channel, "comments", traceback.format_exc())
        return 1
    log.info("Comments %s: %s", args.channel, stats)
    if stats["flagged"]:
        body = "\n\n".join(f"On '{f['video']}':\n{f['comment']}" for f in stats["flagged"])
        notify.send_email(f"[MysteryStudio] {len(stats['flagged'])} comment(s) need your review on {args.channel}", body)
    return 0


def cmd_check(args) -> int:
    """Verify every credential WITHOUT posting anything. Run this first after setting secrets."""
    import requests
    from .errors import AuthError
    cfg = load_config()
    ok_all = True

    def report(name, fn):
        nonlocal ok_all
        try:
            print(f"  OK    {name}: {fn()}")
        except Exception as e:
            ok_all = False
            print(f"  FAIL  {name}: {str(e)[:300]}")

    print("Checking credentials ...")
    report("Gemini", lambda: LLM(cfg).json('Return the JSON {"ok": true}', temperature=0))
    def email():
        if not notify.send_email("[MysteryStudio] test email", "Alerts are working."):
            raise RuntimeError("SMTP_USER / SMTP_APP_PASSWORD not set or Gmail rejected the login")
        return "test email sent - check your inbox"
    report("Email", email)
    for key, ch in cfg["channels"].items():
        if ch["platform"] == "youtube":
            def yt(prefix=ch["secret_prefix"]):
                from .publish_youtube import service
                c = service(prefix).channels().list(part="snippet", mine=True).execute()["items"][0]
                return f"authorised as channel '{c['snippet']['title']}'"
            report(f"{key} (YouTube)", yt)
        else:
            def meta():
                import os
                api = f"https://graph.facebook.com/{cfg['publishing']['meta_graph_version']}"
                t = os.environ["META_PAGE_TOKEN"]
                pg = requests.get(f"{api}/{os.environ['META_PAGE_ID']}", params={"fields": "name", "access_token": t}, timeout=30).json()
                ig = requests.get(f"{api}/{os.environ['META_IG_USER_ID']}", params={"fields": "username", "access_token": t}, timeout=30).json()
                if "error" in pg or "error" in ig:
                    raise AuthError(str(pg.get("error") or ig.get("error")))
                return f"Page '{pg['name']}' + Instagram @{ig['username']}"
            report(f"{key} (Instagram+Facebook)", meta)
    print("ALL GOOD" if ok_all else "Some checks failed - fix the FAIL lines above.")
    return 0 if ok_all else 1


def cmd_report(args) -> int:
    cfg = load_config()
    since = time.time() - 86400
    lines = ["MysteryStudio - last 24 hours", ""]
    for key in cfg["channels"]:
        st = State(key)
        pub = [p for p in st.data["published"] if p.get("ts", 0) >= since]
        fails = [f for f in st.data["failures"] if f["ts"] >= since]
        lines.append(f"{cfg['channels'][key]['label']}: {len(pub)} produced "
                     f"({sum(1 for p in pub if p.get('ids'))} published), {len(fails)} problem(s), "
                     f"{st.count_published()} total")
        lines += [f"   - {p['title']} [{p.get('privacy', '?')}] {p.get('url', '')}" for p in pub]
        lines += [f"   ! {f['stage']}: {f['msg'][:120]}" for f in fails]
    notify.send_email("[MysteryStudio] Daily report", "\n".join(lines))
    print("\n".join(lines))
    return 0


def main(argv=None) -> int:
    setup_logging()
    load_dotenv()
    ap = argparse.ArgumentParser(prog="mysterystudio")
    sub = ap.add_subparsers(required=True)
    r = sub.add_parser("run", help="produce + publish one video")
    r.add_argument("--channel", required=True)
    r.add_argument("--slot", type=int, default=1)
    r.add_argument("--date")
    r.add_argument("--force", action="store_true")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("comments", help="reply to new comments")
    c.add_argument("--channel", required=True)
    c.set_defaults(fn=cmd_comments)
    ck = sub.add_parser("check", help="verify all credentials without posting")
    ck.set_defaults(fn=cmd_check)
    rp = sub.add_parser("report", help="email a 24h summary")
    rp.set_defaults(fn=cmd_report)
    a = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return a.fn(a)
