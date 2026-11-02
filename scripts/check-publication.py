"""Reject personal data and runtime artifacts from the public Writeman source tree."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {".github", "config", "scripts"}
ALLOWED_FILES = {".gitignore", "AGENTS.md", "LICENSE", "README.md", "agent.json", "execution.md"}
FORBIDDEN_NAMES = {
    "writeman.local.json", "agent.local.json", "agent-workspace.json", "agent-deliveries.json",
    "tasks.json", "tasks.json.bak", "media-receipts.json",
}
PATTERNS = [
    re.compile(rb"/" + rb"Users/[^/\s\"']+/"),
    re.compile(rb"https?://[^\s\"<>]*(?:feishu|larksuite)\.(?:cn|com)[^\s\"<>]*", re.I),
    re.compile(rb"\b(?:ou_|cli_)[a-f0-9]{16,}\b", re.I),
    re.compile(rb"\b(?:base|table|record)_token\s*[:=]\s*[A-Za-z0-9_-]{8,}", re.I),
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
]


def publication_errors(root: Path = ROOT) -> list[str]:
    errors = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(root)
        if relative.parts[0] not in ALLOWED_ROOTS and str(relative) not in ALLOWED_FILES:
            errors.append(f"outside publication allowlist: {relative}")
            continue
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in {".log", ".jsonl", ".mp4", ".mov", ".png"}:
            errors.append(f"runtime or evidence artifact: {relative}")
            continue
        body = path.read_bytes()
        if any(pattern.search(body) for pattern in PATTERNS):
            errors.append(f"private marker: {relative}")
    return errors


def main() -> int:
    errors = publication_errors()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Writeman publication check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
