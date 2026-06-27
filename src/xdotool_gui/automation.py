from __future__ import annotations

import random
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .models import AutomationStep


@dataclass(slots=True)
class MacroRunOptions:
    repeat: int = 1
    loop_forever: bool = False
    random_delay_min_ms: int = 0
    random_delay_max_ms: int = 0
    stop_on_error: bool = False


class MacroRunner(QObject):
    logMessage = Signal(str)
    stateChanged = Signal(str)
    finished = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, steps: list[AutomationStep], options: MacroRunOptions) -> bool:
        if self._active:
            return False
        self._stop.clear()
        self._pause.set()
        self._active = True
        self.stateChanged.emit("running")
        self._thread = threading.Thread(target=self._run, args=(steps, options), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._pause.set()
        self.stateChanged.emit("stopping")

    def pause(self) -> None:
        self._pause.clear()
        self.stateChanged.emit("paused")

    def resume(self) -> None:
        self._pause.set()
        self.stateChanged.emit("running")

    def _run(self, steps: list[AutomationStep], options: MacroRunOptions) -> None:
        ok = True
        try:
            repeat = 0
            while not self._stop.is_set():
                repeat += 1
                for step_index, step in enumerate(steps, start=1):
                    if self._stop.is_set():
                        break
                    self._pause.wait()
                    if not step.enabled:
                        continue
                    for run_index in range(max(step.repeat, 1)):
                        if self._stop.is_set():
                            break
                        self._pause.wait()
                        try:
                            argv = shlex.split(step.command)
                            if argv and argv[0] != "xdotool":
                                argv.insert(0, "xdotool")
                            subprocess.run(argv, check=False)
                            self.logMessage.emit(f"Step {step_index}: {step.command}")
                        except Exception as exc:  # pragma: no cover - defensive
                            ok = False
                            self.logMessage.emit(f"Step {step_index} failed: {exc}")
                            if options.stop_on_error:
                                self._stop.set()
                                break
                        if step.delay_ms > 0:
                            self._sleep_ms(step.delay_ms)
                        if options.random_delay_max_ms > 0:
                            delay = random.randint(
                                options.random_delay_min_ms,
                                max(options.random_delay_min_ms, options.random_delay_max_ms),
                            )
                            self._sleep_ms(delay)
                if options.loop_forever:
                    continue
                if repeat >= max(options.repeat, 1):
                    break
        finally:
            self._active = False
            self.stateChanged.emit("idle")
            self.finished.emit(ok)

    def _sleep_ms(self, ms: int) -> None:
        remaining = ms / 1000.0
        while remaining > 0 and not self._stop.is_set():
            self._pause.wait()
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk
