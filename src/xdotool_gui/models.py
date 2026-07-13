from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass(slots=True)
class RecorderEvent:
    timestamp: float
    type: str
    x: int | None = None
    y: int | None = None
    button: int | None = None
    key: str | None = None
    delta: int | None = None
    modifiers: tuple[str, ...] = ()
    double_click: bool = False
    text: str | None = None


class CommandCategory(str, Enum):
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    WINDOWS = "windows"
    DESKTOP = "desktop"
    TYPING = "typing"
    AUTOMATION = "automation"
    AUTO_CLICKER = "auto_clicker"
    TERMINAL = "terminal"


class CommandOrder(str, Enum):
    SEQUENTIAL = "sequential"
    RANDOM = "random"
    WEIGHTED = "weighted"


class MacroActionKind(str, Enum):
    RUN_SHELL = "run_shell"
    RUN_PYTHON = "run_python_script"
    MOUSE_MOVE = "mouse_move"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MIDDLE_CLICK = "middle_click"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    DRAG = "drag"
    SCROLL = "scroll"
    KEY_PRESS = "key_press"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    TEXT = "text"
    WAIT = "wait"
    WAIT_FOR_PIXEL = "wait_for_pixel"
    WAIT_FOR_WINDOW = "wait_for_window"
    COMMENT = "comment"
    LABEL = "label"
    GOTO_LABEL = "goto_label"
    CONDITIONAL_JUMP = "conditional_jump"


@dataclass(slots=True)
class CommandSpec:
    argv: list[str]
    preview: str
    description: str = ""
    category: CommandCategory = CommandCategory.TERMINAL


@dataclass(slots=True)
class ExecutionResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime

    @property
    def success(self) -> bool:
        return self.returncode == 0


@dataclass(slots=True)
class AutomationStep:
    command: str = ""
    action_type: str = MacroActionKind.RUN_SHELL.value
    params: dict[str, Any] = field(default_factory=dict)
    delay_ms: int = 0
    repeat: int = 1
    enabled: bool = True
    label: str = ""


@dataclass(slots=True)
class ClickPosition:
    name: str
    x: int
    y: int
    button: int = 1
    clicks: int = 1
    delay_ms: int = 0
    interval_ms: int = 100
    order: int = 0
    enabled: bool = True
    random_radius: int = 0
    jitter_ms: int = 0
    loop: bool = False
    priority: int = 0
    movement_style: str = "instant"
    ellipse_radius_x: int = 0
    ellipse_radius_y: int = 0
    offset_radius_x: int = 0
    offset_radius_y: int = 0
    bezier_steps: int = 16
    movement_speed_min_ms: int = 0
    movement_speed_max_ms: int = 0


@dataclass(slots=True)
class AutoClickerProfile:
    positions: list[ClickPosition] = field(default_factory=list)
    order: CommandOrder = CommandOrder.SEQUENTIAL
    clicks_per_second: float = 5.0
    random_cps: bool = False
    loop_forever: bool = True
    loops: int = 1
    start_delay_ms: int = 0
    stop_delay_ms: int = 0
    total_clicks: int = 0
    target_window: dict[str, Any] = field(default_factory=dict)
    movement_style: str = "instant"
    ellipse_radius_x: int = 0
    ellipse_radius_y: int = 0
    offset_radius_x: int = 0
    offset_radius_y: int = 0
    bezier_steps: int = 16
    movement_speed_min_ms: int = 0
    movement_speed_max_ms: int = 0


@dataclass(slots=True)
class WindowTarget:
    window_id: str = ""
    title: str = ""
    wm_class: str = ""
    regex: bool = False


@dataclass(slots=True)
class WindowInfo:
    window_id: int
    title: str
    wm_class: str = ""
    pid: int = 0
    desktop: int = -1
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    mapped: bool = False


@dataclass(slots=True)
class HistoryEntry:
    command: str
    timestamp: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    favorite: bool = False
    pinned: bool = False


@dataclass(slots=True)
class PresetEntry:
    name: str
    category: str
    payload: dict[str, Any]
