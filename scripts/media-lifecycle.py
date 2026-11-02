#!/usr/bin/env python3
"""Record a verified Feishu delivery; clean its local files on a later Monday."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "state/media-receipts.json"
RECORDINGS = Path(os.environ.get("WRITEMAN_RECORDINGS_DIR", str(Path.home() / "Blurt/recordings"))).expanduser()
RUNS = ROOT / "runs"
TZ = ZoneInfo(os.environ.get("WRITEMAN_TIMEZONE", "Asia/Shanghai"))
REFERENCE_DOC = os.environ.get("WRITEMAN_REFERENCE_DOCUMENT", "")


def local_now():
    return datetime.now(TZ)


def digest(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"not a regular file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def bounded(path, parent):
    path, parent = Path(os.path.abspath(path)), parent.resolve()
    # macOS exposes the same temporary roots through /var and /private/var.
    # Normalize aliases above the permitted root, but reject links inside it.
    anchor = next((entry for entry in path.parents if entry.resolve() == parent), None)
    if anchor is None or path.resolve() == parent:
        raise ValueError(f"path outside permitted child directory: {path}")
    for entry in (path, *path.parents):
        if entry == anchor:
            break
        if entry.is_symlink():
            raise ValueError(f"symlink is not eligible: {entry}")
    return parent / path.relative_to(anchor)


def recording_path(path):
    path = bounded(path, RECORDINGS)
    if path.parent != RECORDINGS.resolve() or not re.fullmatch(r"\d{8}-\d{6}", path.name):
        raise ValueError("recording must be one timestamp directory under ~/Blurt/recordings")
    return path


def inventory(directory):
    files, directories = {}, []
    if not directory.is_dir():
        raise ValueError(f"directory missing: {directory}")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink is not eligible: {path}")
        name = str(path.relative_to(directory))
        if path.is_dir():
            directories.append(name)
        else:
            files[name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    return {"files": files, "directories": directories}


def ensure_not_sent(recording):
    spec = importlib.util.spec_from_file_location("writeman_attachments", ROOT / "scripts/classify-codex-video-attachments.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.matching_sessions((recording / "recording.mp4").resolve(), module.DEFAULT_ROOTS):
        raise ValueError("recording was sent to Codex; preserve it outside the weekly-demo cleanup")


def cli(arguments, cwd=None):
    result = subprocess.run(["lark-cli", *arguments], cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    try:
        response = json.loads(result.stdout if result.returncode == 0 else result.stderr)
    except ValueError as exc:
        raise ValueError("Feishu returned no usable JSON; local files retained") from exc
    if result.returncode != 0 or response.get("ok") is not True or response.get("identity") != "user":
        raise ValueError("Feishu user read failed: " + response.get("error", {}).get("message", "unexpected response"))
    return response.get("data", {})


def verify_remote(receipt):
    document = cli(["docs", "+fetch", "--doc", receipt["documentId"], "--scope", "range",
                    "--start-block-id", receipt["blockId"], "--end-block-id", receipt["blockId"],
                    "--detail", "full", "--as", "user", "--json"]).get("document", {})
    if document.get("document_id") != receipt["documentId"]:
        raise ValueError("unexpected document in delivery verification")
    xml = ET.fromstring("<root>" + document.get("content", "") + "</root>")
    blocks = [node for node in xml.iter() if node.get("id") == receipt["blockId"]]
    if not any(node.tag == "source" and node.get("token") == receipt["fileToken"]
               for block in blocks for node in block.iter()):
        raise ValueError("the expected video is not attached at the recorded block; local files retained")
    with tempfile.TemporaryDirectory(prefix="writeman-verify-") as temp:
        cli(["docs", "+media-download", "--token", receipt["fileToken"],
             "--output", "remote.mp4", "--as", "user", "--json"], cwd=temp)
        if digest(Path(temp) / "remote.mp4") != receipt["outputSha256"]:
            raise ValueError("remote video differs from the delivered local output; local files retained")
    return {"checkedAt": local_now().isoformat(), "revisionId": document.get("revision_id"),
            "attachmentMatched": True, "downloadSha256Matched": True}


def save(data):
    fd, temporary = tempfile.mkstemp(prefix=".media-receipts-", dir=LEDGER.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, LEDGER)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register(data, args):
    recording = recording_path(args.recording)
    artifacts = bounded(args.artifacts, RUNS)
    output = bounded(args.output, artifacts)
    if not (recording / "recording.mp4").is_file() or output.suffix.lower() != ".mp4":
        raise ValueError("source recording.mp4 and final MP4 are required")
    if args.document_id == REFERENCE_DOC:
        raise ValueError("delivery must be a new document, never the weekly reference document")
    for token in (args.document_id, args.block_id, args.file_token):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("expected a bare document/block/media token")
    ensure_not_sent(recording)
    for other in data["receipts"]:
        if other["status"] == "cleaned":
            continue
        other_artifacts = Path(other["artifacts"])
        if (str(recording) == other["recording"] or artifacts.is_relative_to(other_artifacts)
                or other_artifacts.is_relative_to(artifacts)):
            raise ValueError("source or artifact directory already belongs to a delivery receipt")
    now = local_now()
    monday = (now + timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    receipt = {"id": hashlib.sha256((str(recording) + args.file_token).encode()).hexdigest()[:24],
               "status": "delivered", "deliveredAt": now.isoformat(), "cleanupNotBefore": monday.isoformat(),
               "recording": str(recording), "artifacts": str(artifacts), "output": str(output),
               "outputSha256": digest(output), "documentId": args.document_id,
               "blockId": args.block_id, "fileToken": args.file_token,
               "sourceInventory": inventory(recording), "artifactInventory": inventory(artifacts)}
    receipt["remoteVerification"] = verify_remote(receipt)
    data["receipts"].append(receipt)
    save(data)
    return {"receiptId": receipt["id"], "status": "delivered", "cleanupNotBefore": monday.isoformat()}


def validate_snapshot(directory, expected, resuming):
    if not directory.exists() and resuming:
        return
    current = inventory(directory)
    if any(expected["files"].get(key) != value for key, value in current["files"].items()):
        raise ValueError(f"new or changed file under {directory}; preserve this delivery")
    if not set(current["directories"]).issubset(expected["directories"]):
        raise ValueError(f"new directories under {directory}; preserve this delivery")
    if not resuming and current != expected:
        raise ValueError(f"directory changed since delivery: {directory}")


def remove_snapshot(directory, snapshot):
    if not directory.exists():
        return
    for relative, expected in snapshot["files"].items():
        path = bounded(directory / relative, directory)
        if not path.exists() and not path.is_symlink():
            continue
        if digest(path) != expected["sha256"]:
            raise ValueError(f"file changed during cleanup: {path}")
        path.unlink()
    for relative in sorted(snapshot["directories"], key=lambda name: len(Path(name).parts), reverse=True):
        path = bounded(directory / relative, directory)
        if path.exists():
            path.rmdir()
    directory.rmdir()


def cleanup(data, apply):
    now = local_now()
    results = []
    for receipt in data["receipts"]:
        if receipt["status"] == "cleaned":
            continue
        item = {"receiptId": receipt["id"]}
        if now.weekday() != 0 or now < datetime.fromisoformat(receipt["cleanupNotBefore"]):
            results.append({**item, "status": "not-due", "cleanupNotBefore": receipt["cleanupNotBefore"]})
            continue
        try:
            recording = recording_path(Path(receipt["recording"]))
            artifacts = bounded(Path(receipt["artifacts"]), RUNS)
            ensure_not_sent(recording)
            resuming = receipt["status"] == "cleanup-started"
            validate_snapshot(recording, receipt["sourceInventory"], resuming)
            validate_snapshot(artifacts, receipt["artifactInventory"], resuming)
            verification = verify_remote(receipt)
            if not apply:
                results.append({**item, "status": "eligible", "remoteVerification": verification})
                continue
            receipt.update(status="cleanup-started", remoteVerification=verification)
            save(data)
            remove_snapshot(recording, receipt["sourceInventory"])
            remove_snapshot(artifacts, receipt["artifactInventory"])
            receipt.update(status="cleaned", cleanedAt=now.isoformat())
            save(data)
            results.append({**item, "status": "cleaned"})
        except (ValueError, OSError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            results.append({**item, "status": "retained", "reason": str(exc)})
    return {"mode": "apply" if apply else "dry-run", "receipts": results}


def main():
    global REFERENCE_DOC, RECORDINGS, TZ
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    registration = commands.add_parser("register", help="after upload: verify and record one delivered demo")
    for name in ("recording", "artifacts", "output"):
        registration.add_argument("--" + name, type=Path, required=True)
    for name in ("document-id", "block-id", "file-token"):
        registration.add_argument("--" + name, required=True)
    registration.add_argument("--config", type=Path, required=True, help="private Writeman JSON settings")
    cleaning = commands.add_parser("cleanup", help="Monday task startup: verify receipts, then clean if --apply")
    cleaning.add_argument("--apply", action="store_true")
    cleaning.add_argument("--config", type=Path, help="private Writeman JSON settings")
    args = parser.parse_args()
    if args.command == "register":
        from writeman_config import load_config
        try:
            settings = load_config(args.config)
        except (OSError, ValueError, TypeError) as exc:
            parser.exit(2, f"{exc}\n")
        REFERENCE_DOC = settings.get("reference_document_id", "")
        RECORDINGS = Path(settings.get("recordings_dir", RECORDINGS)).expanduser()
        TZ = ZoneInfo(settings.get("timezone", "Asia/Shanghai"))
        if not REFERENCE_DOC:
            parser.error("configure reference_document_id before registering a delivery")
    if args.command == "cleanup" and not LEDGER.exists():
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "receipts": []}))
        return 0
    if args.command == "cleanup" and args.config:
        from writeman_config import load_config
        try:
            settings = load_config(args.config)
        except (OSError, ValueError, TypeError) as exc:
            parser.exit(2, f"{exc}\n")
        RECORDINGS = Path(settings.get("recordings_dir", RECORDINGS)).expanduser()
        TZ = ZoneInfo(settings.get("timezone", "Asia/Shanghai"))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    try:
        with LEDGER.with_suffix(".lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"version": 1, "receipts": []}
            if data.get("version") != 1 or not isinstance(data.get("receipts"), list):
                raise ValueError("unsupported media receipt format")
            result = register(data, args) if args.command == "register" else cleanup(data, args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, ET.ParseError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
