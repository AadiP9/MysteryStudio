"""Offline end-to-end test: fixture script -> voice -> music -> render -> QC. No API keys needed."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mysterystudio.config import load_config, setup_logging, ROOT
from mysterystudio.state import State
from mysterystudio import pipeline

setup_logging()
cfg = load_config()
if "--fast" in sys.argv:
    cfg["tts"]["engine"] = "fake"
if "--no-ai-images" in sys.argv or True:
    cfg["images"]["providers"] = ["procedural"] if "--procedural" in sys.argv else cfg["images"]["providers"]
fx = json.loads((ROOT / "tests" / "fixture_dbcooper.json").read_text())
t = time.time()
res = pipeline.produce(cfg, None, State("smoke", ROOT / "out" / "state_smoke"), "yt1", "smoke", offline_script=fx)
print("DONE in %.0fs" % (time.time() - t), res["video"], res["qc"])
