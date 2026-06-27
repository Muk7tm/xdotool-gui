from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
    command: str
    delay_ms: int = 0
    repeat: int = 1
    enabled: bool = True


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
