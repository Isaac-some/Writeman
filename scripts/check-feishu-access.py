#!/usr/bin/env python3
"""Run read-only edit-permission checks for locally configured sources."""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from writeman_config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="private Writeman JSON settings")
    args = parser.parse_args()
    try:
        settings = load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{exc}\n")

    checks = []
    for target in settings.get("feishu_targets", []):
        name = target.get("name", "unnamed")
        kind = target.get("type")
        token = target.get("token")
        if not kind or not token:
            checks.append({"target": name, "configured": False, "granted": False})
            continue
        result = subprocess.run(
            ["lark-cli", "drive", "permission.members", "auth", "--token", token,
             "--type", kind, "--action", "edit", "--as", "user", "--json"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45,
        )
        try:
            data = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        except ValueError:
            data = {"error": {"message": "CLI response was not JSON"}}
        granted = (
            result.returncode == 0 and data.get("ok") is True
            and data.get("identity") == "user"
            and data.get("data", {}).get("auth_result") is True
        )
        checks.append({
            "target": name, "type": kind, "configured": True,
            "granted": granted, "error": data.get("error"),
        })
    print(json.dumps({"checkedAt": datetime.now().astimezone().isoformat(), "identity": "user",
                      "readOnly": True, "checks": checks,
                      "limitations": "Permission checks do not verify field rules or perform business writes."},
                     ensure_ascii=False, indent=2))
    return 0 if checks and all(item["granted"] for item in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
