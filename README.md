# MysteryStudio

Free, fully automated mystery / true-crime Shorts studio: researches real cases (Wikipedia-grounded), writes and
fact-checks scripts with Gemini, narrates with Kokoro, renders documentary-style vertical video with OpenCV + FFmpeg,
publishes to 3 YouTube channels + Instagram + Facebook, replies to comments, and emails you on any error.

**Start with [SETUP.md](SETUP.md).**

```
mysterystudio/
  research.py     case discovery + Wikipedia source text
  scriptgen.py    writer -> deterministic fact checks (claim quotes, numbers) -> critic -> editor loop
  tts.py          Kokoro (CPU) with Edge-TTS fallback, one clip per scene
  music.py        original synthesized score, impacts, risers, voice ducking
  visuals.py      Pollinations stills + procedural fallback
  render.py       camera moves, grade, text cards, crossfades -> ffmpeg
  captions.py     word-highlight ASS captions
  qc.py           resolution, duration, black frames, silence, loudness, blank-frame checks
  publish_*.py    YouTube Data API / Instagram + Facebook Reels
  comments.py     triage + replies, flags sensitive comments for you
  cli.py          run | comments | check | report
.github/workflows/  produce-videos, reply-to-comments, daily-report, check-credentials
```
