#!/usr/bin/env python3
"""Keep narrated intro, OpenScreen-zoom the silent demo, then join both parts."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONVERTER = HERE / "blurt-to-openscreen-cursor.py"
OPENSCREEN = Path(os.environ.get(
    "OPENSCREEN_CLI", "/Applications/OpenScreen.app/Contents/MacOS/Openscreen"
))


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.stdout


def parse_speed_range(value: str, duration: float) -> tuple[float, float, float]:
    try:
        start, end, factor = map(float, value.split(":"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use START:END:FACTOR in demo-local seconds") from exc
    if start < 0 or end <= start or end > duration or factor < 1 or factor > 2:
        raise argparse.ArgumentTypeError("ranges must fit the demo; speed factor must be 1..2")
    return start, end, factor


def speed_filters(duration, speed_ranges, input_label="1:v"):
    """Build one continuous pass through the demo, retaining every interval once."""
    segments = []
    cursor = 0.0
    for start, end, factor in speed_ranges:
        if start > cursor:
            segments.append((cursor, start, 1.0))
        segments.append((start, end, factor))
        cursor = end
    if cursor < duration:
        segments.append((cursor, duration, 1.0))
    filters, labels = [], []
    for index, (start, end, factor) in enumerate(segments):
        label = f"demo_piece_{index}"
        filters.append(f"[{input_label}]trim=start={start}:end={end},setpts=(PTS-STARTPTS)/{factor}[{label}]")
        labels.append(f"[{label}]")
    filters.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[sped]")
    return filters, sum((end - start) / factor for start, end, factor in segments)


def load_zoom_plan(path: Path, duration: float) -> list[dict]:
    """Validate explicit demo-local zooms, including native 3D rotation presets."""
    plan = json.loads(path.read_text(encoding="utf-8"))
    regions = plan.get("zoomRegions") if isinstance(plan, dict) else None
    if not isinstance(regions, list) or not regions:
        raise ValueError("zoom plan must contain a nonempty zoomRegions list")
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    result = []
    for index, region in enumerate(regions):
        if not isinstance(region, dict):
            raise ValueError("each zoom region must be an object")
        start, end = region.get("startMs"), region.get("endMs")
        focus = region.get("focus", {})
        depth = region.get("depth", 2)
        if not number(start) or not number(end) or not 0 <= start < end <= duration * 1000:
            raise ValueError("zoom times must fit the silent demo in milliseconds")
        if not isinstance(focus, dict) or any(not number(focus.get(k)) or not 0 <= focus[k] <= 1 for k in ("cx", "cy")):
            raise ValueError("zoom focus must contain normalized cx/cy")
        if type(depth) is not int or depth not in range(1, 7):
            raise ValueError("zoom depth must be an integer from 1 to 6")
        preset = region.get("rotationPreset")
        mode = region.get("focusMode", "auto")
        if preset not in (None, "iso", "left", "right") or mode not in ("manual", "auto"):
            raise ValueError("unsupported rotationPreset or focusMode")
        normalized = {"id": f"writeman-{index + 1}", "startMs": start, "endMs": end,
                      "depth": depth, "focus": focus, "focusMode": mode, "source": "manual"}
        if preset is not None:
            normalized["rotationPreset"] = preset
        result.append(normalized)
    result.sort(key=lambda item: item["startMs"])
    if any(a["endMs"] > b["startMs"] for a, b in zip(result, result[1:])):
        raise ValueError("zoom regions must not overlap; leave gaps for the full view")
    clicks = plan.get("criticalClicksMs", [])
    if not isinstance(clicks, list) or any(not number(t) or not 0 <= t <= duration * 1000 for t in clicks):
        raise ValueError("criticalClicksMs must be demo-local millisecond timestamps")
    if any(not any(r["startMs"] <= t < r["endMs"] for r in result) for t in clicks):
        raise ValueError("a declared critical click has no zoom coverage")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--narration-end", required=True, type=float, help="end of spoken explanation, source seconds")
    parser.add_argument("--demo-start", required=True, type=float, help="start of silent demo, source seconds")
    parser.add_argument("--demo-end", required=True, type=float, help="end of silent demo, source seconds")
    parser.add_argument("--speed-range", action="append", default=[], metavar="START:END:FACTOR",
                        help="gently speed up an analyzed idle interval; times are local to the demo")
    parser.add_argument("--openscreen", type=Path, default=OPENSCREEN)
    parser.add_argument("--zoom-plan", type=Path, help="reviewed demo-local zoomRegions JSON; supports iso/left/right 3D presets")
    args = parser.parse_args()

    if not args.video.is_file() or not args.events.is_file() or not args.openscreen.is_file():
        parser.error("video, Blurt events.jsonl, and OpenScreen CLI must exist")
    if args.output.exists() or args.output.resolve() == args.video.resolve():
        parser.error("output already exists; choose a new output path")
    if args.narration_end <= 0 or args.demo_start < args.narration_end or args.demo_end <= args.demo_start:
        parser.error("expected narration-end > 0 and demo-end > demo-start >= narration-end")

    duration_text = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(args.video)]).strip()
    source_duration = float(duration_text)
    if args.demo_end > source_duration or args.narration_end > source_duration:
        parser.error(f"segment boundary exceeds source duration ({source_duration:.3f}s)")
    demo_duration = args.demo_end - args.demo_start
    try:
        zoom_regions = load_zoom_plan(args.zoom_plan, demo_duration) if args.zoom_plan else None
    except (OSError, ValueError, TypeError) as exc:
        parser.error(f"invalid zoom plan: {exc}")
    speed_ranges = sorted(parse_speed_range(item, demo_duration) for item in args.speed_range)
    if any(a[1] > b[0] for a, b in zip(speed_ranges, speed_ranges[1:])):
        parser.error("speed ranges must not overlap")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="writeman-video-", dir="/tmp") as temp_name:
        temp = Path(temp_name)
        narration = temp / "narration.mp4"
        demo = temp / "demo.mp4"
        zoomed = temp / "demo-zoomed.mp4"
        project = temp / "demo.openscreen"

        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-i", str(args.video),
             "-t", str(args.narration_end), "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
             "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(narration)])
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(args.demo_start), "-i", str(args.video),
             "-t", str(demo_duration), "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-movflags", "+faststart", str(demo)])

        sidecar = Path(f"{demo}.cursor.json")
        converter_result = run(["python3", str(CONVERTER), str(args.events), str(sidecar),
                                "--offset", str(args.demo_start), "--duration", str(demo_duration)])
        samples = int(json.loads(converter_result)["samples"])
        if samples < 2:
            parser.error("silent-demo segment has fewer than two captured pointer events; refusing to claim mouse tracking")
        editor = {"zoomRegions": zoom_regions} if zoom_regions else {}
        project.write_text(json.dumps({"version": 2, "media": {"screenVideoPath": str(demo)}, "editor": editor}), encoding="utf-8")
        zoom_flags = [] if zoom_regions else ["--auto-zoom"]
        export_log = run([str(args.openscreen), "export", str(project), *zoom_flags, "--quality", "medium", "-o", str(zoomed), "--json"])
        done_events = [json.loads(line) for line in export_log.splitlines() if line.startswith("{")]
        done = next((event for event in reversed(done_events) if event.get("event") == "done"), {})
        if not done.get("success") or not zoomed.is_file():
            parser.error(f"OpenScreen export failed: {done.get('error', export_log[-1000:])}")
        match = re.search(r"Auto-zoom: added (\d+) region", export_log)
        if not zoom_regions and (not match or int(match.group(1)) == 0):
            parser.error("OpenScreen did not create an automatic zoom; source files were left untouched")

        dimensions = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=s=x:p=0", str(zoomed)]).strip()
        width, height = map(int, dimensions.split("x"))
        filters, effective_demo_duration = speed_filters(demo_duration, speed_ranges)
        filters.append(f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v0]")
        filters.append(f"[sped]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v1]")
        filters.append("[v0][v1]concat=n=2:v=1:a=0[v]")
        filters.append(f"[0:a]apad=pad_dur={effective_demo_duration}[a]")
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(narration), "-i", str(zoomed),
             "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", "-t",
             str(args.narration_end + effective_demo_duration), "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(args.output)])

    print(json.dumps({"output": str(args.output), "cursorSamples": samples,
                      "autoZoomRegions": int(match.group(1)) if match else 0,
                      "plannedZoomRegions": len(zoom_regions or []),
                      "rotationRegions": sum(bool(r.get("rotationPreset")) for r in (zoom_regions or [])),
                      "speedRanges": len(speed_ranges)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
