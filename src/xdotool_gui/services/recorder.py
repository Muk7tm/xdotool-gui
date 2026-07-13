from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

try:  # pragma: no cover - optional dependency
    from pynput import mouse
except Exception:  # pragma: no cover - optional dependency fallback
    mouse = None  # type: ignore[assignment]


@dataclass(slots=True)
class RecordedStep:
    action_type: str
    command: str
    params: dict[str, Any]
    delay_ms: int = 0
    repeat: int = 1
    enabled: bool = True
    label: str = ""


class MouseMacroRecorder(QObject):
    stepRecorded = Signal(object)
    stateChanged = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener = None
        self._active = False
        self._lock = threading.Lock()
        self._last_emit = time.monotonic()
        self._last_point: tuple[int, int] | None = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return False
        if mouse is None:
            self.error.emit("Mouse recording requires pynput.")
            return False
        self._active = True
        self._last_emit = time.monotonic()
        self._last_point = None
        self._listener = mouse.Listener(on_move=self._on_move, on_click=self._on_click)
        self._listener.start()
        self.stateChanged.emit("recording")
        return True

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        self._active = False
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass
        self.stateChanged.emit("idle")

    def _emit_step(self, step: RecordedStep) -> None:
        self.stepRecorded.emit(
            {
                "action_type": step.action_type,
                "command": step.command,
                "params": step.params,
                "delay_ms": step.delay_ms,
                "repeat": step.repeat,
                "enabled": step.enabled,
                "label": step.label,
            }
        )

    def _elapsed_ms(self) -> int:
        now = time.monotonic()
        delta = max(int((now - self._last_emit) * 1000), 0)
        self._last_emit = now
        return delta

    def _on_move(self, x: int, y: int) -> None:
        with self._lock:
            if not self._active:
                return
            previous = self._last_point
            if previous is not None:
                dx = abs(x - previous[0])
                dy = abs(y - previous[1])
                if dx < 4 and dy < 4:
                    return
            self._last_point = (x, y)
            self._emit_step(
                RecordedStep(
                    action_type="mouse_move",
                    command="",
                    params={"x": x, "y": y, "movement_style": "instant"},
                    delay_ms=self._elapsed_ms(),
                    label="Recorded move",
                )
            )

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        if not pressed:
            return
        with self._lock:
            if not self._active:
                return
            button_name = getattr(button, "name", str(button)).lower()
            button_map = {"left": 1, "right": 3, "middle": 2}
            self._last_point = (x, y)
            self._emit_step(
                RecordedStep(
                    action_type="click" if button_map.get(button_name, 1) == 1 else "right_click" if button_map.get(button_name, 1) == 3 else "middle_click",
                    command="",
                    params={"x": x, "y": y, "button": button_map.get(button_name, 1), "clicks": 1},
                    delay_ms=self._elapsed_ms(),
                    label="Recorded click",
                )
            )
