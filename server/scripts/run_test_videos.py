"""Run every exported test video through the pipeline and grade the verdicts.

Reads dump/test_videos/manifest.json (produced by export_test_videos.py), feeds
each .mp4 plus its recorded corner taps through run_pipeline, and prints the
decision against the expected verdict. A one-command end-to-end demo.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.pipeline.calibration import CalibrationError
from app.pipeline.process_job import run_pipeline

VIDEO_DIR = Path("/Users/nirajkafle/Desktop/niraj/dev-projects/pocket-drs/dump/test_videos")


def main() -> int:
    manifest = json.loads((VIDEO_DIR / "manifest.json").read_text())
    videos = manifest["videos"]

    passed = 0
    print(f"{'file':28} {'expected':13} {'got':13} match")
    print("-" * 70)
    for v in videos:
        # Use the exact request recorded at export time so verdicts reproduce.
        req = v["request"]
        art = Path(tempfile.mkdtemp(prefix="runtv_"))
        try:
            out = run_pipeline(video_path=VIDEO_DIR / v["file"], request_json=req, artifacts_dir=art, progress=None)
            got = (out.result.get("lbw") or {}).get("decision")
        except CalibrationError as exc:
            got = f"calib_rejected ({exc})"

        match = "OK" if got == v["expected_decision"] else "MISS"
        passed += match == "OK"
        print(f"{v['file']:28} {v['expected_decision']:13} {str(got):13} {match}")

    print("-" * 70)
    print(f"Passed {passed}/{len(videos)}")
    return 0 if passed == len(videos) else 1


if __name__ == "__main__":
    raise SystemExit(main())
