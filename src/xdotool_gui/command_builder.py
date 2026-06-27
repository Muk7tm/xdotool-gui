from __future__ import annotations

import shlex
from typing import Iterable, Sequence

from .models import CommandCategory, CommandSpec


def preview(argv: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def _spec(argv: list[str], description: str, category: CommandCategory) -> CommandSpec:
    return CommandSpec(argv=argv, preview=preview(argv), description=description, category=category)


def raw_command(text: str) -> CommandSpec:
    parts = shlex.split(text)
    if not parts:
        raise ValueError("Enter a raw xdotool command first.")
    if parts[0] == "xdotool":
        parts = parts[1:]
    argv = ["xdotool", *parts]
    return _spec(argv, "Raw xdotool command", CommandCategory.TERMINAL)


def keyboard_key(keys: Iterable[str], repeat: int = 1, delay_ms: int = 0) -> CommandSpec:
    argv = ["xdotool", "key"]
    if repeat > 1:
        argv += ["--repeat", str(repeat)]
    if delay_ms > 0:
        argv += ["--delay", str(delay_ms)]
    argv.extend(key for key in keys if key)
    return _spec(argv, "Keyboard key sequence", CommandCategory.KEYBOARD)


def keyboard_keydown(key: str) -> CommandSpec:
    return _spec(["xdotool", "keydown", key], "Keyboard key down", CommandCategory.KEYBOARD)


def keyboard_keyup(key: str) -> CommandSpec:
    return _spec(["xdotool", "keyup", key], "Keyboard key up", CommandCategory.KEYBOARD)


def keyboard_type(text: str, delay_ms: int = 0, clearmodifiers: bool = False) -> CommandSpec:
    argv = ["xdotool", "type"]
    if clearmodifiers:
        argv.append("--clearmodifiers")
    if delay_ms > 0:
        argv += ["--delay", str(delay_ms)]
    argv.append(text)
    return _spec(argv, "Keyboard type text", CommandCategory.TYPING)


def mouse_move(x: int, y: int) -> CommandSpec:
    return _spec(["xdotool", "mousemove", str(x), str(y)], "Move mouse", CommandCategory.MOUSE)


def mouse_move_relative(dx: int, dy: int, window: str | None = None) -> CommandSpec:
    argv = ["xdotool", "mousemove_relative"]
    if window:
        argv += ["--window", window]
    argv += ["--", str(dx), str(dy)]
    return _spec(argv, "Move mouse relative", CommandCategory.MOUSE)


def mouse_click(button: int, repeat: int = 1, delay_ms: int = 0) -> CommandSpec:
    argv = ["xdotool", "click"]
    if repeat > 1:
        argv += ["--repeat", str(repeat)]
    if delay_ms > 0:
        argv += ["--delay", str(delay_ms)]
    argv.append(str(button))
    return _spec(argv, "Mouse click", CommandCategory.MOUSE)


def mouse_location() -> CommandSpec:
    return _spec(["xdotool", "getmouselocation", "--shell"], "Mouse location", CommandCategory.MOUSE)


def window_search(term: str, by: str = "name") -> CommandSpec:
    option = f"--{by}" if by in {"name", "class", "classname", "pid", "desktop"} else "--name"
    return _spec(["xdotool", "search", option, term], "Search windows", CommandCategory.WINDOWS)


def window_action(action: str, window_id: str | None = None, *extra: str) -> CommandSpec:
    argv = ["xdotool", action]
    if window_id:
        argv.append(window_id)
    argv.extend(str(part) for part in extra if part is not None)
    return _spec(argv, f"Window action: {action}", CommandCategory.WINDOWS)


def window_state(window_id: str, states: list[str], remove: bool = False) -> CommandSpec:
    argv = ["xdotool", "windowstate"]
    argv.append("--remove" if remove else "--add")
    argv.extend(states)
    argv.append(window_id)
    return _spec(argv, "Window state change", CommandCategory.WINDOWS)


def desktop_action(action: str, *extra: str) -> CommandSpec:
    return _spec(["xdotool", action, *map(str, extra)], "Desktop action", CommandCategory.DESKTOP)
