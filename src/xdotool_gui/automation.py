from __future__ import annotations

import math
import random
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from PySide6.QtCore import QObject, Signal

from .models import AutomationStep, MacroActionKind, WindowTarget
from .services.runtime import RetryPolicy, XdotoolRunner
from .services.x11 import X11Inspector, color_distance, parse_color


@dataclass(slots=True)
class MacroRunOptions:
    repeat: int = 1
    loop_forever: bool = False
    random_delay_min_ms: int = 0
    random_delay_max_ms: int = 0
    stop_on_error: bool = False
    delay_mode: str = "fixed"
    fixed_delay_ms: int = 0
    gaussian_mean_ms: int = 0
    gaussian_stdev_ms: int = 0
    humanize_delays: bool = False
    max_runtime_minutes: int = 0
    max_failures: int = 0
    continue_on_timeout: bool = False
    confirm_infinite_loops: bool = True
    retry_count: int = 3
    retry_delay_ms: int = 150
    target_window: WindowTarget | None = None
    stop_on_window_loss: bool = True
    macro_name: str = "Untitled macro"


@dataclass(slots=True)
class _ProgressSnapshot:
    cycle: int
    total_cycles: int
    completed_actions: int
    current_action: str
    macro_name: str
    elapsed_seconds: float
    average_cycle_seconds: float
    remaining_seconds: float | None
    finish_time: str
    percent: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "total_cycles": self.total_cycles,
            "completed_actions": self.completed_actions,
            "current_action": self.current_action,
            "macro_name": self.macro_name,
            "elapsed_seconds": self.elapsed_seconds,
            "average_cycle_seconds": self.average_cycle_seconds,
            "remaining_seconds": self.remaining_seconds,
            "finish_time": self.finish_time,
            "percent": self.percent,
        }


class MacroRunner(QObject):
    logMessage = Signal(str)
    stateChanged = Signal(str)
    finished = Signal(bool)
    progressChanged = Signal(object)
    failureCountChanged = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._failures = 0
        self._runner = XdotoolRunner()
        self._inspector: X11Inspector | None = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self, steps: list[AutomationStep], options: MacroRunOptions) -> bool:
        if self._active:
            return False
        self._stop.clear()
        self._pause.set()
        self._failures = 0
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
        started_at = time.monotonic()
        cycles_completed = 0
        try:
            enabled_steps = [step for step in steps if step.enabled]
            labels = self._label_map(enabled_steps)
            total_cycles = max(options.repeat, 1)
            self._inspector = X11Inspector()
            if options.loop_forever and options.confirm_infinite_loops:
                self.logMessage.emit("Infinite loop confirmed by settings.")
            while not self._stop.is_set():
                cycles_completed += 1
                cycle_started = time.monotonic()
                action_index = 0
                completed_actions = 0
                while action_index < len(enabled_steps) and not self._stop.is_set():
                    self._pause.wait()
                    if self._max_runtime_exceeded(started_at, options):
                        self.logMessage.emit("Maximum runtime reached; stopping automation.")
                        self._stop.set()
                        ok = False
                        break
                    step = enabled_steps[action_index]
                    current_action = self._step_label(step)
                    self._emit_progress(
                        cycle=cycles_completed,
                        total_cycles=0 if options.loop_forever else total_cycles,
                        completed_actions=completed_actions,
                        current_action=current_action,
                        macro_name=options.macro_name,
                        started_at=started_at,
                        cycles_completed=max(cycles_completed - 1, 0),
                        action_index=action_index,
                        actions_total=len(enabled_steps),
                    )
                    repeat_count = max(step.repeat, 1)
                    jump: int | None = None
                    for repeat_index in range(repeat_count):
                        if self._stop.is_set():
                            break
                        try:
                            jump = self._execute_step(step, options, labels)
                        except Exception as exc:  # pragma: no cover - defensive
                            ok = False
                            self._failures += 1
                            self.failureCountChanged.emit(self._failures)
                            self.logMessage.emit(f"Action failed: {current_action}: {exc}")
                            if options.stop_on_error or (options.max_failures and self._failures >= options.max_failures):
                                self._stop.set()
                                break
                            jump = None
                            continue
                        completed_actions += 1
                        if jump is not None:
                            break
                        self._sleep_action_delay(step, options)
                    if jump is not None:
                        action_index = jump
                    else:
                        action_index += 1
                if self._stop.is_set() or not options.loop_forever and cycles_completed >= total_cycles:
                    break
                self._emit_cycle_summary(cycles_completed, started_at, options, completed_actions, len(enabled_steps))
            self._emit_progress(
                cycle=cycles_completed,
                total_cycles=0 if options.loop_forever else total_cycles,
                completed_actions=0,
                current_action="stopped",
                macro_name=options.macro_name,
                started_at=started_at,
                cycles_completed=cycles_completed,
                action_index=len(enabled_steps),
                actions_total=len(enabled_steps),
            )
        except Exception as exc:  # pragma: no cover - defensive
            ok = False
            self.logMessage.emit(str(exc))
        finally:
            if self._inspector is not None:
                self._inspector.close()
                self._inspector = None
            self._active = False
            self.stateChanged.emit("idle")
            self.finished.emit(ok)

    def _execute_step(
        self,
        step: AutomationStep,
        options: MacroRunOptions,
        labels: dict[str, int],
    ) -> int | None:
        kind = (step.action_type or MacroActionKind.RUN_SHELL.value).strip().lower()
        params = dict(step.params or {})
        if step.command and kind == MacroActionKind.RUN_SHELL.value:
            params.setdefault("command", step.command)
        self._ensure_target_window(options)
        if kind == MacroActionKind.COMMENT.value:
            self.logMessage.emit(f"Comment: {step.command or step.label or params.get('text', '')}")
            return None
        if kind == MacroActionKind.LABEL.value:
            label = step.label or str(params.get("label", step.command)).strip()
            if label:
                self.logMessage.emit(f"Label reached: {label}")
            return None
        if kind == MacroActionKind.GOTO_LABEL.value:
            target = str(params.get("label", params.get("target", step.command))).strip()
            if not target:
                raise ValueError("Goto label requires a target label.")
            jump = labels.get(target)
            if jump is None:
                raise ValueError(f"Unknown label: {target}")
            self.logMessage.emit(f"Goto label: {target}")
            return jump
        if kind == MacroActionKind.CONDITIONAL_JUMP.value:
            self.logMessage.emit("Conditional jump is reserved for future workflows.")
            return None
        if kind == MacroActionKind.WAIT.value:
            timeout = max(int(params.get("timeout_ms", step.delay_ms or 0)), 0)
            self._sleep_ms(timeout)
            self.logMessage.emit(f"Waited {timeout} ms")
            return None
        if kind == MacroActionKind.WAIT_FOR_PIXEL.value:
            self._wait_for_pixel(params, options)
            return None
        if kind == MacroActionKind.WAIT_FOR_WINDOW.value:
            self._wait_for_window(params, options)
            return None
        if kind == MacroActionKind.RUN_PYTHON.value:
            self._run_python_script(params)
            return None
        if kind == MacroActionKind.MOUSE_MOVE.value:
            self._mouse_move(params, options)
            return None
        if kind == MacroActionKind.CLICK.value:
            self._click(params, button=1, options=options)
            return None
        if kind == MacroActionKind.DOUBLE_CLICK.value:
            self._click(params, button=int(params.get("button", 1)), clicks=2, options=options)
            return None
        if kind == MacroActionKind.RIGHT_CLICK.value:
            self._click(params, button=int(params.get("button", 3)), options=options)
            return None
        if kind == MacroActionKind.MIDDLE_CLICK.value:
            self._click(params, button=int(params.get("button", 2)), options=options)
            return None
        if kind == MacroActionKind.MOUSE_DOWN.value:
            self._run_xdotool(["xdotool", "mousedown", str(int(params.get("button", 1)))], options)
            return None
        if kind == MacroActionKind.MOUSE_UP.value:
            self._run_xdotool(["xdotool", "mouseup", str(int(params.get("button", 1)))], options)
            return None
        if kind == MacroActionKind.DRAG.value:
            self._drag(params, options)
            return None
        if kind == MacroActionKind.SCROLL.value:
            self._scroll(params, options)
            return None
        if kind == MacroActionKind.KEY_PRESS.value:
            self._key_press(params, options)
            return None
        if kind == MacroActionKind.KEY_DOWN.value:
            self._key_event("keydown", params, options)
            return None
        if kind == MacroActionKind.KEY_UP.value:
            self._key_event("keyup", params, options)
            return None
        if kind == MacroActionKind.TEXT.value:
            self._type_text(params, options)
            return None
        command = str(params.get("command", step.command)).strip()
        if not command:
            raise ValueError("Run shell action requires a command.")
        self._run_shell_command(command, options)
        return None

    def _ensure_target_window(self, options: MacroRunOptions) -> None:
        target = options.target_window
        inspector = self._inspector
        if inspector is None or target is None:
            return
        resolved = inspector.resolve_target(target)
        if resolved is None:
            message = "Target window not found."
            if options.stop_on_window_loss:
                raise RuntimeError(message)
            self.logMessage.emit(message)
            return
        if not inspector.window_exists(resolved.window_id):
            message = f"Target window disappeared: {resolved.window_id}"
            if options.stop_on_window_loss:
                raise RuntimeError(message)
            self.logMessage.emit(message)
            return
        try:
            inspector.focus_window(resolved.window_id)
            self.logMessage.emit(f"Focused window: {resolved.window_id} {resolved.title}")
        except Exception as exc:
            if options.stop_on_window_loss:
                raise RuntimeError(str(exc)) from exc
            self.logMessage.emit(f"Unable to focus target window: {exc}")

    def _run_xdotool(self, argv: list[str], options: MacroRunOptions) -> None:
        policy = RetryPolicy(attempts=max(options.retry_count, 1), delay_ms=max(options.retry_delay_ms, 0))
        result = self._runner.run(argv, policy=policy, logger=self.logMessage.emit)
        if result.returncode != 0:
            self._failures += 1
            self.failureCountChanged.emit(self._failures)
            raise RuntimeError(result.stderr.strip() or f"xdotool command failed: {' '.join(argv)}")
        self.logMessage.emit(f"Executed: {' '.join(argv)}")

    def _run_shell_command(self, command: str, options: MacroRunOptions) -> None:
        argv = shlex.split(command)
        if argv and argv[0] == "xdotool":
            self._run_xdotool(argv, options)
            return
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"Shell command failed: {command}")
        self.logMessage.emit(f"Shell: {command}")

    def _run_python_script(self, params: dict[str, Any]) -> None:
        script = str(params.get("script", "")).strip()
        if not script:
            raise ValueError("Python script is empty.")
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "Python script failed.")
        self.logMessage.emit("Python script executed.")

    def _mouse_move(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        movement_style = str(params.get("movement_style", params.get("style", "instant"))).strip().lower()
        radius_x = int(params.get("ellipse_radius_x", params.get("radius_x", params.get("random_radius", 0))))
        radius_y = int(params.get("ellipse_radius_y", params.get("radius_y", params.get("random_radius", 0))))
        offset_x = int(params.get("offset_radius_x", params.get("offset_x", 0)))
        offset_y = int(params.get("offset_radius_y", params.get("offset_y", 0)))
        if radius_x or radius_y:
            angle = random.random() * math.tau
            x += int(math.cos(angle) * (radius_x or radius_y))
            y += int(math.sin(angle) * (radius_y or radius_x))
        if offset_x:
            x += random.randint(-offset_x, offset_x)
        if offset_y:
            y += random.randint(-offset_y, offset_y)
        if movement_style in {"smooth", "bezier"}:
            steps = max(int(params.get("bezier_steps", params.get("steps", 16))), 2)
            path = self._bezier_path(*self._current_mouse_position(), x, y, steps=steps, curvature=movement_style == "bezier")
            for point in path:
                self._run_xdotool(["xdotool", "mousemove", str(point[0]), str(point[1])], options)
        else:
            self._run_xdotool(["xdotool", "mousemove", str(x), str(y)], options)
        self.logMessage.emit(f"Mouse moved to {x},{y}")

    def _click(self, params: dict[str, Any], button: int, options: MacroRunOptions, clicks: int = 1) -> None:
        button = int(params.get("button", button))
        count = max(int(params.get("clicks", clicks)), 1)
        if "x" in params and "y" in params:
            self._run_xdotool(["xdotool", "mousemove", str(int(params.get("x", 0))), str(int(params.get("y", 0)))], options)
        args = ["xdotool", "click"]
        if count > 1:
            args += ["--repeat", str(count)]
        args.append(str(button))
        self._run_xdotool(args, options)
        self.logMessage.emit(f"Click button {button} x{count}")

    def _drag(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        start_x = int(params.get("start_x", params.get("x", 0)))
        start_y = int(params.get("start_y", params.get("y", 0)))
        end_x = int(params.get("end_x", params.get("target_x", start_x)))
        end_y = int(params.get("end_y", params.get("target_y", start_y)))
        steps = max(int(params.get("bezier_steps", 16)), 2)
        button = int(params.get("button", 1))
        self._run_xdotool(["xdotool", "mousemove", str(start_x), str(start_y)], options)
        self._run_xdotool(["xdotool", "mousedown", str(button)], options)
        for point in self._bezier_path(start_x, start_y, end_x, end_y, steps=steps, curvature=True):
            self._run_xdotool(["xdotool", "mousemove", str(point[0]), str(point[1])], options)
        self._run_xdotool(["xdotool", "mouseup", str(button)], options)
        self.logMessage.emit(f"Drag from {start_x},{start_y} to {end_x},{end_y}")

    def _scroll(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        amount = int(params.get("amount", 1))
        direction = str(params.get("direction", "up")).strip().lower()
        button = 5 if direction in {"down", "south", "forward"} else 4
        for _ in range(max(amount, 1)):
            self._run_xdotool(["xdotool", "click", str(button)], options)
        self.logMessage.emit(f"Scroll {direction} x{amount}")

    def _key_press(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        key = str(params.get("key", params.get("keys", ""))).strip()
        if not key:
            raise ValueError("Key press requires a key.")
        repeat = max(int(params.get("repeat", 1)), 1)
        delay_ms = max(int(params.get("delay_ms", 0)), 0)
        argv = ["xdotool", "key"]
        if repeat > 1:
            argv += ["--repeat", str(repeat)]
        if delay_ms > 0:
            argv += ["--delay", str(delay_ms)]
        argv.append(key)
        self._run_xdotool(argv, options)

    def _key_event(self, action: str, params: dict[str, Any], options: MacroRunOptions) -> None:
        key = str(params.get("key", params.get("keys", ""))).strip()
        if not key:
            raise ValueError(f"{action} requires a key.")
        self._run_xdotool(["xdotool", action, key], options)

    def _type_text(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        text = str(params.get("text", params.get("value", "")))
        if not text:
            raise ValueError("Text typing requires text.")
        delay_ms = max(int(params.get("delay_ms", 0)), 0)
        clearmodifiers = bool(params.get("clearmodifiers", False))
        argv = ["xdotool", "type"]
        if clearmodifiers:
            argv.append("--clearmodifiers")
        if delay_ms > 0:
            argv += ["--delay", str(delay_ms)]
        argv.append(text)
        self._run_xdotool(argv, options)
        self.logMessage.emit("Typed text")

    def _wait_for_pixel(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        inspector = self._inspector
        if inspector is None:
            raise RuntimeError("X11 inspector is unavailable.")
        x = int(params.get("x", 0))
        y = int(params.get("y", 0))
        expected = params.get("color", params.get("hex", "#000000"))
        tolerance = max(int(params.get("tolerance", 0)), 0)
        poll_interval_ms = max(int(params.get("poll_interval_ms", params.get("interval_ms", 100))), 1)
        timeout_ms = max(int(params.get("timeout_ms", 0)), 0)
        continue_on_timeout = bool(params.get("continue_on_timeout", options.continue_on_timeout))
        target_rgb = parse_color(str(expected))
        started = time.monotonic()
        while not self._stop.is_set():
            self._pause.wait()
            current = inspector.pixel_rgb(x, y)
            if color_distance(current, target_rgb) <= tolerance:
                self.logMessage.emit(f"Pixel matched at {x},{y}: {current}")
                return
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if timeout_ms and elapsed_ms >= timeout_ms:
                message = f"Pixel wait timeout at {x},{y} after {int(elapsed_ms)} ms"
                self.logMessage.emit(message)
                if continue_on_timeout:
                    return
                raise TimeoutError(message)
            self._sleep_ms(poll_interval_ms)

    def _wait_for_window(self, params: dict[str, Any], options: MacroRunOptions) -> None:
        inspector = self._inspector
        if inspector is None:
            raise RuntimeError("X11 inspector is unavailable.")
        title = str(params.get("title", "")).strip()
        wm_class = str(params.get("class", params.get("wm_class", ""))).strip()
        regex_value = params.get("regex", "")
        if isinstance(regex_value, bool):
            regex = title if regex_value else ""
        else:
            regex = str(regex_value).strip()
        timeout_ms = max(int(params.get("timeout_ms", 0)), 0)
        continue_on_timeout = bool(params.get("continue_on_timeout", options.continue_on_timeout))
        started = time.monotonic()
        while not self._stop.is_set():
            self._pause.wait()
            found = inspector.search_windows(title=title, wm_class=wm_class, regex=regex)
            if found:
                window = found[0]
                inspector.focus_window(window.window_id)
                self.logMessage.emit(f"Window ready: {window.window_id} {window.title}")
                return
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if timeout_ms and elapsed_ms >= timeout_ms:
                message = f"Window wait timeout after {int(elapsed_ms)} ms"
                self.logMessage.emit(message)
                if continue_on_timeout:
                    return
                raise TimeoutError(message)
            self._sleep_ms(250)

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
        steps = max(steps, 2)
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
            x = self._cubic_bezier(start_x, control_1[0], control_2[0], end_x, t)
            y = self._cubic_bezier(start_y, control_1[1], control_2[1], end_y, t)
            points.append((int(round(x)), int(round(y))))
        return points

    @staticmethod
    def _cubic_bezier(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
        inv = 1.0 - t
        return (
            inv * inv * inv * p0
            + 3 * inv * inv * t * p1
            + 3 * inv * t * t * p2
            + t * t * t * p3
        )

    def _current_mouse_position(self) -> tuple[int, int]:
        inspector = self._inspector
        if inspector is None:
            return 0, 0
        return inspector.pointer_position()

    def _sleep_action_delay(self, step: AutomationStep, options: MacroRunOptions) -> None:
        delay_ms = self._resolve_delay_ms(step, options)
        if delay_ms > 0:
            self._sleep_ms(delay_ms)

    def _resolve_delay_ms(self, step: AutomationStep, options: MacroRunOptions) -> int:
        base = max(step.delay_ms, 0)
        if options.delay_mode == "random":
            low = max(options.random_delay_min_ms, 0)
            high = max(options.random_delay_max_ms, low)
            return random.randint(low, high) if high else base
        if options.delay_mode == "gaussian":
            mean = options.gaussian_mean_ms or base
            stdev = max(options.gaussian_stdev_ms, 1)
            return max(0, int(round(random.gauss(mean, stdev))))
        if options.delay_mode == "humanized":
            mean = options.fixed_delay_ms or base
            stdev = max(int(mean * 0.2), 15)
            return max(0, int(round(random.gauss(mean, stdev))))
        if options.fixed_delay_ms > 0:
            base = options.fixed_delay_ms
        if options.humanize_delays and base > 0:
            stdev = max(int(base * 0.15), 10)
            return max(0, int(round(random.gauss(base, stdev))))
        return base

    def _sleep_ms(self, ms: int) -> None:
        remaining = max(ms, 0) / 1000.0
        while remaining > 0 and not self._stop.is_set():
            self._pause.wait()
            chunk = min(0.1, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _label_map(self, steps: list[AutomationStep]) -> dict[str, int]:
        labels: dict[str, int] = {}
        for index, step in enumerate(steps):
            label = self._step_label(step)
            if step.action_type == MacroActionKind.LABEL.value and label:
                labels[label] = index
        return labels

    def _step_label(self, step: AutomationStep) -> str:
        if step.label.strip():
            return step.label.strip()
        if step.action_type == MacroActionKind.LABEL.value:
            return step.command.strip() or str(step.params.get("label", "")).strip()
        return step.command.strip() or step.action_type

    def _emit_cycle_summary(
        self,
        cycles_completed: int,
        started_at: float,
        options: MacroRunOptions,
        completed_actions: int,
        actions_total: int,
    ) -> None:
        elapsed = time.monotonic() - started_at
        average_cycle = elapsed / max(cycles_completed, 1)
        self.logMessage.emit(
            f"Cycle {cycles_completed} complete | actions={completed_actions} | avg_cycle={self._format_seconds(average_cycle)}"
        )
        self._emit_progress(
            cycle=cycles_completed,
            total_cycles=0 if options.loop_forever else max(options.repeat, 1),
            completed_actions=completed_actions,
            current_action="idle",
            macro_name=options.macro_name,
            started_at=started_at,
            cycles_completed=cycles_completed,
            action_index=actions_total,
            actions_total=max(actions_total, 1),
        )

    def _emit_progress(
        self,
        *,
        cycle: int,
        total_cycles: int,
        completed_actions: int,
        current_action: str,
        macro_name: str,
        started_at: float,
        cycles_completed: int,
        action_index: int,
        actions_total: int,
    ) -> None:
        elapsed = time.monotonic() - started_at
        average_cycle = elapsed / max(cycles_completed or cycle, 1)
        remaining_seconds: float | None
        percent: float | None
        if total_cycles > 0:
            cycle_fraction = max(cycle - 1, 0) + (action_index / max(actions_total, 1))
            overall_fraction = min(max(cycle_fraction / total_cycles, 0.0), 1.0)
            remaining_cycles = max(total_cycles - cycle_fraction, 0.0)
            remaining_seconds = remaining_cycles * average_cycle
            percent = overall_fraction * 100.0
        else:
            remaining_seconds = None
            percent = None
        finish_time = datetime.now() + timedelta(seconds=remaining_seconds or 0)
        snapshot = _ProgressSnapshot(
            cycle=cycle,
            total_cycles=total_cycles,
            completed_actions=completed_actions,
            current_action=current_action,
            macro_name=macro_name,
            elapsed_seconds=elapsed,
            average_cycle_seconds=average_cycle,
            remaining_seconds=remaining_seconds,
            finish_time=finish_time.strftime("%H:%M"),
            percent=percent,
        )
        self.progressChanged.emit(snapshot.as_dict())

    def _max_runtime_exceeded(self, started_at: float, options: MacroRunOptions) -> bool:
        if options.max_runtime_minutes <= 0:
            return False
        return (time.monotonic() - started_at) >= (options.max_runtime_minutes * 60)

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        total = max(int(seconds), 0)
        minutes, secs = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"
