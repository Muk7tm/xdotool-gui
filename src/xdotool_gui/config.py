from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hotkey_registry import hotkey_defaults

APP_NAME = "xdotool-gui"
CONFIG_DIR = Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
CONFIG_VERSION = 2
LEGACY_HOTKEY_DEFAULTS = {
    "execute_current": "Ctrl+Alt+Enter",
    "save_preset": "Ctrl+Alt+P",
    "show_settings": "Ctrl+Alt+,",
    "show_hotkeys": "Ctrl+Alt+H",
    "copy_preview": "Ctrl+Alt+C",
    "quit_app": "Ctrl+Alt+Q",
    "stop_active": "Ctrl+Alt+X",
    "pause_active": "Ctrl+Alt+Shift+P",
    "resume_active": "Ctrl+Alt+Shift+R",
    "capture_position": "Ctrl+Alt+Shift+C",
    "toggle_clicking": "Ctrl+Alt+T",
    "emergency_stop": "Ctrl+Alt+Escape",
}


def default_config() -> dict[str, Any]:
    return {
        "version": CONFIG_VERSION,
        "window": {"width": 1280, "height": 860, "x": 100, "y": 100},
        "theme": "system",
        "hotkeys": hotkey_defaults(),
        "history": [],
        "presets": [],
        "macros": [],
        "last_macro": {},
        "click_profiles": [],
        "window_target": {"window_id": "", "title": "", "wm_class": "", "regex": False},
        "automation": {
            "macro_name": "Untitled macro",
            "loop_forever": False,
            "repeat": 1,
            "confirm_infinite_loops": True,
            "max_runtime_minutes": 0,
            "max_failures": 0,
            "continue_on_timeout": False,
            "stop_on_window_loss": True,
            "retry_count": 3,
            "retry_delay_ms": 150,
            "delay_mode": "fixed",
            "fixed_delay_ms": 0,
            "random_delay_min_ms": 0,
            "random_delay_max_ms": 0,
            "gaussian_mean_ms": 0,
            "gaussian_stdev_ms": 0,
        },
        "logging": {
            "auto_scroll": True,
        },
        "delays": {
            "mouse_move_ms": 0,
            "click_ms": 0,
        },
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
        self.data.setdefault("version", CONFIG_VERSION)
        hotkeys = dict(self.data.get("hotkeys", {}))
        merged_hotkeys = hotkey_defaults()
        for name, current in hotkeys.items():
            if current and current != LEGACY_HOTKEY_DEFAULTS.get(name, "") and name in merged_hotkeys:
                merged_hotkeys[name] = current
        self.data["hotkeys"] = merged_hotkeys
        return self.data

    def save(self, data: dict[str, Any] | None = None) -> None:
        ensure_config_dir()
        if data is not None:
            self.data = data
        self.data["version"] = CONFIG_VERSION
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = ConfigStore._merge(dict(base[key]), value)
            else:
                base[key] = value
        return base
