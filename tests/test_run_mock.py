"""Offline integration test of the `run` command with a fake Gemini, fake voice and procedural visuals.
Covers: fact-check rejection + revision, critic gate, review mode, duplicate-slot protection, state ledger."""
import copy, json, os, shutil, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = Path(tempfile.mkdtemp())
os.environ["MS_OUT_DIR"] = str(tmp / "out")
os.environ["MS_MODEL_DIR"] = os.environ.get("MS_MODEL_DIR", str(tmp / "models"))

from mysterystudio import config as C
C.STATE_DIR = tmp / "state"
import mysterystudio.state as S; S.STATE_DIR = C.STATE_DIR
import mysterystudio.cli as cli, mysterystudio.research as research, mysterystudio.llm as llm_mod
import mysterystudio.pipeline as pipeline

SOURCE = ("On November 24, 1971, a man identifying himself as Dan Cooper hijacked Northwest Orient Airlines Flight 305. "
          "He demanded $200,000 in ransom and four parachutes. After the passengers were released in Seattle, he jumped "
          "from the aft stairs over southwest Washington. In 1980, a boy found $5,800 of the ransom along the Columbia River. "
          "The FBI suspended active investigation in July 2016, after 45 years. ") * 3
fx = json.loads((ROOT / "tests" / "fixture_dbcooper.json").read_text())
good = copy.deepcopy(fx["script"])
good["claims"] = [{"claim": c, "source_quote": q} for c, q in [
    ("Hijack in 1971", "On November 24, 1971, a man identifying himself as Dan Cooper hijacked Northwest Orient Airlines Flight 305"),
    ("Demands", "He demanded $200,000 in ransom and four parachutes"),
    ("1980 find", "In 1980, a boy found $5,800 of the ransom along the Columbia River"),
    ("FBI", "The FBI suspended active investigation in July 2016, after 45 years")]]
bad = copy.deepcopy(good)
bad["claims"][1]["source_quote"] = "He demanded a private jet and ten million dollars"   # hallucinated claim
bad["scenes"][3]["narration"] += " He was caught in 1999."                                  # number not in source


class FakeLLM:
    calls = []
    def __init__(self, cfg): pass
    def json(self, prompt, system=None, temperature=0.7, tries=3):
        FakeLLM.calls.append("critic" if system and "ruthless" in system else "writer")
        if system and "ruthless" in system:
            return {"hook_strength": 9, "retention": 8, "clarity": 9, "suspense": 8, "accuracy": 9, "originality": 8,
                    "problems": [], "fixes": []}
        return bad if FakeLLM.calls.count("writer") == 1 else good


cli.LLM = FakeLLM
research.pick_real_topic = lambda llm, state, identity: {
    "kind": "real", "title": "D. B. Cooper", "angle": "x", "status": "unsolved",
    "url": "https://en.wikipedia.org/wiki/D._B._Cooper", "source_text": SOURCE}

cfg0 = C.load_config()
def fake_cfg(): 
    c = C.load_config(); c["tts"]["engine"] = "fake"; c["images"]["providers"] = ["procedural"]; return c
cli.load_config = fake_cfg
pipeline.visuals.time.sleep = lambda s: None

rc = cli.main(["run", "--channel", "yt1", "--slot", "1", "--date", "2026-11-06", "--dry-run"])
assert rc == 0, rc
assert FakeLLM.calls[:2] == ["writer", "writer"], FakeLLM.calls       # bad draft rejected BEFORE costing a critic call
assert "critic" in FakeLLM.calls
st = S.State("yt1")
assert len(st.data["published"]) == 1 and st.data["published"][0]["slot"] == 1
assert st.topic_used("D. B. Cooper")
vid = next((tmp / "out").glob("*/video.mp4"))
print("video:", vid, round(vid.stat().st_size / 1e6, 1), "MB")

n_before = len(FakeLLM.calls)
rc = cli.main(["run", "--channel", "yt1", "--slot", "1", "--date", "2026-11-06", "--dry-run"])
assert rc == 0 and len(FakeLLM.calls) == n_before, "duplicate slot must be skipped without any work"
meta = json.loads((vid.parent / "metadata.json").read_text())
assert "wikipedia.org" in meta["description"] and "AI-generated" in meta["description"]
print("ALL TESTS PASSED; metadata title:", meta["title"])
shutil.rmtree(tmp, ignore_errors=True)
