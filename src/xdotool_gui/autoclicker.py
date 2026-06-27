from __future__ import annotations

import random
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal

from .models import AutoClickerProfile, ClickPosition, CommandOrder


class AutoClickerController(QObject):
    logMessage = Signal(str)
    stateChanged = Signal(str)
    counterChanged = Signal(int)
    finished = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._count = 0
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self, profile: AutoClickerProfile) -> bool:
        if self._active:
            return False
        self._stop.clear()
        self._pause.set()
        self._count = 0
        self._active = True
        self.stateChanged.emit("running")
        self._thread = threading.Thread(target=self._run, args=(profile,), daemon=True)
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

    def _run(self, profile: AutoClickerProfile) -> None:
        ok = True
        try:
            if profile.start_delay_ms:
                self._sleep_ms(profile.start_delay_ms)
            loops = 0
            while not self._stop.is_set():
                loops += 1
                positions = [pos for pos in profile.positions if pos.enabled]
                if not positions:
                    self.logMessage.emit("No enabled click positions.")
                    break
                ordered = self._ordered_positions(positions, profile.order)
                for pos in ordered:
                    if self._stop.is_set():
                        break
                    self._pause.wait()
                    self._click_position(pos, profile)
                    if not profile.loop_forever and profile.loops > 0 and loops >= profile.loops:
                        break
                if not profile.loop_forever and profile.loops > 0 and loops >= profile.loops:
                    break
        except Exception as exc:  # pragma: no cover - defensive
            ok = False
            self.logMessage.emit(str(exc))
        finally:
            if profile.stop_delay_ms:
                self._sleep_ms(profile.stop_delay_ms)
            self._active = False
            self.stateChanged.emit("idle")
            self.finished.emit(ok)

    def _ordered_positions(self, positions: list[ClickPosition], order: CommandOrder) -> list[ClickPosition]:
        if order == CommandOrder.RANDOM:
            shuffled = positions[:]
            random.shuffle(shuffled)
            return shuffled
        if order == CommandOrder.WEIGHTED:
            pool: list[ClickPosition] = []
            for pos in positions:
                weight = max(pos.priority, 1)
                pool.extend([pos] * weight)
            random.shuffle(pool)
            return pool
        return sorted(positions, key=lambda pos: pos.order)

    def _click_position(self, pos: ClickPosition, profile: AutoClickerProfile) -> None:
        if pos.delay_ms:
            self._sleep_ms(pos.delay_ms)
        cps = max(profile.clicks_per_second, 0.1)
        if profile.random_cps:
            cps = max(random.uniform(cps * 0.5, cps * 1.5), 0.1)
        interval = max(1, int(1000 / cps))
        for index in range(max(pos.clicks, 1)):
            if self._stop.is_set():
                break
            if profile.total_clicks > 0 and self._count >= profile.total_clicks:
                self._stop.set()
                break
            self._pause.wait()
            x = pos.x + random.randint(-pos.random_radius, pos.random_radius) if pos.random_radius else pos.x
            y = pos.y + random.randint(-pos.random_radius, pos.random_radius) if pos.random_radius else pos.y
            argv = [
                "xdotool",
                "mousemove",
                str(x),
                str(y),
                "click",
                str(pos.button),
            ]
            subprocess.run(argv, check=False)
            self._count += 1
            self.counterChanged.emit(self._count)
            self.logMessage.emit(f"{pos.name}: {x},{y} button {pos.button}")
            wait = pos.interval_ms or interval
            if pos.jitter_ms:
                wait += random.randint(-pos.jitter_ms, pos.jitter_ms)
            if index < max(pos.clicks, 1) - 1:
                self._sleep_ms(max(wait, 1))

    def _sleep_ms(self, ms: int) -> None:
        remaining = ms / 1000.0
        while remaining > 0 and not self._stop.is_set():
            self._pause.wait()
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk
