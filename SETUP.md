# MysteryStudio - setup guide

Everything runs on **GitHub Actions** (free cron runners). Your laptop is only used for the one-time logins below.

```
GitHub Actions (cron, 09:00 + 19:00 IST)
  4 parallel jobs: yt1 | yt2 | yt3 | meta (Instagram+Facebook)
  each job:  pick case -> Wikipedia source -> Gemini writer -> fact-check -> critic loop
             -> Kokoro voice -> synthesized score -> render (captions, camera, grade) -> QC -> publish
  every 6h:  comment bot per channel      22:00 IST: daily email report      any failure: email
```

Output per day: 2 videos on each YouTube channel + 2 Reels shared on Instagram and Facebook = **8 videos**.

---

## 0. Read this first (honest limits)

| Topic | Reality |
|---|---|
| Visual style | Dark documentary motion graphics: AI-generated atmospheric stills (Pollinations/FLUX, free) with a camera push, film grade, text cards, kinetic captions, original synthesized score. It is **not** 3D-simulation animation like the MasterMind reference. |
| First 20 videos | **Review mode.** YouTube videos upload as **Private**, Instagram/Facebook are skipped, and you get an email per video. Watch them, tune the voice/look, then the system flips to public automatically after video 20 (`review.first_n_videos` in `config.yaml`). |
| YouTube "unaudited project" lock | Google forces uploads from API projects that have not passed an audit to **Private**. You will get an email when this happens. Submit the *YouTube API Services - Audit and Quota Extension* form for each of your 3 projects (search for that name). Until approved, flip videos to Public by hand in YouTube Studio. |
| YouTube quota | An upload costs 1,600 of 10,000 daily units per project. That is why each channel uses its **own** Google Cloud project: 2 uploads/day leave ~6,800 units for comment replies (50 units each). |
| Instagram/Facebook | Untested against your accounts (I cannot log in to them from here). Use `check` (step 6) and the first review period to confirm. |
| Free Gemini tier | Rate-limited, and Google may use free-tier prompts to improve products. Nothing personal is sent: only case text from Wikipedia and public comments. |
| Pollinations (free images) | No SLA. If it is down or blocks the runner, scenes fall back to procedural noir backdrops automatically, so videos are still produced but look plainer. |
| GitHub minutes | A video takes roughly 5-9 min (voice ~1, render ~2, free image generation 1-5). 8/day is about 1,200-2,200 min/month, plus ~700 for the comment jobs, against 2,000 free minutes on a **private** repo. Two ways out: make the repo **public** (unlimited minutes; your code, state files and review-video artifacts become visible, secrets stay hidden), or stay private and set the comment cron to every 12 h and expect to run out near month-end. |
| Scheduled workflows | GitHub may delay cron by 5-30 min, and pauses schedules in repos with 60 days of zero activity (the bot's state commits count as activity). |
| Real people | The writer is told never to name or imply guilt of unconvicted people, but **you** remain responsible for what is published. The review phase exists for this. |

---

## 1. GitHub repository

1. Create a **private** repo (e.g. `mysterystudio`) and push this folder to it.
2. Settings -> Actions -> General -> Workflow permissions -> **Read and write permissions** (the bot commits `state/*.json`).

Secrets live in: Settings -> Secrets and variables -> Actions -> *New repository secret*.

## 2. Gemini API key (scripts)

1. https://aistudio.google.com/apikey -> create a key.
2. Secret: `GEMINI_API_KEY`.
3. If the model name in `config.yaml` is ever retired, change `llm.model`.

## 3. YouTube - repeat for each of the 3 channels

Do this once per channel, **signed in as the Google account that owns that channel**.

1. https://console.cloud.google.com -> new project (name it e.g. `ms-channel-1`).
2. APIs & Services -> Library -> enable **YouTube Data API v3**.
3. APIs & Services -> OAuth consent screen -> *External* -> fill the app name and your email.
   Add your own address under **Test users**.
4. **Important:** on the consent screen click **Publish app** (status "In production"). If you leave it in *Testing*, Google expires the token after 7 days and uploads stop.
5. Credentials -> Create credentials -> OAuth client ID -> **Desktop app** -> download the JSON.
6. On your laptop:
   ```bash
   pip install google-auth-oauthlib google-api-python-client
   python scripts/youtube_auth.py client_secret_xxx.json
   ```
   Browser opens -> sign in -> "Google hasn't verified this app" -> *Advanced -> Go to app (unsafe)* (it is your own app) -> allow. If the account has several channels, pick the right one. The script prints the channel name so you can confirm.
7. Save the three printed values as secrets: `YT1_CLIENT_ID`, `YT1_CLIENT_SECRET`, `YT1_REFRESH_TOKEN` (then `YT2_*`, `YT3_*` for the other channels).

Channel identities (change them in `config.yaml -> identities`):
`yt1` unsolved mysteries - `yt2` investigations and twists - `yt3` original psychological fiction.

## 4. Instagram + Facebook

1. Instagram app -> Settings -> Account type -> **Professional** (Creator or Business).
2. Link it to a **Facebook Page** (Page settings -> Linked accounts, or Instagram -> Edit profile -> Page).
3. https://developers.facebook.com -> My Apps -> Create app -> type **Business**. Keep it in *Development* mode (fine for your own accounts, no app review needed).
4. Open the Graph API Explorer, pick your app, click *Get User Access Token* and tick:
   `pages_show_list, pages_read_engagement, pages_manage_posts, pages_manage_engagement, instagram_basic, instagram_content_publish, instagram_manage_comments, business_management`
5. On your laptop:
   ```bash
   python scripts/meta_setup.py APP_ID APP_SECRET SHORT_LIVED_TOKEN "Exact Facebook Page Name"
   ```
   (App ID/secret: App settings -> Basic.) It prints three values.
6. Secrets: `META_PAGE_ID`, `META_IG_USER_ID`, `META_PAGE_TOKEN` (the page token does not expire).

## 5. Email alerts

1. Google Account -> Security -> turn on 2-Step Verification -> **App passwords** -> create one.
2. Secrets: `SMTP_USER` (your Gmail), `SMTP_APP_PASSWORD` (the 16-character app password), `ALERT_TO` (where to send alerts; can be the same address).

You receive an email for: any production/upload/auth/quota/comment error, a crashed job, a YouTube-forced-private upload, each review video, comments that need a human, and a daily report at 22:00 IST.

## 6. Verify everything before the first video

Actions tab -> **check-credentials** -> Run workflow. The log shows OK/FAIL for Gemini, email, each YouTube channel (and which channel it is authorised as), and the Instagram/Facebook account. Fix every FAIL.

Then Actions -> **produce-videos** -> Run workflow with `channels = yt1`, `dry_run = true`. It renders one real video and keeps it as a downloadable artifact (7 days). Watch it.

## 7. Go live

Nothing else to do: the cron schedule starts working. For the first 20 videos per channel you get review emails; YouTube copies are Private - open YouTube Studio to watch, and make any good ones Public manually if you like.

Instagram/Facebook are skipped during review. To test them sooner, give that channel a shorter review in `config.yaml`:
```yaml
  meta: {platform: meta, identity: social, secret_prefix: META, review_first_n: 4, label: "Instagram + Facebook"}
```

## 8. Tuning (all in `config.yaml`)

| Want | Change |
|---|---|
| Different narrator | `tts.kokoro_voice` (am_michael, am_adam, bm_george, bm_lewis, af_nicole...), `tts.speed` |
| Stricter scripts | `quality.min_avg_score`, `quality.max_revisions` |
| Longer or shorter stories | `quality.min_words`/`max_words`, `video.max_seconds` |
| Different look | `look.*` (grain, vignette, saturation, tint, zoom) and `images.style_suffix` |
| Posting times | cron lines in `.github/workflows/produce.yml` (UTC) |
| Channel themes | `identities.*.brief` |
| Fewer comment replies | `comments.max_replies_per_run`, or the cron in `comments.yml` |

## 9. Troubleshooting

| Email / symptom | Fix |
|---|---|
| `Google refresh token rejected` | Re-run `scripts/youtube_auth.py` for that channel, update the secret. Check the OAuth app is *In production*. |
| `YouTube forced this video to PRIVATE` | Submit the API audit form for that project (section 0). |
| `quota/upload limit reached` | Wait for the next day (Pacific midnight). Do not retry manually. |
| `Meta ... token/permission problem` | Re-run `scripts/meta_setup.py`; confirm the Instagram account is Professional and linked to the Page. |
| `Script ... failed quality gate` | Normal now and then: the fact-checker rejected a script rather than publish something unsupported. The next slot tries a new case. |
| Plain, repetitive visuals | Pollinations was unavailable; check the run log for "image via procedural". |
| Gemini 429 errors | Free-tier rate limit. The jobs already stagger; reduce comment frequency or add a billing-free second key. |

## 10. Test locally (optional)

```bash
pip install -r requirements.txt && sudo apt install ffmpeg      # Windows: choco install ffmpeg
python scripts/smoke_test.py            # offline: fixture script -> voice -> render -> QC
python tests/test_run_mock.py           # offline: fact-check loop, review mode, duplicate protection
cp .env.example .env  # fill in, then:  python -m mysterystudio check
python -m mysterystudio run --channel yt1 --slot 1 --dry-run
```
Note: rendering on an 8 GB laptop works but takes a few minutes and heats the CPU; that is the reason this is built for GitHub Actions.
