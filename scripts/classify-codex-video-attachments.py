#!/usr/bin/env python3
"""Find Blurt videos explicitly attached to Codex user messages."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_ROOTS = [Path.home() / ".codex/sessions", Path.home() / ".codex/archived_sessions"]


def user_text(row: dict) -> str | None:
    payload = row.get("payload", {})
    if row.get("type") == "response_item" and payload.get("type") == "message" and payload.get("role") == "user":
        content = payload.get("content", [])
    elif row.get("type") == "event_msg":
        item = payload.get("item", {})
        if item.get("type") != "UserMessage":
            return None
        content = item.get("content", [])
    else:
        return None
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict))


def attachment_mentions(text: str, video: Path) -> bool:
    lines = text.splitlines()
    in_files = False
    for line in lines:
        if line.strip() == "# Files mentioned by the user:":
            in_files = True
            continue
        if in_files and line.startswith("## ") and str(video) in line:
            return True
        if in_files and line.startswith("## My request:"):
            break
    return False


def matching_sessions(video: Path, roots: list[Path]) -> list[str]:
    existing_roots = [str(root) for root in roots if root.is_dir()]
    if not existing_roots:
        raise RuntimeError("no Codex session-history roots are available")
    search = subprocess.run(
        ["rg", "-l", "--fixed-strings", "--glob", "*.jsonl", "--", str(video), *existing_roots],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if search.returncode not in (0, 1):
        raise RuntimeError(search.stderr.strip() or f"rg exited {search.returncode}")

    matches = []
    for filename in search.stdout.splitlines():
        path = Path(filename)
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    text = user_text(row)
                    if text and attachment_mentions(text, video):
                        matches.append(str(path))
                        break
        except OSError:
            continue
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="*", type=Path, help="Blurt recording directories; defaults to ~/Blurt/recordings/*")
    parser.add_argument("--codex-root", action="append", type=Path, default=None,
                        help="session-history root; may be repeated")
    args = parser.parse_args()
    roots = args.codex_root or DEFAULT_ROOTS
    sessions = args.recordings or sorted(path for path in (Path.home() / "Blurt/recordings").glob("*") if path.is_dir())

    result = []
    for session in sessions:
        video = (session / "recording.mp4").resolve()
        if not video.is_file():
            result.append({"session": str(session), "status": "missing-video"})
            continue
        try:
            matches = matching_sessions(video, roots)
        except RuntimeError as exc:
            result.append({"session": str(session), "status": "unknown", "reason": str(exc)})
            continue
        result.append({
            "session": str(session),
            "status": "sent-to-codex" if matches else "no-codex-attachment-found",
            "codexSessions": matches,
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
