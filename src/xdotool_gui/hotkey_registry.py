from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HotkeyActionSpec:
    name: str
    label: str
    category: str
    description: str
    default: str = ""


HOTKEY_ACTIONS: list[HotkeyActionSpec] = [
    HotkeyActionSpec("execute_current", "Execute Current", "App", "Execute the active tab or raw terminal command.", "Ctrl+Alt+F9"),
    HotkeyActionSpec("save_preset", "Save Preset", "App", "Save the current preview as a preset.", "Ctrl+Alt+F7"),
    HotkeyActionSpec("save_history", "Save History", "App", "Persist history and presets to disk.", ""),
    HotkeyActionSpec("show_settings", "Show Settings", "App", "Open the settings dialog.", "Ctrl+Alt+F6"),
    HotkeyActionSpec("show_hotkeys", "Show Hotkeys", "App", "Open the hotkeys page.", "Ctrl+Alt+F5"),
    HotkeyActionSpec("show_about", "Show About", "App", "Open the about dialog.", ""),
    HotkeyActionSpec("refresh_preview", "Refresh Preview", "App", "Refresh the generated command preview.", ""),
    HotkeyActionSpec("copy_preview", "Copy Preview", "App", "Copy the generated command preview.", "Ctrl+Alt+F4"),
    HotkeyActionSpec("quit_app", "Quit App", "App", "Close the application.", "Ctrl+Alt+Q"),
    HotkeyActionSpec("stop_active", "Stop Active", "Runtime", "Stop automation and the auto clicker.", "Ctrl+Alt+Shift+F9"),
    HotkeyActionSpec("pause_active", "Pause Active", "Runtime", "Pause automation and the auto clicker.", "Ctrl+Alt+Shift+F10"),
    HotkeyActionSpec("resume_active", "Resume Active", "Runtime", "Resume automation and the auto clicker.", "Ctrl+Alt+Shift+F11"),
    HotkeyActionSpec("capture_position", "Record Position", "Runtime", "Capture the current cursor position into the active position fields.", "F8"),
    HotkeyActionSpec("toggle_clicking", "Toggle Clicking", "Runtime", "Start or stop the auto clicker.", "Ctrl+Alt+F12"),
    HotkeyActionSpec("emergency_stop", "Emergency Stop", "Runtime", "Immediate stop that cannot be disabled.", "Ctrl+Alt+Escape"),
    HotkeyActionSpec("tab_keyboard", "Go Keyboard", "Tabs", "Switch to the Keyboard tab.", ""),
    HotkeyActionSpec("tab_mouse", "Go Mouse", "Tabs", "Switch to the Mouse tab.", ""),
    HotkeyActionSpec("tab_windows", "Go Windows", "Tabs", "Switch to the Windows tab.", ""),
    HotkeyActionSpec("tab_desktop", "Go Desktop", "Tabs", "Switch to the Desktop tab.", ""),
    HotkeyActionSpec("tab_typing", "Go Typing", "Tabs", "Switch to the Typing tab.", ""),
    HotkeyActionSpec("tab_automation", "Go Automation", "Tabs", "Switch to the Automation tab.", ""),
    HotkeyActionSpec("tab_autoclicker", "Go Auto Clicker", "Tabs", "Switch to the Auto Clicker tab.", ""),
    HotkeyActionSpec("tab_terminal", "Go Terminal", "Tabs", "Switch to the Terminal tab.", ""),
    HotkeyActionSpec("tab_history", "Go History", "Tabs", "Switch to the History tab.", ""),
    HotkeyActionSpec("tab_presets", "Go Presets", "Tabs", "Switch to the Presets tab.", ""),
    HotkeyActionSpec("tab_hotkeys", "Go Hotkeys", "Tabs", "Switch to the Hotkeys tab.", ""),
]


def hotkey_defaults() -> dict[str, str]:
    return {spec.name: spec.default for spec in HOTKEY_ACTIONS}


HOTKEY_ALIASES: dict[str, str] = {
    "start": "execute_current",
    "stop": "stop_active",
    "pause": "pause_active",
    "resume": "resume_active",
}


def normalize_hotkey_bindings(bindings: dict[str, str]) -> dict[str, str]:
    normalized = hotkey_defaults()
    for key, value in bindings.items():
        target = HOTKEY_ALIASES.get(key, key)
        if target in normalized:
            normalized[target] = value
    return normalized
