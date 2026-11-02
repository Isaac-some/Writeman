#!/usr/bin/env python3
"""Render a matched flat/3D pair through the real CLI and compare decoded frames."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(args):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def frame(path, seconds):
    return run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", str(seconds), "-i", str(path),
                "-vf", "scale=320:180", "-frames:v", "1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="writeman-native-3d-") as name:
        temp = Path(name)
        source, events = temp / "source.mp4", temp / "events.jsonl"
        run(["ffmpeg", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
             "color=c=0x1b4055:s=640x360:r=30:d=7", "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
             "-vf", "drawgrid=width=64:height=36:color=white@0.5:thickness=1,drawbox=x=30:y=30:w=580:h=300:color=white:t=5,drawbox=x=100:y=100:w=150:h=120:color=0xf7ba54:t=fill",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
        events.write_text("\n".join(json.dumps({"type": "cursor", "t": i / 30, "x": 0.5, "y": 0.5})
                                    for i in range(211)) + "\n")
        outputs, logs = {}, {}
        for mode in ("flat", "iso"):
            region = {"startMs": 700, "endMs": 4700, "depth": 1,
                      "focus": {"cx": 0.5, "cy": 0.5}, "focusMode": "manual"}
            if mode == "iso":
                region["rotationPreset"] = "iso"
            plan = temp / f"{mode}.json"
            plan.write_text(json.dumps({"zoomRegions": [region], "criticalClicksMs": [2500]}))
            output = temp / f"{mode}.mp4"
            logs[mode] = json.loads(run(["python3", str(HERE / "assemble-demo.py"), str(source), str(events),
                                        str(output), "--narration-end", "1", "--demo-start", "1", "--demo-end", "7",
                                        "--zoom-plan", str(plan)]))
            run(["ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"])
            outputs[mode] = output
            run(["ffmpeg", "-hide_banner", "-v", "error", "-ss", "3.5", "-i", str(output),
                 "-frames:v", "1", "-update", "1", "-y", str(args.evidence / f"rotation-{mode}.png")])
        comparisons = {}
        for label, seconds in (("narration", 0.5), ("rotationActive", 3.5), ("returnToGlobal", 6.9)):
            flat, tilted = (frame(outputs[mode], seconds) for mode in ("flat", "iso"))
            assert len(flat) == len(tilted) == 320 * 180 * 3
            fraction = sum(abs(a - b) > 20 for a, b in zip(flat, tilted)) / len(flat)
            comparisons[label] = {"seconds": seconds, "channelFractionDeltaOver20": fraction}
        assert comparisons["narration"]["channelFractionDeltaOver20"] < 0.01, comparisons
        assert comparisons["rotationActive"]["channelFractionDeltaOver20"] > 0.1, comparisons
        assert comparisons["returnToGlobal"]["channelFractionDeltaOver20"] < 0.03, comparisons
        report = {"passed": True, "renderer": "/Applications/OpenScreen.app/Contents/MacOS/Openscreen",
                  "onlyPlanDifference": "rotationPreset=iso", "comparisons": comparisons,
                  "fullDecodePassed": True, "logs": logs, "syntheticMediaRemovedOnExit": True,
                  "manualImageInspectionPending": True}
        # Temporary MP4 paths in logs are intentionally historical, not retained media.
        (args.evidence / "openscreen-native-rotation.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
