from __future__ import annotations

import random
import subprocess
import threading
import time
import math

from PySide6.QtCore import QObject, Signal

from .models import AutoClickerProfile, ClickPosition, CommandOrder, WindowTarget
from .services.runtime import RetryPolicy, XdotoolRunner
from .services.x11 import X11Inspector


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
        self._runner = XdotoolRunner()
        self._inspector: X11Inspector | None = None

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
            self._inspector = X11Inspector()
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
            if self._inspector is not None:
                self._inspector.close()
                self._inspector = None
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
            x, y = self._randomized_position(pos, profile)
            try:
                self._ensure_target_window(profile)
                self._move_pointer(x, y, pos, profile)
                self._run_xdotool(["xdotool", "click", str(pos.button)], profile)
            except Exception as exc:
                self.logMessage.emit(f"{pos.name} failed: {exc}")
                continue
            self._count += 1
            self.counterChanged.emit(self._count)
            self.logMessage.emit(f"{pos.name}: {x},{y} button {pos.button}")
            wait = pos.interval_ms or interval
            if pos.jitter_ms:
                wait += random.randint(-pos.jitter_ms, pos.jitter_ms)
            if index < max(pos.clicks, 1) - 1:
                self._sleep_ms(max(wait, 1))

    def _run_xdotool(self, argv: list[str], profile: AutoClickerProfile) -> None:
        policy = RetryPolicy(attempts=3, delay_ms=150)
        result = self._runner.run(argv, policy=policy, logger=self.logMessage.emit)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"xdotool failed: {' '.join(argv)}")

    def _ensure_target_window(self, profile: AutoClickerProfile) -> None:
        inspector = self._inspector
        if inspector is None or not profile.target_window:
            return
        target = WindowTarget(**profile.target_window)
        resolved = inspector.resolve_target(target)
        if resolved is None:
            raise RuntimeError("Auto clicker target window not found.")
        inspector.focus_window(resolved.window_id)

    def _randomized_position(self, pos: ClickPosition, profile: AutoClickerProfile) -> tuple[int, int]:
        radius_x = pos.random_radius or profile.offset_radius_x
        radius_y = pos.random_radius or profile.offset_radius_y
        if pos.ellipse_radius_x or pos.ellipse_radius_y or profile.ellipse_radius_x or profile.ellipse_radius_y:
            radius_x = pos.ellipse_radius_x or profile.ellipse_radius_x or radius_x
            radius_y = pos.ellipse_radius_y or profile.ellipse_radius_y or radius_y
            angle = random.random() * math.tau
            return pos.x + int(math.cos(angle) * radius_x), pos.y + int(math.sin(angle) * radius_y)
        x = pos.x + (random.randint(-radius_x, radius_x) if radius_x else 0)
        y = pos.y + (random.randint(-radius_y, radius_y) if radius_y else 0)
        return x, y

    def _move_pointer(self, x: int, y: int, pos: ClickPosition, profile: AutoClickerProfile) -> None:
        movement_style = (pos.movement_style or profile.movement_style or "instant").lower()
        if movement_style in {"smooth", "bezier"}:
            start_x, start_y = self._current_mouse_position()
            steps = max(pos.bezier_steps or profile.bezier_steps or 16, 2)
            path = self._bezier_path(start_x, start_y, x, y, steps=steps, curvature=movement_style == "bezier")
            min_speed = max(pos.movement_speed_min_ms or profile.movement_speed_min_ms, 0)
            max_speed = max(pos.movement_speed_max_ms or profile.movement_speed_max_ms, min_speed)
            for point_x, point_y in path:
                self._run_xdotool(["xdotool", "mousemove", str(point_x), str(point_y)], profile)
                if max_speed > 0:
                    self._sleep_ms(random.randint(min_speed, max_speed))
        else:
            self._run_xdotool(["xdotool", "mousemove", str(x), str(y)], profile)

    def _current_mouse_position(self) -> tuple[int, int]:
        inspector = self._inspector
        if inspector is None:
            return 0, 0
        return inspector.pointer_position()

    def _bezier_path(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        *,
        steps: int,
        curvature: bool,
    ) -> list[tuple[int, int]]:
        mid_x = (start_x + end_x) / 2.0
        mid_y = (start_y + end_y) / 2.0
        if curvature:
            control_1 = (mid_x + (end_y - start_y) * 0.15, mid_y - (end_x - start_x) * 0.15)
            control_2 = (mid_x - (end_y - start_y) * 0.15, mid_y + (end_x - start_x) * 0.15)
        else:
            control_1 = (mid_x, start_y)
            control_2 = (mid_x, end_y)
        points: list[tuple[int, int]] = []
        for index in range(1, steps + 1):
            t = index / steps
            inv = 1.0 - t
            x = (
                inv * inv * inv * start_x
                + 3 * inv * inv * t * control_1[0]
                + 3 * inv * t * t * control_2[0]
                + t * t * t * end_x
            )
            y = (
                inv * inv * inv * start_y
                + 3 * inv * inv * t * control_1[1]
                + 3 * inv * t * t * control_2[1]
                + t * t * t * end_y
            )
            points.append((int(round(x)), int(round(y))))
        return points

    def _sleep_ms(self, ms: int) -> None:
        remaining = ms / 1000.0
        while remaining > 0 and not self._stop.is_set():
            self._pause.wait()
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk
