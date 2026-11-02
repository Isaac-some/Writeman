#!/usr/bin/env python3
"""Convert Blurt normalized pointer events to OpenScreen cursor telemetry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def convert(source: Path, destination: Path, offset: float = 0.0, duration: float | None = None) -> int:
    samples = []
    with source.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") not in {"cursor", "click"}:
                continue
            x, y = event.get("x"), event.get("y")
            t = event.get("t")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not isinstance(t, (int, float)):
                continue
            local_t = t - offset
            if local_t < 0 or (duration is not None and local_t > duration):
                continue
            samples.append({
                "timeMs": round(local_t * 1000),
                "cx": min(1.0, max(0.0, x)),
                "cy": min(1.0, max(0.0, y)),
                "visible": True,
                "interactionType": "click" if event["type"] == "click" else "move",
            })

    samples.sort(key=lambda sample: sample["timeMs"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({
        "version": 2,
        "provider": "none",
        "assets": [],
        "samples": samples,
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return len(samples)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offset", type=float, default=0.0, help="seconds to subtract from source event time")
    parser.add_argument("--duration", type=float, help="ignore events after this segment duration")
    args = parser.parse_args()
    print(json.dumps({"samples": convert(args.events, args.output, args.offset, args.duration)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
