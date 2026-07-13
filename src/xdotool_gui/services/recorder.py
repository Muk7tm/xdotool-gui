from __future__ import annotations

import queue
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Signal

from xdotool_gui.models import RecorderEvent

try:  # pragma: no cover - optional dependency
    from pynput import keyboard as pynput_keyboard
    from pynput import mouse as pynput_mouse
except Exception:  # pragma: no cover - optional dependency fallback
    pynput_keyboard = None  # type: ignore[assignment]
    pynput_mouse = None  # type: ignore[assignment]


class RecorderService(QObject):
    stepRecorded = Signal(object)
    eventsRecorded = Signal(object)
    stateChanged = Signal(str)
    error = Signal(str)
    statusChanged = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[RecorderEvent] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._active = False
        self._last_move_time = 0.0
        self._last_position: tuple[int, int] | None = None
        self._started_at = 0.0
        self._last_event_time = 0.0
        self._mouse_listener: Any = None
        self._keyboard_listener: Any = None
        self._last_click_time = 0.0
        self._last_click_button: int | None = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> bool:
        if self._active:
            return False
        if pynput_mouse is None or pynput_keyboard is None:
            self.error.emit("Recorder requires pynput to be installed.")
            return False

        self._stop_event = threading.Event()
        self._active = True
        self._started_at = time.monotonic()
        self._last_move_time = self._started_at
        self._last_position = None
        self._last_event_time = self._started_at
        self._last_click_time = 0.0
        self._last_click_button = None
        self._clear_queue()

        self._thread = threading.Thread(target=self._run, name="recorder-worker", daemon=True)
        self._thread.start()
        self.stateChanged.emit("recording")
        self.statusChanged.emit("Recording...")
        return True

    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop_event.set()
        self._stop_listeners()
        self.stateChanged.emit("idle")
        self.statusChanged.emit("Stopped")

    def drain_events(self) -> list[RecorderEvent]:
        events: list[RecorderEvent] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def _clear_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _buffer_event(self, event: RecorderEvent) -> None:
        self._queue.put(event)

    def _run(self) -> None:
        try:
            self._mouse_listener = pynput_mouse.Listener(on_move=self._on_mouse_move, on_click=self._on_mouse_click, on_scroll=self._on_scroll)
            self._keyboard_listener = pynput_keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
            self._mouse_listener.start()
            self._keyboard_listener.start()
            while not self._stop_event.is_set():
                time.sleep(0.05)
        except Exception as exc:  # pragma: no cover - environment-specific
            self.error.emit(f"Recorder failure: {exc}")
        finally:
            self._stop_listeners()
            self._active = False
            self.stateChanged.emit("idle")
            self.statusChanged.emit("Recorder stopped")

    def _stop_listeners(self) -> None:
        for listener in (self._mouse_listener, self._keyboard_listener):
            if listener is None:
                continue
            try:
                listener.stop()
            except Exception:
                pass
        self._mouse_listener = None
        self._keyboard_listener = None

    def _buffer_timed_event(self, event: RecorderEvent) -> None:
        now = time.monotonic()
        if self._last_event_time and (now - self._last_event_time) >= 0.05:
            self._buffer_event(RecorderEvent(timestamp=now - self._started_at, type="Wait"))
        self._last_event_time = now
        self._buffer_event(event)

    def _on_mouse_move(self, x: int, y: int) -> None:
        if not self._active:
            return
        now = time.monotonic()
        should_record = self._should_record_move(x, y, self._last_position[0] if self._last_position is not None else None, self._last_position[1] if self._last_position is not None else None, now, self._last_move_time)
        if should_record:
            self._last_position = (x, y)
            self._last_move_time = now
            self._buffer_timed_event(RecorderEvent(timestamp=now - self._started_at, type="MouseMove", x=x, y=y))

    def _on_mouse_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        if not self._active:
            return
        button_name = getattr(button, "name", str(button)).lower()
        button_map = {"left": 1, "right": 3, "middle": 2}
        button_code = button_map.get(button_name, 1)
        now = time.monotonic()
        if pressed:
            double_click = bool(self._last_click_button == button_code and (now - self._last_click_time) <= 0.25)
            self._last_click_time = now
            self._last_click_button = button_code
            self._buffer_timed_event(RecorderEvent(timestamp=now - self._started_at, type="MouseClick", x=x, y=y, button=button_code, double_click=double_click))
        else:
            self._buffer_timed_event(RecorderEvent(timestamp=now - self._started_at, type="MouseUp", x=x, y=y, button=button_code))

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if not self._active:
            return
        self._buffer_timed_event(RecorderEvent(timestamp=time.monotonic() - self._started_at, type="Scroll", x=x, y=y, delta=dy if dy != 0 else dx))

    def _on_key_press(self, key: Any) -> None:
        if not self._active:
            return
        self._buffer_timed_event(RecorderEvent(timestamp=time.monotonic() - self._started_at, type="KeyDown", key=self._normalize_key(key)))

    def _on_key_release(self, key: Any) -> None:
        if not self._active:
            return
        self._buffer_timed_event(RecorderEvent(timestamp=time.monotonic() - self._started_at, type="KeyUp", key=self._normalize_key(key)))

    def _normalize_key(self, key: Any) -> str:
        if key is None:
            return ""
        if hasattr(key, "name"):
            return str(key.name)
        return str(key)

    def _should_record_move(self, x: int, y: int, previous_x: int | None, previous_y: int | None, now: float, last_time: float) -> bool:
        if previous_x is None or previous_y is None:
            return True
        distance = abs(x - previous_x) + abs(y - previous_y)
        return distance >= 5 or (now - last_time) >= 0.02


class MouseMacroRecorder(RecorderService):
    pass
