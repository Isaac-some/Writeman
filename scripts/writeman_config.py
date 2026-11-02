"""Load Writeman's private local configuration without embedding resource IDs."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "writeman.local.json"


def load_config(path: Path | None = None) -> dict:
    config_path = Path(path or os.environ.get("WRITEMAN_CONFIG", DEFAULT_CONFIG)).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(
            "Missing local configuration. "
            "Copy config/writeman.example.json to config/writeman.local.json and add your own resource IDs."
        )
    value = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Writeman configuration must be a JSON object")
    return value
