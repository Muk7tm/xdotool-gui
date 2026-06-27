from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

from PySide6.QtCore import QObject, Signal

try:
    from pynput import keyboard
except Exception:  # pragma: no cover - optional dependency fallback
    keyboard = None  # type: ignore[assignment]


_MODIFIER_MAP = {
    "ctrl": "<ctrl>",
    "control": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "super": "<cmd>",
    "meta": "<cmd>",
    "cmd": "<cmd>",
    "win": "<cmd>",
}


def normalize_hotkey(sequence: str) -> str:
    parts = [part.strip().lower() for part in re.split(r"[+\-]", sequence) if part.strip()]
    if not parts:
        return ""
    normalized: list[str] = []
    for part in parts:
        if part in _MODIFIER_MAP:
            normalized.append(_MODIFIER_MAP[part])
            continue
        if len(part) == 1:
            normalized.append(part)
            continue
        normalized.append(f"<{part}>")
    return "+".join(normalized)


EMERGENCY_FALLBACK = normalize_hotkey("Ctrl+Alt+Escape")


@dataclass(slots=True)
class HotkeyBinding:
    name: str
    sequence: str


class HotkeyManager(QObject):
    activated = Signal(str)
    statusChanged = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener = None
        self._bindings: list[HotkeyBinding] = []

    @property
    def available(self) -> bool:
        return keyboard is not None

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def configure(self, bindings: dict[str, str]) -> bool:
        self.stop()
        self._bindings = []
        merged = dict(bindings)
        merged.setdefault("emergency_stop", "Ctrl+Alt+Escape")
        for name, sequence in merged.items():
            normalized = normalize_hotkey(sequence)
            if normalized:
                self._bindings.append(HotkeyBinding(name=name, sequence=normalized))
        if not self._bindings:
            self.statusChanged.emit("Hotkeys disabled")
            return True
        if keyboard is None:
            self.statusChanged.emit("Global hotkeys unavailable")
            self.error.emit("Install pynput to enable global hotkeys on X11.")
            return False
        callbacks = {binding.sequence: self._make_callback(binding.name) for binding in self._bindings}
        try:
            self._listener = keyboard.GlobalHotKeys(callbacks)
            self._listener.start()
            self.statusChanged.emit("Global hotkeys active")
            return True
        except Exception as exc:  # pragma: no cover - environment-specific
            self.error.emit(str(exc))
            self.statusChanged.emit("Global hotkeys unavailable")
            return False

    def _make_callback(self, name: str) -> Callable[[], None]:
        def _callback() -> None:
            self.activated.emit(name)

        return _callback
