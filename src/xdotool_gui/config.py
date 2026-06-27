from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hotkey_registry import hotkey_defaults

APP_NAME = "xdotool-gui"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"


def default_config() -> dict[str, Any]:
    return {
        "window": {"width": 1280, "height": 860, "x": 100, "y": 100},
        "theme": "system",
        "hotkeys": hotkey_defaults(),
        "history": [],
        "presets": [],
        "macros": [],
        "click_profiles": [],
    }


def ensure_config_dir() -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_FILE
        self.data: dict[str, Any] = default_config()

    def load(self) -> dict[str, Any]:
        ensure_config_dir()
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                loaded = {}
            self.data = self._merge(default_config(), loaded)
        else:
            self.data = default_config()
        return self.data

    def save(self, data: dict[str, Any] | None = None) -> None:
        ensure_config_dir()
        if data is not None:
            self.data = data
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = ConfigStore._merge(dict(base[key]), value)
            else:
                base[key] = value
        return base
