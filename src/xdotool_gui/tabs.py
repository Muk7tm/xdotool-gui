from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QMenu,
)

from .automation import MacroRunOptions, MacroRunner
from .autoclicker import AutoClickerController
from .command_builder import (
    desktop_action,
    keyboard_key,
    keyboard_keydown,
    keyboard_keyup,
    keyboard_type,
    mouse_click,
    mouse_location,
    mouse_move,
    mouse_move_relative,
    raw_command,
    window_action,
    window_search,
    window_state,
)
from .hotkey_registry import HOTKEY_ACTIONS, hotkey_defaults, normalize_hotkey_bindings
from .models import AutoClickerProfile, AutomationStep, ClickPosition, CommandSpec, CommandOrder, HistoryEntry, MacroActionKind, PresetEntry, WindowInfo, WindowTarget
from .services.recorder import RecorderService
from .services.x11 import X11Inspector, parse_color


class BaseCommandTab(QWidget):
    commandChanged = Signal()

    def preview_command(self) -> str:
        spec = self.command_spec()
        return spec.preview if spec else ""

    def command_spec(self) -> CommandSpec | None:
        return None

    def execute_direct(self) -> bool:
        return False


MACRO_ACTION_LABELS: dict[str, str] = {
    MacroActionKind.RUN_SHELL.value: "Run Shell Command",
    MacroActionKind.RUN_PYTHON.value: "Run Python Script",
    MacroActionKind.MOUSE_MOVE.value: "Mouse Move",
    MacroActionKind.CLICK.value: "Click",
    MacroActionKind.DOUBLE_CLICK.value: "Double Click",
    MacroActionKind.RIGHT_CLICK.value: "Right Click",
    MacroActionKind.MIDDLE_CLICK.value: "Middle Click",
    MacroActionKind.MOUSE_DOWN.value: "Mouse Down",
    MacroActionKind.MOUSE_UP.value: "Mouse Up",
    MacroActionKind.DRAG.value: "Drag",
    MacroActionKind.SCROLL.value: "Scroll",
    MacroActionKind.KEY_PRESS.value: "Key Press",
    MacroActionKind.KEY_DOWN.value: "Key Down",
    MacroActionKind.KEY_UP.value: "Key Up",
    MacroActionKind.TEXT.value: "Text Typing",
    MacroActionKind.WAIT.value: "Wait",
    MacroActionKind.WAIT_FOR_PIXEL.value: "Wait For Pixel",
    MacroActionKind.WAIT_FOR_WINDOW.value: "Wait For Window",
    MacroActionKind.COMMENT.value: "Comment",
    MacroActionKind.LABEL.value: "Label",
    MacroActionKind.GOTO_LABEL.value: "Goto Label",
    MacroActionKind.CONDITIONAL_JUMP.value: "Conditional Jump",
}

MACRO_ACTIONS = list(MACRO_ACTION_LABELS.keys())


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _safe_int(text: str, fallback: int = 0) -> int:
    try:
        return int(text.strip())
    except Exception:
        return fallback


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _textish(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    return str(value).strip()


class KeyboardTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_combo = QComboBox()
        self.action_combo.addItems(["key", "keydown", "keyup", "type", "sequence"])
        self.keys_edit = QLineEdit("ctrl+s")
        self.sequence_edit = QLineEdit("ctrl+s alt+F4")
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Text to type")
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 9999)
        self.repeat_spin.setValue(1)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 60000)
        self.delay_spin.setValue(0)
        self.clearmodifiers = QCheckBox("Clear modifiers")
        self.preview = QLabel()
        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow("Key or keys", self.keys_edit)
        form.addRow("Key sequence", self.sequence_edit)
        form.addRow("Type text", self.text_edit)
        form.addRow("Repeat", self.repeat_spin)
        form.addRow("Delay ms", self.delay_spin)
        form.addRow("", self.clearmodifiers)
        box = QGroupBox("Keyboard")
        box.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(self.preview)
        for widget in [self.action_combo, self.keys_edit, self.sequence_edit, self.text_edit, self.repeat_spin, self.delay_spin, self.clearmodifiers]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(lambda *_: self.commandChanged.emit())
        self.commandChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.setText(self.preview_command())

    def command_spec(self) -> CommandSpec | None:
        action = self.action_combo.currentText()
        if action == "key":
            keys = [part for part in self.keys_edit.text().split() if part]
            return keyboard_key(keys, self.repeat_spin.value(), self.delay_spin.value()) if keys else None
        if action == "keydown":
            key = self.keys_edit.text().strip()
            return keyboard_keydown(key) if key else None
        if action == "keyup":
            key = self.keys_edit.text().strip()
            return keyboard_keyup(key) if key else None
        if action == "type":
            text = self.text_edit.toPlainText()
            return keyboard_type(text, self.delay_spin.value(), self.clearmodifiers.isChecked()) if text else None
        keys = [part.strip() for part in self.sequence_edit.text().split() if part.strip()]
        return keyboard_key(keys, self.repeat_spin.value(), self.delay_spin.value()) if keys else None


class MouseTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_combo = QComboBox()
        self.action_combo.addItems(["move", "move_relative", "click", "location"])
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-100000, 100000)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-100000, 100000)
        self.dx_spin = QSpinBox()
        self.dx_spin.setRange(-100000, 100000)
        self.dy_spin = QSpinBox()
        self.dy_spin.setRange(-100000, 100000)
        self.button_spin = QSpinBox()
        self.button_spin.setRange(1, 10)
        self.button_spin.setValue(1)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 1000)
        self.repeat_spin.setValue(1)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 60000)
        self.window_id = QLineEdit()
        self.capture_button = QPushButton("Record Position")
        self.capture_button.setToolTip("Insert the current mouse position into the active fields.")
        self.location_label = QLabel("0, 0")
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._update_location)
        self.timer.start()
        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("Delta X", self.dx_spin)
        form.addRow("Delta Y", self.dy_spin)
        form.addRow("Button", self.button_spin)
        form.addRow("Repeat", self.repeat_spin)
        form.addRow("Delay ms", self.delay_spin)
        form.addRow("Window id", self.window_id)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.capture_button)
        btn_row.addWidget(self.location_label)
        btn_row.addWidget(QLabel("Hotkey: F8"))
        btn_box = QWidget()
        btn_box.setLayout(btn_row)
        box = QGroupBox("Mouse")
        box.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(btn_box)
        for widget in [self.action_combo, self.x_spin, self.y_spin, self.dx_spin, self.dy_spin, self.button_spin, self.repeat_spin, self.delay_spin, self.window_id]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(lambda *_: self.commandChanged.emit())
        self.capture_button.clicked.connect(lambda: self.capture_position())
        self.commandChanged.connect(self._refresh_location_preview)
        self._refresh_location_preview()

    def _refresh_location_preview(self) -> None:
        self.location_label.setText(self.preview_command())

    def _update_location(self) -> None:
        pos = QCursor.pos()
        self.location_label.setText(f"{pos.x()}, {pos.y()}")

    def capture_position(self) -> None:
        pos = QCursor.pos()
        self.x_spin.setValue(pos.x())
        self.y_spin.setValue(pos.y())
        self.commandChanged.emit()

    def command_spec(self) -> CommandSpec | None:
        action = self.action_combo.currentText()
        if action == "move":
            return mouse_move(self.x_spin.value(), self.y_spin.value())
        if action == "move_relative":
            return mouse_move_relative(self.dx_spin.value(), self.dy_spin.value(), self.window_id.text().strip() or None)
        if action == "click":
            return mouse_click(self.button_spin.value(), self.repeat_spin.value(), self.delay_spin.value())
        return mouse_location()


class WindowsTab(BaseCommandTab):
    windowTargetChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_combo = QComboBox()
        self.action_combo.addItems([
            "search",
            "activate",
            "focus",
            "raise",
            "lower",
            "move",
            "resize",
            "minimize",
            "maximize",
            "fullscreen",
            "close",
            "kill",
            "set_desktop",
            "get_active_window",
            "get_geometry",
            "window_class",
            "window_title",
            "pid",
            "window_stack",
            "window_list",
        ])
        self.search_edit = QLineEdit()
        self.class_edit = QLineEdit()
        self.regex_edit = QLineEdit()
        self.window_id = QLineEdit()
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-100000, 100000)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-100000, 100000)
        self.w_spin = QSpinBox()
        self.w_spin.setRange(1, 200000)
        self.h_spin = QSpinBox()
        self.h_spin.setRange(1, 200000)
        self.desktop_spin = QSpinBox()
        self.desktop_spin.setRange(0, 128)

        self.refresh_button = QPushButton("Refresh Windows")
        self.use_selected_button = QPushButton("Use Selected")
        self.save_target_button = QPushButton("Save Target")
        self.target_id = QLineEdit()
        self.target_title = QLineEdit()
        self.target_class = QLineEdit()
        self.target_id.setReadOnly(True)
        self.target_title.setReadOnly(True)
        self.target_class.setReadOnly(True)
        self.target_regex = QCheckBox("Regex")
        self.target_regex.setEnabled(False)

        self.windows_table = QTableWidget(0, 8)
        self.windows_table.setHorizontalHeaderLabels(["ID", "Title", "Class", "PID", "Desktop", "X", "Y", "Size"])
        self.windows_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.windows_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.windows_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.windows_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.windows_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self.preview = QLabel()
        self.preview.setWordWrap(True)

        filter_form = QFormLayout()
        filter_form.addRow("Search title", self.search_edit)
        filter_form.addRow("Search class", self.class_edit)
        filter_form.addRow("Regex", self.regex_edit)
        filter_box = QGroupBox("Window Browser")
        filter_box.setLayout(filter_form)

        target_form = QFormLayout()
        target_form.addRow("Window id", self.target_id)
        target_form.addRow("Title", self.target_title)
        target_form.addRow("Class", self.target_class)
        target_form.addRow("", self.target_regex)
        target_box = QGroupBox("Target Window")
        target_box.setLayout(target_form)

        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow("Search / term", self.search_edit)
        form.addRow("Window id", self.window_id)
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("Width", self.w_spin)
        form.addRow("Height", self.h_spin)
        form.addRow("Desktop", self.desktop_spin)
        action_box = QGroupBox("Window Actions")
        action_box.setLayout(form)

        top_buttons = QHBoxLayout()
        for widget in [self.refresh_button, self.use_selected_button, self.save_target_button]:
            top_buttons.addWidget(widget)

        layout = QVBoxLayout(self)
        layout.addWidget(filter_box)
        layout.addWidget(self.windows_table)
        layout.addLayout(top_buttons)
        layout.addWidget(target_box)
        layout.addWidget(action_box)
        layout.addWidget(self.preview)

        for widget in [self.action_combo, self.search_edit, self.class_edit, self.regex_edit, self.window_id, self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.desktop_spin]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(lambda *_: self.commandChanged.emit())

        self.refresh_button.clicked.connect(self.refresh_windows)
        self.use_selected_button.clicked.connect(self._use_selected_window)
        self.save_target_button.clicked.connect(self._save_target_window)
        self.windows_table.itemSelectionChanged.connect(self._sync_selected_window)
        self.windows_table.cellDoubleClicked.connect(lambda *_: self._save_target_window())
        self.commandChanged.connect(lambda: self.preview.setText(self.preview_command()))
        self.preview.setText(self.preview_command())
        self.refresh_windows()

    def refresh_windows(self) -> None:
        inspector: X11Inspector | None = None
        try:
            inspector = X11Inspector()
            windows = inspector.search_windows(
                title=self.search_edit.text(),
                wm_class=self.class_edit.text(),
                regex=self.regex_edit.text(),
            )
        except Exception as exc:
            self.windows_table.setRowCount(0)
            self.preview.setText(f"Unable to list windows: {exc}")
            return
        finally:
            if inspector is not None:
                inspector.close()
        self.windows_table.setRowCount(0)
        for window in windows:
            self._add_window_row(window)
        self.preview.setText(f"{len(windows)} windows")
        self.commandChanged.emit()

    def _add_window_row(self, window: WindowInfo) -> None:
        row = self.windows_table.rowCount()
        self.windows_table.insertRow(row)
        values = [
            hex(window.window_id),
            window.title,
            window.wm_class,
            str(window.pid),
            str(window.desktop),
            str(window.x),
            str(window.y),
            f"{window.width}x{window.height}",
        ]
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, window.window_id)
            self.windows_table.setItem(row, col, item)

    def _selected_window_info(self) -> WindowInfo | None:
        row = self.windows_table.currentRow()
        if row < 0:
            return None
        try:
            return WindowInfo(
                window_id=int(self.windows_table.item(row, 0).data(Qt.ItemDataRole.UserRole)),
                title=self.windows_table.item(row, 1).text(),
                wm_class=self.windows_table.item(row, 2).text(),
                pid=_safe_int(self.windows_table.item(row, 3).text()),
                desktop=_safe_int(self.windows_table.item(row, 4).text(), -1),
                x=_safe_int(self.windows_table.item(row, 5).text()),
                y=_safe_int(self.windows_table.item(row, 6).text()),
                width=_safe_int(self.windows_table.item(row, 7).text().split("x")[0]),
                height=_safe_int(self.windows_table.item(row, 7).text().split("x")[-1]),
                mapped=True,
            )
        except Exception:
            return None

    def _sync_selected_window(self) -> None:
        window = self._selected_window_info()
        if window is None:
            return
        self.target_id.setText(hex(window.window_id))
        self.target_title.setText(window.title)
        self.target_class.setText(window.wm_class)
        self.preview.setText(f"Selected window: {window.title or window.window_id}")
        self.commandChanged.emit()

    def selected_target(self) -> WindowTarget:
        return WindowTarget(
            window_id=self.target_id.text().strip(),
            title=self.target_title.text().strip(),
            wm_class=self.target_class.text().strip(),
            regex=self.target_regex.isChecked(),
        )

    def set_target(self, target: dict[str, Any]) -> None:
        self.target_id.setText(str(target.get("window_id", "")))
        self.target_title.setText(str(target.get("title", "")))
        self.target_class.setText(str(target.get("wm_class", "")))
        self.target_regex.setChecked(bool(target.get("regex", False)))

    def _use_selected_window(self) -> None:
        window = self._selected_window_info()
        if window is None:
            QMessageBox.information(self, "Windows", "Select a window first.")
            return
        self.target_id.setText(hex(window.window_id))
        self.target_title.setText(window.title)
        self.target_class.setText(window.wm_class)
        self.preview.setText(f"Target prepared: {window.title or window.window_id}")
        self.commandChanged.emit()

    def _save_target_window(self) -> None:
        window = self._selected_window_info()
        if window is None:
            QMessageBox.information(self, "Windows", "Select a window first.")
            return
        self._use_selected_window()
        self.windowTargetChanged.emit(asdict(self.selected_target()))
        QMessageBox.information(self, "Windows", "Target window saved.")

    def command_spec(self) -> CommandSpec | None:
        action = self.action_combo.currentText()
        window_id = self.window_id.text().strip() or None
        if action == "search":
            term = self.search_edit.text().strip()
            return window_search(term, "name") if term else None
        if action == "activate":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowactivate", target) if target else None
        if action == "focus":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowfocus", target) if target else None
        if action == "raise":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowraise", target) if target else None
        if action == "lower":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowlower", target) if target else None
        if action == "move":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowmove", target, str(self.x_spin.value()), str(self.y_spin.value())) if target else None
        if action == "resize":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowsize", target, str(self.w_spin.value()), str(self.h_spin.value())) if target else None
        if action == "minimize":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowminimize", target) if target else None
        if action == "maximize":
            target = window_id or self.search_edit.text().strip()
            return window_state(target, ["MAXIMIZED_VERT", "MAXIMIZED_HORZ"]) if target else None
        if action == "fullscreen":
            target = window_id or self.search_edit.text().strip()
            return window_state(target, ["FULLSCREEN"]) if target else None
        if action == "close":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowclose", target) if target else None
        if action == "kill":
            target = window_id or self.search_edit.text().strip()
            return window_action("windowkill", target) if target else None
        if action == "set_desktop":
            target = window_id or self.search_edit.text().strip()
            return window_action("set_desktop_for_window", target, str(self.desktop_spin.value())) if target else None
        if action == "get_active_window":
            return window_action("getactivewindow")
        if action == "get_geometry":
            target = window_id or self.search_edit.text().strip()
            return window_action("getwindowgeometry", target) if target else None
        if action == "window_class":
            target = window_id or self.search_edit.text().strip()
            return window_action("getwindowclassname", target) if target else None
        if action == "window_title":
            target = window_id or self.search_edit.text().strip()
            return window_action("getwindowname", target) if target else None
        if action == "pid":
            target = window_id or self.search_edit.text().strip()
            return window_action("getwindowpid", target) if target else None
        if action == "window_stack":
            target = window_id or self.search_edit.text().strip()
            return window_action("getwindowstack", target) if target else None
        return window_action("windowlist")


class DesktopTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.action_combo = QComboBox()
        self.action_combo.addItems(["switch", "current", "info", "move_window"])
        self.desktop_spin = QSpinBox()
        self.desktop_spin.setRange(0, 128)
        self.window_id = QLineEdit()
        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow("Desktop", self.desktop_spin)
        form.addRow("Window id", self.window_id)
        box = QGroupBox("Desktop")
        box.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(box)
        self.preview = QLabel()
        layout.addWidget(self.preview)
        for widget in [self.action_combo, self.desktop_spin, self.window_id]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_: self.commandChanged.emit())
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(lambda *_: self.commandChanged.emit())
        self.commandChanged.connect(lambda: self.preview.setText(self.preview_command()))
        self.preview.setText(self.preview_command())

    def command_spec(self) -> CommandSpec | None:
        action = self.action_combo.currentText()
        if action == "switch":
            return desktop_action("set_desktop", str(self.desktop_spin.value()))
        if action == "current":
            return desktop_action("get_desktop")
        if action == "info":
            return desktop_action("get_num_desktops")
        target = self.window_id.text().strip()
        return desktop_action("set_desktop_for_window", target, str(self.desktop_spin.value())) if target else None


class TypingTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText("Enter the text to type")
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(0, 1000)
        self.clearmodifiers = QCheckBox("Clear modifiers")
        self.clipboard_button = QPushButton("Load Clipboard")
        self.preview = QLabel()
        form = QFormLayout()
        form.addRow("Delay ms", self.delay_spin)
        form.addRow("", self.clearmodifiers)
        form.addRow("", self.clipboard_button)
        box = QGroupBox("Typing")
        box.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)
        layout.addWidget(box)
        layout.addWidget(self.preview)
        self.text_edit.textChanged.connect(lambda *_: self.commandChanged.emit())
        self.delay_spin.valueChanged.connect(lambda *_: self.commandChanged.emit())
        self.clearmodifiers.stateChanged.connect(lambda *_: self.commandChanged.emit())
        self.clipboard_button.clicked.connect(lambda: self.load_clipboard())
        self.commandChanged.connect(lambda: self.preview.setText(self.preview_command()))
        self.preview.setText(self.preview_command())

    def load_clipboard(self) -> None:
        self.text_edit.setPlainText(QApplication.clipboard().text())
        self.commandChanged.emit()

    def command_spec(self) -> CommandSpec | None:
        text = self.text_edit.toPlainText()
        return keyboard_type(text, self.delay_spin.value(), self.clearmodifiers.isChecked()) if text else None


class AutomationTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Enabled", "Command", "Delay ms", "Repeat"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 9999)
        self.repeat_spin.setValue(1)
        self.loop_forever = QCheckBox("Loop forever")
        self.random_min = QSpinBox()
        self.random_min.setRange(0, 60000)
        self.random_max = QSpinBox()
        self.random_max.setRange(0, 60000)
        self.stop_on_error = QCheckBox("Stop on error")
        self.add_button = QPushButton("Add Step")
        self.remove_button = QPushButton("Remove Step")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.record_hint = QLabel("Record mouse moves and clicks into the macro table, then play them back in a loop.")
        self.record_hint.setWordWrap(True)
        self.recording_label = QLabel("Recorder idle")
        self.status = QLabel("idle")
        buttons = QHBoxLayout()
        for widget in [self.add_button, self.remove_button, self.up_button, self.down_button, self.start_button, self.pause_button, self.resume_button, self.stop_button]:
            buttons.addWidget(widget)
        form = QFormLayout()
        form.addRow("Repeat", self.repeat_spin)
        form.addRow("Random delay min ms", self.random_min)
        form.addRow("Random delay max ms", self.random_max)
        form.addRow("", self.loop_forever)
        form.addRow("", self.stop_on_error)
        top = QWidget()
        top.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(top)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.runner = MacroRunner(self)
        self.runner.logMessage.connect(self._set_status)
        self.runner.stateChanged.connect(self.status.setText)
        self.add_button.clicked.connect(lambda: self.add_step())
        self.remove_button.clicked.connect(lambda: self.remove_step())
        self.up_button.clicked.connect(lambda: self.shift_step(-1))
        self.down_button.clicked.connect(lambda: self.shift_step(1))
        self.start_button.clicked.connect(lambda: self.execute_direct())
        self.pause_button.clicked.connect(lambda: self.runner.pause())
        self.resume_button.clicked.connect(lambda: self.runner.resume())
        self.stop_button.clicked.connect(lambda: self.runner.stop())
        self.table.itemChanged.connect(lambda *_: self.commandChanged.emit())
        self.table.itemSelectionChanged.connect(lambda *_: self.commandChanged.emit())
        self.commandChanged.connect(lambda: self.status.setText(self.preview_command()))
        self.add_step()
        self.status.setText(self.preview_command())

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def add_step(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QTableWidgetItem()
        enabled.setCheckState(Qt.CheckState.Checked)
        self.table.setItem(row, 0, enabled)
        self.table.setItem(row, 1, QTableWidgetItem("xdotool mousemove 100 100"))
        self.table.setItem(row, 2, QTableWidgetItem("0"))
        self.table.setItem(row, 3, QTableWidgetItem("1"))
        self.commandChanged.emit()

    def remove_step(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.commandChanged.emit()

    def shift_step(self, direction: int) -> None:
        row = self.table.currentRow()
        other = row + direction
        if row < 0 or other < 0 or other >= self.table.rowCount():
            return
        values = [self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount())]
        other_values = [self.table.item(other, col).text() if self.table.item(other, col) else "" for col in range(self.table.columnCount())]
        other_checks = self.table.item(other, 0).checkState() if self.table.item(other, 0) else Qt.CheckState.Unchecked
        row_checks = self.table.item(row, 0).checkState() if self.table.item(row, 0) else Qt.CheckState.Unchecked
        for col, value in enumerate(other_values):
            self.table.item(row, col).setText(value)
        self.table.item(row, 0).setCheckState(other_checks)
        for col, value in enumerate(values):
            self.table.item(other, col).setText(value)
        self.table.item(other, 0).setCheckState(row_checks)
        self.table.setCurrentCell(other, 0)
        self.commandChanged.emit()

    def steps(self) -> list[AutomationStep]:
        steps: list[AutomationStep] = []
        for row in range(self.table.rowCount()):
            enabled_item = self.table.item(row, 0)
            command_item = self.table.item(row, 1)
            delay_item = self.table.item(row, 2)
            repeat_item = self.table.item(row, 3)
            steps.append(
                AutomationStep(
                    command=(command_item.text() if command_item else "").strip(),
                    delay_ms=int(delay_item.text()) if delay_item and delay_item.text().isdigit() else 0,
                    repeat=max(int(repeat_item.text()), 1) if repeat_item and repeat_item.text().isdigit() else 1,
                    enabled=enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True,
                )
            )
        return steps

    def command_spec(self) -> CommandSpec | None:
        commands = [step.command for step in self.steps() if step.enabled]
        if not commands:
            return None
        return raw_command(commands[0])

    def preview_command(self) -> str:
        commands = [step.command for step in self.steps() if step.enabled]
        if not commands:
            return ""
        return " && ".join(commands)

    def execute_direct(self) -> bool:
        options = MacroRunOptions(
            repeat=self.repeat_spin.value(),
            loop_forever=self.loop_forever.isChecked(),
            random_delay_min_ms=self.random_min.value(),
            random_delay_max_ms=self.random_max.value(),
            stop_on_error=self.stop_on_error.isChecked(),
        )
        started = self.runner.start(self.steps(), options)
        if not started:
            QMessageBox.information(self, "Automation", "Automation is already running.")
        return started


class StructuredAutomationTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Enabled", "Action", "Command / Label", "Params", "Delay ms", "Repeat"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

        self.macro_name = QLineEdit("Untitled macro")
        self.repeat_spin = QSpinBox()
        self.repeat_spin.setRange(1, 9999)
        self.repeat_spin.setValue(1)
        self.loop_forever = QCheckBox("Loop forever")
        self.confirm_infinite = QCheckBox("Confirm infinite loops")
        self.confirm_infinite.setChecked(True)
        self.stop_on_error = QCheckBox("Stop on error")
        self.continue_on_timeout = QCheckBox("Continue on timeout")
        self.stop_on_window_loss = QCheckBox("Stop if target window vanishes")
        self.stop_on_window_loss.setChecked(True)

        self.delay_mode = QComboBox()
        self.delay_mode.addItems(["fixed", "random", "gaussian", "humanized"])
        self.fixed_delay = QSpinBox()
        self.fixed_delay.setRange(0, 600000)
        self.random_min = QSpinBox()
        self.random_min.setRange(0, 600000)
        self.random_max = QSpinBox()
        self.random_max.setRange(0, 600000)
        self.gaussian_mean = QSpinBox()
        self.gaussian_mean.setRange(0, 600000)
        self.gaussian_stdev = QSpinBox()
        self.gaussian_stdev.setRange(0, 600000)
        self.max_runtime = QSpinBox()
        self.max_runtime.setRange(0, 1440)
        self.max_failures = QSpinBox()
        self.max_failures.setRange(0, 99999)
        self.retry_count = QSpinBox()
        self.retry_count.setRange(1, 25)
        self.retry_count.setValue(3)
        self.retry_delay = QSpinBox()
        self.retry_delay.setRange(0, 5000)

        self.target_id = QLineEdit()
        self.target_title = QLineEdit()
        self.target_class = QLineEdit()
        self.target_regex = QCheckBox("Regex")
        for widget in [self.target_id, self.target_title, self.target_class]:
            widget.setReadOnly(True)
        self.target_regex.setEnabled(False)

        self.insert_combo = QComboBox()
        self.insert_combo.addItems([MACRO_ACTION_LABELS[action] for action in MACRO_ACTIONS])
        self.insert_button = QPushButton("Insert Action")
        self.add_button = QPushButton("Add Step")
        self.remove_button = QPushButton("Remove Step")
        self.duplicate_button = QPushButton("Duplicate")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        self.validate_button = QPushButton("Validate")
        self.copy_button = QPushButton("Copy")
        self.paste_button = QPushButton("Paste")
        self.cut_button = QPushButton("Cut")
        self.undo_button = QPushButton("Undo")
        self.redo_button = QPushButton("Redo")
        self.record_position_button = QPushButton("Record Position")
        self.record_button = QPushButton("Record Mouse")
        self.stop_record_button = QPushButton("Stop Recording")
        self.stop_record_button.setEnabled(False)
        self.record_button.setToolTip("Record mouse moves and clicks into the macro table.")
        self.stop_record_button.setToolTip("Stop the mouse recorder.")
        self.record_hint = QLabel("Use the recorder to capture mouse moves and clicks into the current macro.")
        self.record_hint.setWordWrap(True)
        self.recording_label = QLabel("Recorder idle")
        self.save_button = QPushButton("Save Macro")
        self.load_button = QPushButton("Load Macro")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        for button, tip in [
            (self.add_button, "Add a blank macro step."),
            (self.insert_button, "Insert a step using the selected action type."),
            (self.remove_button, "Delete the selected step."),
            (self.duplicate_button, "Duplicate the selected step."),
            (self.copy_button, "Copy selected steps as JSON."),
            (self.paste_button, "Paste steps from JSON in the clipboard."),
            (self.validate_button, "Validate the macro before running it."),
            (self.start_button, "Run the macro."),
            (self.pause_button, "Pause the running macro."),
            (self.resume_button, "Resume a paused macro."),
            (self.stop_button, "Stop the running macro."),
        ]:
            button.setToolTip(tip)

        self.status = QLabel("idle")
        self.progress = QProgressBar()
        self.current_cycle = QLabel("0 / 0")
        self.completed_actions = QLabel("0")
        self.current_action = QLabel("idle")
        self.macro_label = QLabel("Untitled macro")
        self.elapsed_label = QLabel("0s")
        self.average_label = QLabel("0s")
        self.remaining_label = QLabel("-")
        self.finish_label = QLabel("-")
        self.percent_label = QLabel("-")

        file_row = QHBoxLayout()
        for widget in [self.save_button, self.load_button, self.import_button, self.export_button]:
            file_row.addWidget(widget)
        edit_row = QHBoxLayout()
        for widget in [self.add_button, self.insert_combo, self.insert_button, self.remove_button, self.duplicate_button, self.copy_button, self.paste_button, self.cut_button, self.undo_button, self.redo_button, self.record_position_button, self.validate_button]:
            edit_row.addWidget(widget)
        run_row = QHBoxLayout()
        for widget in [self.start_button, self.pause_button, self.resume_button, self.stop_button]:
            run_row.addWidget(widget)

        macro_form = QFormLayout()
        macro_form.addRow("Macro name", self.macro_name)
        macro_form.addRow("Repeat", self.repeat_spin)
        macro_form.addRow("", self.loop_forever)
        macro_form.addRow("", self.confirm_infinite)
        macro_form.addRow("", self.stop_on_error)
        macro_form.addRow("", self.continue_on_timeout)
        macro_form.addRow("", self.stop_on_window_loss)
        macro_form.addRow("Delay mode", self.delay_mode)
        macro_form.addRow("Fixed delay ms", self.fixed_delay)
        macro_form.addRow("Random min ms", self.random_min)
        macro_form.addRow("Random max ms", self.random_max)
        macro_form.addRow("Gaussian mean ms", self.gaussian_mean)
        macro_form.addRow("Gaussian stdev ms", self.gaussian_stdev)
        macro_form.addRow("Max runtime minutes", self.max_runtime)
        macro_form.addRow("Max failures", self.max_failures)
        macro_form.addRow("Retries", self.retry_count)
        macro_form.addRow("Retry delay ms", self.retry_delay)
        macro_box = QGroupBox("Macro Settings")
        macro_box.setLayout(macro_form)

        target_form = QFormLayout()
        target_form.addRow("Target id", self.target_id)
        target_form.addRow("Target title", self.target_title)
        target_form.addRow("Target class", self.target_class)
        target_form.addRow("", self.target_regex)
        target_box = QGroupBox("Window Target")
        target_box.setLayout(target_form)

        progress_form = QGridLayout()
        progress_form.addWidget(QLabel("Macro"), 0, 0)
        progress_form.addWidget(self.macro_label, 0, 1)
        progress_form.addWidget(QLabel("Cycle"), 1, 0)
        progress_form.addWidget(self.current_cycle, 1, 1)
        progress_form.addWidget(QLabel("Completed actions"), 2, 0)
        progress_form.addWidget(self.completed_actions, 2, 1)
        progress_form.addWidget(QLabel("Current action"), 3, 0)
        progress_form.addWidget(self.current_action, 3, 1)
        progress_form.addWidget(QLabel("Elapsed"), 4, 0)
        progress_form.addWidget(self.elapsed_label, 4, 1)
        progress_form.addWidget(QLabel("Average cycle"), 5, 0)
        progress_form.addWidget(self.average_label, 5, 1)
        progress_form.addWidget(QLabel("Remaining"), 6, 0)
        progress_form.addWidget(self.remaining_label, 6, 1)
        progress_form.addWidget(QLabel("Finish"), 7, 0)
        progress_form.addWidget(self.finish_label, 7, 1)
        progress_form.addWidget(QLabel("Progress"), 8, 0)
        progress_form.addWidget(self.percent_label, 8, 1)
        progress_box = QGroupBox("Progress")
        progress_box.setLayout(progress_form)

        pixel_group = QGroupBox("Pixel Inspector")
        pixel_layout = QGridLayout(pixel_group)
        self.pixel_x_label = QLabel("0")
        self.pixel_y_label = QLabel("0")
        self.pixel_rgb_label = QLabel("0,0,0")
        self.pixel_hex_label = QLabel("#000000")
        self.pixel_preview = QLabel(" ")
        self.pixel_preview.setMinimumHeight(24)
        self.pixel_preview.setStyleSheet("border: 1px solid #999; background: #000000;")
        pixel_layout.addWidget(QLabel("X"), 0, 0)
        pixel_layout.addWidget(self.pixel_x_label, 0, 1)
        pixel_layout.addWidget(QLabel("Y"), 0, 2)
        pixel_layout.addWidget(self.pixel_y_label, 0, 3)
        pixel_layout.addWidget(QLabel("RGB"), 1, 0)
        pixel_layout.addWidget(self.pixel_rgb_label, 1, 1, 1, 3)
        pixel_layout.addWidget(QLabel("HEX"), 2, 0)
        pixel_layout.addWidget(self.pixel_hex_label, 2, 1, 1, 3)
        pixel_layout.addWidget(self.pixel_preview, 3, 0, 1, 4)
        self.pixel_timer = QTimer(self)
        self.pixel_timer.setInterval(250)
        self.pixel_timer.timeout.connect(self._update_pixel_inspector)
        self.pixel_timer.start()

        settings_widget = QWidget()
        settings_layout = QVBoxLayout(settings_widget)
        settings_layout.addWidget(target_box)
        settings_layout.addWidget(macro_box)
        settings_layout.addWidget(pixel_group)
        settings_layout.addWidget(self.record_hint)
        settings_layout.addWidget(self.record_button)
        settings_layout.addWidget(self.stop_record_button)
        settings_layout.addWidget(self.recording_label)
        settings_layout.addStretch(1)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidget(settings_widget)
        settings_scroll.setMinimumHeight(180)

        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.addWidget(self.table)
        editor_layout.addLayout(edit_row)
        editor_layout.addLayout(file_row)
        editor_layout.addLayout(run_row)
        editor_layout.addWidget(self.progress)
        editor_layout.addWidget(progress_box)
        editor_layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(settings_scroll)
        splitter.addWidget(editor_widget)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        self.table.setMinimumHeight(220)
        progress_box.setMinimumHeight(160)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.runner = MacroRunner(self)
        self.recorder = RecorderService(self)
        self._recorder_timer = QTimer(self)
        self._recorder_timer.setInterval(100)
        self._recorder_timer.timeout.connect(self._drain_recorder_events)
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []
        self._updating_from_history = False
        self._pending_recorded_steps: list[dict[str, Any]] = []
        self.runner.logMessage.connect(self._set_status)
        self.runner.stateChanged.connect(self.status.setText)
        self.runner.progressChanged.connect(self._update_progress)
        self.runner.failureCountChanged.connect(lambda count: self.status.setText(f"Failures: {count}"))
        self.recorder.stepRecorded.connect(self._append_recorded_step)
        self.recorder.eventsRecorded.connect(self._append_recorded_events)
        self.recorder.stateChanged.connect(self._update_recording_state)
        self.recorder.statusChanged.connect(self._update_recording_status)
        self.recorder.error.connect(lambda message: QMessageBox.warning(self, "Recorder", message))

        self.add_button.clicked.connect(lambda: self.add_step())
        self.insert_button.clicked.connect(lambda: self.add_step(action_type=self._selected_action_type()))
        self.remove_button.clicked.connect(self.remove_step)
        self.duplicate_button.clicked.connect(self.duplicate_step)
        self.up_button.clicked.connect(lambda: self.shift_step(-1))
        self.down_button.clicked.connect(lambda: self.shift_step(1))
        self.validate_button.clicked.connect(lambda: self.validate_macro(show_dialog=True))
        self.copy_button.clicked.connect(self.copy_selected_steps)
        self.paste_button.clicked.connect(self.paste_steps)
        self.cut_button.clicked.connect(self.cut_selected_steps)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.record_position_button.clicked.connect(self.record_position_into_step)
        self.record_button.clicked.connect(self.start_recording)
        self.stop_record_button.clicked.connect(self.stop_recording)
        self.save_button.clicked.connect(self.save_macro)
        self.load_button.clicked.connect(self.load_macro)
        self.import_button.clicked.connect(self.import_macro)
        self.export_button.clicked.connect(self.export_macro)
        self.start_button.clicked.connect(self.execute_direct)
        self.pause_button.clicked.connect(self.runner.pause)
        self.resume_button.clicked.connect(self.runner.resume)
        self.stop_button.clicked.connect(self.runner.stop)
        self.table.itemChanged.connect(self._handle_table_change)
        self.table.itemSelectionChanged.connect(lambda *_: self.commandChanged.emit())
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        self._recorder_timer.start()
        QShortcut(QKeySequence.StandardKey.Undo, self.table, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self.table, self.redo)
        QShortcut(QKeySequence.StandardKey.Cut, self.table, self.cut_selected_steps)
        QShortcut(QKeySequence.StandardKey.Copy, self.table, self.copy_selected_steps)
        QShortcut(QKeySequence.StandardKey.Paste, self.table, self.paste_steps)
        QShortcut(QKeySequence("Ctrl+D"), self.table, self.duplicate_step)
        QShortcut(QKeySequence("Delete"), self.table, self.remove_step)
        for widget in [self.macro_name, self.repeat_spin, self.loop_forever, self.confirm_infinite, self.stop_on_error, self.continue_on_timeout, self.stop_on_window_loss, self.delay_mode, self.fixed_delay, self.random_min, self.random_max, self.gaussian_mean, self.gaussian_stdev, self.max_runtime, self.max_failures, self.retry_count, self.retry_delay]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(lambda *_: self._handle_form_change())
            elif hasattr(widget, "currentTextChanged"):
                widget.currentTextChanged.connect(lambda *_: self._handle_form_change())
            elif hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(lambda *_: self._handle_form_change())
            elif hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(lambda *_: self._handle_form_change())
        self.commandChanged.connect(self._refresh_preview)
        self.add_step()
        self._push_history()
        self._refresh_preview()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    def _selected_action_type(self) -> str:
        index = self.insert_combo.currentIndex()
        if 0 <= index < len(MACRO_ACTIONS):
            return MACRO_ACTIONS[index]
        return MacroActionKind.RUN_SHELL.value

    def _push_history(self) -> None:
        if self._updating_from_history:
            return
        snapshot = self._snapshot_state()
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > 50:
            self._undo_stack = self._undo_stack[-50:]
        self._redo_stack.clear()

    def _snapshot_state(self) -> dict[str, Any]:
        return {
            "name": self.macro_name.text().strip() or "Untitled macro",
            "target_window": asdict(self.target_window()),
            "options": {
                "repeat": self.repeat_spin.value(),
                "loop_forever": self.loop_forever.isChecked(),
                "confirm_infinite_loops": self.confirm_infinite.isChecked(),
                "stop_on_error": self.stop_on_error.isChecked(),
                "continue_on_timeout": self.continue_on_timeout.isChecked(),
                "stop_on_window_loss": self.stop_on_window_loss.isChecked(),
                "delay_mode": self.delay_mode.currentText(),
                "fixed_delay_ms": self.fixed_delay.value(),
                "random_delay_min_ms": self.random_min.value(),
                "random_delay_max_ms": self.random_max.value(),
                "gaussian_mean_ms": self.gaussian_mean.value(),
                "gaussian_stdev_ms": self.gaussian_stdev.value(),
                "max_runtime_minutes": self.max_runtime.value(),
                "max_failures": self.max_failures.value(),
                "retry_count": self.retry_count.value(),
                "retry_delay_ms": self.retry_delay.value(),
            },
            "actions": [
                {
                    "command": step.command,
                    "action_type": step.action_type,
                    "params": step.params,
                    "delay_ms": step.delay_ms,
                    "repeat": step.repeat,
                    "enabled": step.enabled,
                    "label": step.label,
                }
                for step in self.steps()
            ],
        }

    def _restore_state(self, snapshot: dict[str, Any]) -> None:
        self._updating_from_history = True
        self.table.setRowCount(0)
        self.macro_name.setText(str(snapshot.get("name", "Untitled macro")))
        self.set_target_window(snapshot.get("target_window", {}))
        options = snapshot.get("options", {})
        if isinstance(options, dict):
            self.repeat_spin.setValue(_safe_int(str(options.get("repeat", 1)), 1))
            self.loop_forever.setChecked(bool(options.get("loop_forever", False)))
            self.confirm_infinite.setChecked(bool(options.get("confirm_infinite_loops", True)))
            self.stop_on_error.setChecked(bool(options.get("stop_on_error", False)))
            self.continue_on_timeout.setChecked(bool(options.get("continue_on_timeout", False)))
            self.stop_on_window_loss.setChecked(bool(options.get("stop_on_window_loss", True)))
            self.delay_mode.setCurrentText(str(options.get("delay_mode", "fixed")))
            self.fixed_delay.setValue(_safe_int(str(options.get("fixed_delay_ms", 0)), 0))
            self.random_min.setValue(_safe_int(str(options.get("random_delay_min_ms", 0)), 0))
            self.random_max.setValue(_safe_int(str(options.get("random_delay_max_ms", 0)), 0))
            self.gaussian_mean.setValue(_safe_int(str(options.get("gaussian_mean_ms", 0)), 0))
            self.gaussian_stdev.setValue(_safe_int(str(options.get("gaussian_stdev_ms", 0)), 0))
            self.max_runtime.setValue(_safe_int(str(options.get("max_runtime_minutes", 0)), 0))
            self.max_failures.setValue(_safe_int(str(options.get("max_failures", 0)), 0))
            self.retry_count.setValue(max(_safe_int(str(options.get("retry_count", 3)), 3), 1))
            self.retry_delay.setValue(_safe_int(str(options.get("retry_delay_ms", 150)), 150))
        for entry in snapshot.get("actions", []):
            if isinstance(entry, dict):
                self.add_step(
                    AutomationStep(
                        command=str(entry.get("command", "")),
                        action_type=str(entry.get("action_type", MacroActionKind.RUN_SHELL.value)),
                        params=dict(entry.get("params", {})) if isinstance(entry.get("params", {}), dict) else {},
                        delay_ms=_safe_int(str(entry.get("delay_ms", 0)), 0),
                        repeat=max(_safe_int(str(entry.get("repeat", 1)), 1), 1),
                        enabled=bool(entry.get("enabled", True)),
                        label=str(entry.get("label", "")),
                    )
                )
        self._updating_from_history = False
        self.commandChanged.emit()

    def _handle_table_change(self, *_args: Any) -> None:
        if self._updating_from_history:
            return
        self._push_history()
        self.commandChanged.emit()

    def _handle_form_change(self) -> None:
        if self._updating_from_history:
            return
        self._push_history()
        self.commandChanged.emit()

    def undo(self) -> None:
        if len(self._undo_stack) <= 1:
            return
        current = self._undo_stack.pop()
        previous = self._undo_stack[-1]
        self._redo_stack.append(current)
        self._restore_state(previous)
        self.status.setText("Undo")

    def redo(self) -> None:
        if not self._redo_stack:
            return
        next_state = self._redo_stack.pop()
        self._undo_stack.append(next_state)
        self._restore_state(next_state)
        self.status.setText("Redo")

    def _update_pixel_inspector(self) -> None:
        try:
            inspector = X11Inspector()
        except Exception as exc:  # pragma: no cover - environment-specific
            self.pixel_x_label.setText("-")
            self.pixel_y_label.setText("-")
            self.pixel_rgb_label.setText(str(exc))
            self.pixel_hex_label.setText("-")
            self.pixel_preview.setStyleSheet("border: 1px solid #999; background: #222;")
            return
        try:
            pos = QCursor.pos()
            self.pixel_x_label.setText(str(pos.x()))
            self.pixel_y_label.setText(str(pos.y()))
            rgb = inspector.pixel_rgb(pos.x(), pos.y())
            self.pixel_rgb_label.setText(f"{rgb[0]}, {rgb[1]}, {rgb[2]}")
            hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
            self.pixel_hex_label.setText(hex_color)
            self.pixel_preview.setStyleSheet(f"border: 1px solid #999; background: {hex_color};")
        except Exception as exc:  # pragma: no cover - environment-specific
            self.pixel_rgb_label.setText(str(exc))
        finally:
            inspector.close()

    def _action_combo(self, action_type: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems([MACRO_ACTION_LABELS[action] for action in MACRO_ACTIONS])
        combo.setCurrentIndex(MACRO_ACTIONS.index(action_type) if action_type in MACRO_ACTIONS else 0)
        combo.currentIndexChanged.connect(lambda *_: self._handle_form_change())
        return combo

    def _default_template(self, action_type: str) -> tuple[str, dict[str, Any], str]:
        templates: dict[str, tuple[str, dict[str, Any], str]] = {
            MacroActionKind.RUN_SHELL.value: ("xdotool mousemove 100 100", {"command": "xdotool mousemove 100 100"}, "Shell command"),
            MacroActionKind.RUN_PYTHON.value: ("", {"script": "print('hello')"}, "Python script"),
            MacroActionKind.MOUSE_MOVE.value: ("", {"x": 100, "y": 100, "movement_style": "smooth", "bezier_steps": 16}, "Mouse move"),
            MacroActionKind.CLICK.value: ("", {"button": 1, "clicks": 1}, "Click"),
            MacroActionKind.DOUBLE_CLICK.value: ("", {"button": 1, "clicks": 2}, "Double click"),
            MacroActionKind.RIGHT_CLICK.value: ("", {"button": 3, "clicks": 1}, "Right click"),
            MacroActionKind.MIDDLE_CLICK.value: ("", {"button": 2, "clicks": 1}, "Middle click"),
            MacroActionKind.MOUSE_DOWN.value: ("", {"button": 1}, "Mouse down"),
            MacroActionKind.MOUSE_UP.value: ("", {"button": 1}, "Mouse up"),
            MacroActionKind.DRAG.value: ("", {"start_x": 100, "start_y": 100, "end_x": 300, "end_y": 300, "button": 1, "bezier_steps": 16}, "Drag"),
            MacroActionKind.SCROLL.value: ("", {"direction": "up", "amount": 1}, "Scroll"),
            MacroActionKind.KEY_PRESS.value: ("", {"key": "ctrl+s", "repeat": 1, "delay_ms": 0}, "Key press"),
            MacroActionKind.KEY_DOWN.value: ("", {"key": "ctrl"}, "Key down"),
            MacroActionKind.KEY_UP.value: ("", {"key": "ctrl"}, "Key up"),
            MacroActionKind.TEXT.value: ("", {"text": "Hello world", "delay_ms": 0, "clearmodifiers": False}, "Text typing"),
            MacroActionKind.WAIT.value: ("", {"timeout_ms": 1000}, "Wait"),
            MacroActionKind.WAIT_FOR_PIXEL.value: ("", {"x": 100, "y": 100, "color": "#ffffff", "tolerance": 10, "poll_interval_ms": 100, "timeout_ms": 10000, "continue_on_timeout": False}, "Wait for pixel"),
            MacroActionKind.WAIT_FOR_WINDOW.value: ("", {"title": "", "class": "", "regex": "", "timeout_ms": 10000, "continue_on_timeout": False}, "Wait for window"),
            MacroActionKind.COMMENT.value: ("Comment", {"text": ""}, "Comment"),
            MacroActionKind.LABEL.value: ("Label", {"label": "start"}, "Label"),
            MacroActionKind.GOTO_LABEL.value: ("", {"label": "start"}, "Goto label"),
            MacroActionKind.CONDITIONAL_JUMP.value: ("", {"condition": "", "true_label": "", "false_label": ""}, "Conditional jump"),
        }
        return templates.get(action_type, templates[MacroActionKind.RUN_SHELL.value])

    def add_step(self, step: AutomationStep | None = None, action_type: str | None = None) -> None:
        action = (step.action_type if step is not None else action_type) or MacroActionKind.RUN_SHELL.value
        command, params, label = self._default_template(action)
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QTableWidgetItem("")
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled.setCheckState(Qt.CheckState.Checked if (step.enabled if step is not None else True) else Qt.CheckState.Unchecked)
        self.table.setItem(row, 0, enabled)
        self.table.setCellWidget(row, 1, self._action_combo(action))
        command_item = QTableWidgetItem(step.command if step is not None else command)
        command_item.setData(Qt.ItemDataRole.UserRole, step.label if step is not None else label)
        self.table.setItem(row, 2, command_item)
        self.table.setItem(row, 3, QTableWidgetItem(_json_text(step.params if step is not None else params)))
        self.table.setItem(row, 4, QTableWidgetItem(str(step.delay_ms if step is not None else 0)))
        self.table.setItem(row, 5, QTableWidgetItem(str(step.repeat if step is not None else 1)))
        self._push_history()
        self.commandChanged.emit()

    def _current_action_type(self, row: int) -> str:
        widget = self.table.cellWidget(row, 1)
        if isinstance(widget, QComboBox):
            index = widget.currentIndex()
            if 0 <= index < len(MACRO_ACTIONS):
                return MACRO_ACTIONS[index]
        return MacroActionKind.RUN_SHELL.value

    def _parse_params(self, text: str, *, strict: bool = False) -> dict[str, Any]:
        if not text.strip():
            return {}
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("Params must be a JSON object.")
            return parsed
        except Exception:
            if strict:
                raise
            return {}

    def step_at(self, row: int) -> AutomationStep:
        enabled = self.table.item(row, 0).checkState() == Qt.CheckState.Checked if self.table.item(row, 0) else True
        command_item = self.table.item(row, 2)
        params_item = self.table.item(row, 3)
        delay_item = self.table.item(row, 4)
        repeat_item = self.table.item(row, 5)
        return AutomationStep(
            command=command_item.text().strip() if command_item else "",
            action_type=self._current_action_type(row),
            params=self._parse_params(params_item.text()) if params_item else {},
            delay_ms=_safe_int(delay_item.text(), 0) if delay_item else 0,
            repeat=max(_safe_int(repeat_item.text(), 1), 1) if repeat_item else 1,
            enabled=enabled,
            label=str(command_item.data(Qt.ItemDataRole.UserRole) or "") if command_item else "",
        )

    def steps(self) -> list[AutomationStep]:
        return [self.step_at(row) for row in range(self.table.rowCount())]

    def _write_step(self, row: int, step: AutomationStep) -> None:
        self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if step.enabled else Qt.CheckState.Unchecked)
        widget = self.table.cellWidget(row, 1)
        if isinstance(widget, QComboBox):
            widget.setCurrentIndex(MACRO_ACTIONS.index(step.action_type) if step.action_type in MACRO_ACTIONS else 0)
        self.table.item(row, 2).setText(step.command)
        self.table.item(row, 2).setData(Qt.ItemDataRole.UserRole, step.label)
        self.table.item(row, 3).setText(_json_text(step.params))
        self.table.item(row, 4).setText(str(step.delay_ms))
        self.table.item(row, 5).setText(str(step.repeat))

    def remove_step(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self._push_history()
            self.commandChanged.emit()

    def duplicate_step(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.add_step(self.step_at(row))

    def shift_step(self, direction: int) -> None:
        row = self.table.currentRow()
        other = row + direction
        if row < 0 or other < 0 or other >= self.table.rowCount():
            return
        current = self.step_at(row)
        swap = self.step_at(other)
        self._write_step(row, swap)
        self._write_step(other, current)
        self.table.setCurrentCell(other, 0)
        self._push_history()
        self.commandChanged.emit()

    def _validate_step(self, step: AutomationStep) -> list[str]:
        errors: list[str] = []
        params = step.params or {}
        if step.delay_ms < 0:
            errors.append("Delay cannot be negative.")
        if step.repeat < 1:
            errors.append("Repeat must be at least 1.")
        if step.action_type == MacroActionKind.WAIT_FOR_PIXEL.value:
            try:
                parse_color(str(params.get("color", "#000000")))
            except Exception as exc:
                errors.append(str(exc))
            for key in ["x", "y", "tolerance", "poll_interval_ms", "timeout_ms"]:
                if key not in params:
                    errors.append(f"Missing {key} for wait_for_pixel.")
        if step.action_type == MacroActionKind.WAIT_FOR_WINDOW.value and not any(_textish(params.get(key, "")) for key in ["title", "class", "wm_class", "regex"]):
            errors.append("Wait for window needs a title, class, or regex.")
        if step.action_type == MacroActionKind.GOTO_LABEL.value and not str(params.get("label", step.command)).strip():
            errors.append("Goto label needs a label target.")
        if step.action_type == MacroActionKind.LABEL.value and not str(step.label or params.get("label", step.command)).strip():
            errors.append("Label needs a name.")
        return errors

    def validate_macro(self, show_dialog: bool = False) -> list[str]:
        errors: list[str] = []
        for row_index in range(self.table.rowCount()):
            params_item = self.table.item(row_index, 3)
            if params_item is not None:
                try:
                    self._parse_params(params_item.text(), strict=True)
                except Exception as exc:
                    errors.append(f"Row {row_index + 1}: invalid params JSON: {exc}")
            step = self.step_at(row_index)
            for error in self._validate_step(step):
                errors.append(f"Row {row_index + 1}: {error}")
        if show_dialog:
            if errors:
                QMessageBox.warning(self, "Macro Validation", "\n".join(errors))
            else:
                QMessageBox.information(self, "Macro Validation", "No validation errors were found.")
        return errors

    def _macro_options(self) -> MacroRunOptions:
        target = self.target_window()
        return MacroRunOptions(
            repeat=self.repeat_spin.value(),
            loop_forever=self.loop_forever.isChecked(),
            stop_on_error=self.stop_on_error.isChecked(),
            delay_mode=self.delay_mode.currentText(),
            fixed_delay_ms=self.fixed_delay.value(),
            random_delay_min_ms=self.random_min.value(),
            random_delay_max_ms=self.random_max.value(),
            gaussian_mean_ms=self.gaussian_mean.value(),
            gaussian_stdev_ms=self.gaussian_stdev.value(),
            max_runtime_minutes=self.max_runtime.value(),
            max_failures=self.max_failures.value(),
            retry_count=self.retry_count.value(),
            retry_delay_ms=self.retry_delay.value(),
            continue_on_timeout=self.continue_on_timeout.isChecked(),
            confirm_infinite_loops=self.confirm_infinite.isChecked(),
            target_window=target if any([target.window_id, target.title, target.wm_class]) else None,
            stop_on_window_loss=self.stop_on_window_loss.isChecked(),
            macro_name=self.macro_name.text().strip() or "Untitled macro",
        )

    def target_window(self) -> WindowTarget:
        return WindowTarget(
            window_id=self.target_id.text().strip(),
            title=self.target_title.text().strip(),
            wm_class=self.target_class.text().strip(),
            regex=self.target_regex.isChecked(),
        )

    def set_target_window(self, target: dict[str, Any]) -> None:
        self.target_id.setText(str(target.get("window_id", "")))
        self.target_title.setText(str(target.get("title", "")))
        self.target_class.setText(str(target.get("wm_class", "")))
        self.target_regex.setChecked(bool(target.get("regex", False)))

    def set_progress(self, payload: dict[str, Any]) -> None:
        cycle = int(payload.get("cycle", 0))
        total_cycles = int(payload.get("total_cycles", 0))
        completed = int(payload.get("completed_actions", 0))
        current_action = str(payload.get("current_action", "idle"))
        macro_name = str(payload.get("macro_name", self.macro_name.text()))
        elapsed = float(payload.get("elapsed_seconds", 0.0))
        average = float(payload.get("average_cycle_seconds", 0.0))
        remaining = payload.get("remaining_seconds")
        finish = str(payload.get("finish_time", "-"))
        percent = payload.get("percent")
        self.current_cycle.setText(f"{cycle} / {total_cycles}" if total_cycles else str(cycle))
        self.completed_actions.setText(str(completed))
        self.current_action.setText(current_action)
        self.macro_label.setText(macro_name)
        self.elapsed_label.setText(self._format_seconds(elapsed))
        self.average_label.setText(self._format_seconds(average))
        self.remaining_label.setText(self._format_seconds(float(remaining))) if remaining is not None else self.remaining_label.setText("-")
        self.finish_label.setText(finish)
        self.percent_label.setText(f"{percent:.1f}%" if isinstance(percent, (int, float)) else "-")
        if isinstance(percent, (int, float)):
            self.progress.setRange(0, 100)
            self.progress.setValue(int(percent))
        else:
            self.progress.setRange(0, 0)

    def _update_progress(self, payload: object) -> None:
        if isinstance(payload, dict):
            self.set_progress(payload)

    def preview_command(self) -> str:
        enabled = len([step for step in self.steps() if step.enabled])
        return f"Macro {self.macro_name.text().strip() or 'Untitled macro'}: {enabled} enabled actions"

    def command_spec(self) -> CommandSpec | None:
        enabled = [step for step in self.steps() if step.enabled and step.command]
        if not enabled:
            return None
        return raw_command(enabled[0].command)

    def _refresh_preview(self) -> None:
        self.status.setText(self.preview_command())
        self.macro_label.setText(self.macro_name.text().strip() or "Untitled macro")

    def _selected_rows(self) -> list[int]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return rows

    def _show_table_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Add Step", self.add_step)
        menu.addAction("Insert Selected", lambda: self.add_step(action_type=self._selected_action_type()))
        menu.addAction("Duplicate", self.duplicate_step)
        menu.addAction("Copy", self.copy_selected_steps)
        menu.addAction("Cut", self.cut_selected_steps)
        menu.addAction("Paste", self.paste_steps)
        menu.addSeparator()
        menu.addAction("Enable", self.enable_selected_steps)
        menu.addAction("Disable", self.disable_selected_steps)
        menu.addSeparator()
        menu.addAction("Remove", self.remove_step)
        menu.addAction("Move Up", lambda: self.shift_step(-1))
        menu.addAction("Move Down", lambda: self.shift_step(1))
        menu.addSeparator()
        menu.addAction("Undo", self.undo)
        menu.addAction("Redo", self.redo)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def copy_selected_steps(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        payload = [asdict(self.step_at(row)) for row in rows]
        QApplication.clipboard().setText(json.dumps(payload, indent=2, ensure_ascii=False))
        self.status.setText("Copied selected steps")

    def cut_selected_steps(self) -> None:
        self.copy_selected_steps()
        rows = self._selected_rows()
        if not rows:
            return
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
        self._push_history()
        self.commandChanged.emit()

    def enable_selected_steps(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked)
        self._push_history()
        self.commandChanged.emit()

    def disable_selected_steps(self) -> None:
        rows = self._selected_rows()
        if not rows:
            return
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._push_history()
        self.commandChanged.emit()

    def paste_steps(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        try:
            data = json.loads(text)
        except Exception as exc:
            QMessageBox.warning(self, "Paste", f"Clipboard does not contain valid JSON: {exc}")
            return
        items = data if isinstance(data, list) else [data]
        inserted = 0
        for entry in items:
            if not isinstance(entry, dict):
                continue
            try:
                self.add_step(
                    AutomationStep(
                        command=str(entry.get("command", "")),
                        action_type=str(entry.get("action_type", MacroActionKind.RUN_SHELL.value)),
                        params=dict(entry.get("params", {})) if isinstance(entry.get("params", {}), dict) else {},
                        delay_ms=_safe_int(str(entry.get("delay_ms", 0)), 0),
                        repeat=max(_safe_int(str(entry.get("repeat", 1)), 1), 1),
                        enabled=bool(entry.get("enabled", True)),
                        label=str(entry.get("label", "")),
                    )
                )
                inserted += 1
            except Exception:
                continue
        if inserted:
            self._push_history()
            self.commandChanged.emit()
            self.status.setText(f"Pasted {inserted} step(s)")

    def record_position_into_step(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.add_step()
            row = self.table.rowCount() - 1
        pos = QCursor.pos()
        step = self.step_at(row)
        params = dict(step.params or {})
        params["x"] = pos.x()
        params["y"] = pos.y()
        updated_step = AutomationStep(
            command=step.command,
            action_type=step.action_type,
            params=params,
            delay_ms=step.delay_ms,
            repeat=step.repeat,
            enabled=step.enabled,
            label=step.label,
        )
        self._write_step(row, updated_step)
        self._push_history()
        self.commandChanged.emit()
        self.status.setText(f"Recorded position {pos.x()}, {pos.y()}")

    def start_recording(self) -> None:
        if self.recorder.start():
            self.record_button.setEnabled(False)
            self.stop_record_button.setEnabled(True)
            self.status.setText("Recording...")

    def stop_recording(self) -> None:
        self.recorder.stop()
        self.record_button.setEnabled(True)
        self.stop_record_button.setEnabled(False)
        self.status.setText("Recording stopped")

    def _update_recording_state(self, state: str) -> None:
        self.recording_label.setText(f"Recorder {state}")

    def _update_recording_status(self, text: str) -> None:
        self.record_hint.setText(text)
        self.status.setText(text)

    def _append_recorded_step(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._pending_recorded_steps.append(payload)

    def _append_recorded_events(self, payload: object) -> None:
        if not isinstance(payload, list):
            return
        self._pending_recorded_steps.extend(payload)

    def _drain_recorder_events(self) -> None:
        if not self._pending_recorded_steps:
            return
        pending = self._pending_recorded_steps
        self._pending_recorded_steps = []
        for payload in pending:
            if not isinstance(payload, dict):
                continue
            action_type = str(payload.get("action_type", MacroActionKind.MOUSE_MOVE.value))
            params = payload.get("params", {})
            if not isinstance(params, dict):
                params = {}
            step = AutomationStep(
                command=str(payload.get("command", "")),
                action_type=action_type,
                params=params,
                delay_ms=_safe_int(str(payload.get("delay_ms", 0)), 0),
                repeat=max(_safe_int(str(payload.get("repeat", 1)), 1), 1),
                enabled=bool(payload.get("enabled", True)),
                label=str(payload.get("label", "")),
            )
            self.add_step(step)
        self.status.setText(f"Recorded {len(pending)} event(s)")

    def execute_direct(self) -> bool:
        errors = self.validate_macro(show_dialog=False)
        if errors:
            QMessageBox.warning(self, "Automation", "\n".join(errors))
            return False
        started = self.runner.start(self.steps(), self._macro_options())
        if not started:
            QMessageBox.information(self, "Automation", "Automation is already running.")
        return started

    def _macro_document(self) -> dict[str, Any]:
        return {
            "version": 2,
            "name": self.macro_name.text().strip() or "Untitled macro",
            "target_window": asdict(self.target_window()),
            "options": {
                "repeat": self.repeat_spin.value(),
                "loop_forever": self.loop_forever.isChecked(),
                "confirm_infinite_loops": self.confirm_infinite.isChecked(),
                "stop_on_error": self.stop_on_error.isChecked(),
                "continue_on_timeout": self.continue_on_timeout.isChecked(),
                "stop_on_window_loss": self.stop_on_window_loss.isChecked(),
                "delay_mode": self.delay_mode.currentText(),
                "fixed_delay_ms": self.fixed_delay.value(),
                "random_delay_min_ms": self.random_min.value(),
                "random_delay_max_ms": self.random_max.value(),
                "gaussian_mean_ms": self.gaussian_mean.value(),
                "gaussian_stdev_ms": self.gaussian_stdev.value(),
                "max_runtime_minutes": self.max_runtime.value(),
                "max_failures": self.max_failures.value(),
                "retry_count": self.retry_count.value(),
                "retry_delay_ms": self.retry_delay.value(),
            },
            "actions": [
                {
                    "command": step.command,
                    "action_type": step.action_type,
                    "params": step.params,
                    "delay_ms": step.delay_ms,
                    "repeat": step.repeat,
                    "enabled": step.enabled,
                    "label": step.label,
                }
                for step in self.steps()
            ],
        }

    def _load_macro_data(self, data: dict[str, Any], replace: bool = True) -> None:
        if not isinstance(data, dict):
            raise ValueError("Macro data must be a JSON object.")
        if replace:
            self.table.setRowCount(0)
        if isinstance(data.get("name"), str):
            self.macro_name.setText(data["name"])
        if isinstance(data.get("target_window"), dict):
            self.set_target_window(data["target_window"])
        options = data.get("options", {})
        if isinstance(options, dict):
            self.repeat_spin.setValue(_safe_int(str(options.get("repeat", 1)), 1))
            self.loop_forever.setChecked(bool(options.get("loop_forever", False)))
            self.confirm_infinite.setChecked(bool(options.get("confirm_infinite_loops", True)))
            self.stop_on_error.setChecked(bool(options.get("stop_on_error", False)))
            self.continue_on_timeout.setChecked(bool(options.get("continue_on_timeout", False)))
            self.stop_on_window_loss.setChecked(bool(options.get("stop_on_window_loss", True)))
            self.delay_mode.setCurrentText(str(options.get("delay_mode", "fixed")))
            self.fixed_delay.setValue(_safe_int(str(options.get("fixed_delay_ms", 0)), 0))
            self.random_min.setValue(_safe_int(str(options.get("random_delay_min_ms", 0)), 0))
            self.random_max.setValue(_safe_int(str(options.get("random_delay_max_ms", 0)), 0))
            self.gaussian_mean.setValue(_safe_int(str(options.get("gaussian_mean_ms", 0)), 0))
            self.gaussian_stdev.setValue(_safe_int(str(options.get("gaussian_stdev_ms", 0)), 0))
            self.max_runtime.setValue(_safe_int(str(options.get("max_runtime_minutes", 0)), 0))
            self.max_failures.setValue(_safe_int(str(options.get("max_failures", 0)), 0))
            self.retry_count.setValue(max(_safe_int(str(options.get("retry_count", 3)), 3), 1))
            self.retry_delay.setValue(_safe_int(str(options.get("retry_delay_ms", 150)), 150))
        actions = data.get("actions", [])
        if isinstance(actions, list):
            for entry in actions:
                if isinstance(entry, dict):
                    self.add_step(
                        AutomationStep(
                            command=str(entry.get("command", "")),
                            action_type=str(entry.get("action_type", MacroActionKind.RUN_SHELL.value)),
                            params=dict(entry.get("params", {})) if isinstance(entry.get("params", {}), dict) else {},
                            delay_ms=_safe_int(str(entry.get("delay_ms", 0)), 0),
                            repeat=max(_safe_int(str(entry.get("repeat", 1)), 1), 1),
                            enabled=bool(entry.get("enabled", True)),
                            label=str(entry.get("label", "")),
                        )
                    )
        self.commandChanged.emit()

    def save_macro(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save macro", str(Path.home() / "xdotool-macro.json"), "JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self._macro_document(), indent=2, ensure_ascii=False), encoding="utf-8")

    def load_macro(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load macro", str(Path.home()), "JSON Files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = {"actions": data}
            self._load_macro_data(data, replace=True)
        except Exception as exc:
            QMessageBox.warning(self, "Automation", f"Unable to load macro: {exc}")

    def import_macro(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import macro", str(Path.home()), "JSON Files (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, list):
                data = {"actions": data}
            self._load_macro_data(data, replace=False)
        except Exception as exc:
            QMessageBox.warning(self, "Automation", f"Unable to import macro: {exc}")

    def export_macro(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export macro", str(Path.home() / "xdotool-macro.json"), "JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self._macro_document(), indent=2, ensure_ascii=False), encoding="utf-8")


class AutoClickerTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.button_combo = QComboBox()
        self.button_combo.addItems(["1", "2", "3", "4", "5"])
        self.cps_spin = QDoubleSpinBox()
        self.cps_spin.setRange(0.1, 999.0)
        self.cps_spin.setValue(5.0)
        self.random_cps = QCheckBox("Random CPS")
        self.loop_forever = QCheckBox("Loop forever")
        self.loops_spin = QSpinBox()
        self.loops_spin.setRange(1, 999999)
        self.loops_spin.setValue(1)
        self.start_delay = QSpinBox()
        self.start_delay.setRange(0, 600000)
        self.stop_delay = QSpinBox()
        self.stop_delay.setRange(0, 600000)
        self.total_clicks = QSpinBox()
        self.total_clicks.setRange(0, 999999)
        self.total_clicks.setValue(0)
        self.order_combo = QComboBox()
        self.order_combo.addItems([item.value for item in CommandOrder])
        self.movement_style = QComboBox()
        self.movement_style.addItems(["instant", "smooth", "bezier"])
        self.ellipse_x_spin = QSpinBox()
        self.ellipse_x_spin.setRange(0, 10000)
        self.ellipse_y_spin = QSpinBox()
        self.ellipse_y_spin.setRange(0, 10000)
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(0, 10000)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(0, 10000)
        self.bezier_steps = QSpinBox()
        self.bezier_steps.setRange(2, 100)
        self.bezier_steps.setValue(16)
        self.counter = QLabel("0")
        self.status = QLabel("idle")
        self._target_window: dict[str, Any] = {}
        self.positions = QTableWidget(0, 12)
        self.positions.setHorizontalHeaderLabels([
            "Enabled",
            "Name",
            "X",
            "Y",
            "Button",
            "Clicks",
            "Delay ms",
            "Interval ms",
            "Order",
            "Priority",
            "Radius",
            "Jitter",
        ])
        self.positions.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        self.dup_button = QPushButton("Duplicate")
        self.up_button = QPushButton("Up")
        self.down_button = QPushButton("Down")
        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.stop_button = QPushButton("Stop")
        self.capture_button = QPushButton("Record Position")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        self.save_button = QPushButton("Save")
        self.load_button = QPushButton("Load")
        form = QFormLayout()
        form.addRow("Button", self.button_combo)
        form.addRow("Clicks/sec", self.cps_spin)
        form.addRow("", self.random_cps)
        form.addRow("", self.loop_forever)
        form.addRow("Loops", self.loops_spin)
        form.addRow("Start delay ms", self.start_delay)
        form.addRow("Stop delay ms", self.stop_delay)
        form.addRow("Total clicks", self.total_clicks)
        form.addRow("Order", self.order_combo)
        form.addRow("Movement style", self.movement_style)
        form.addRow("Ellipse radius X", self.ellipse_x_spin)
        form.addRow("Ellipse radius Y", self.ellipse_y_spin)
        form.addRow("Offset radius X", self.offset_x_spin)
        form.addRow("Offset radius Y", self.offset_y_spin)
        form.addRow("Bezier steps", self.bezier_steps)
        top = QWidget()
        top.setLayout(form)
        buttons = QHBoxLayout()
        for widget in [self.add_button, self.remove_button, self.dup_button, self.up_button, self.down_button, self.capture_button, self.import_button, self.export_button, self.save_button, self.load_button]:
            buttons.addWidget(widget)
        runner_buttons = QHBoxLayout()
        for widget in [self.start_button, self.pause_button, self.resume_button, self.stop_button]:
            runner_buttons.addWidget(widget)
        layout = QVBoxLayout(self)
        layout.addWidget(top)
        layout.addWidget(self.positions)
        layout.addLayout(buttons)
        layout.addLayout(runner_buttons)
        layout.addWidget(QLabel("Clicks"))
        layout.addWidget(self.counter)
        layout.addWidget(self.status)
        self.controller = AutoClickerController(self)
        self.controller.counterChanged.connect(self.counter.setText)
        self.controller.stateChanged.connect(self.status.setText)
        self.controller.logMessage.connect(self.status.setText)
        self.add_button.clicked.connect(lambda: self.add_position())
        self.remove_button.clicked.connect(lambda: self.remove_position())
        self.dup_button.clicked.connect(lambda: self.duplicate_position())
        self.up_button.clicked.connect(lambda: self.shift_position(-1))
        self.down_button.clicked.connect(lambda: self.shift_position(1))
        self.capture_button.clicked.connect(lambda: self.capture_position())
        self.start_button.clicked.connect(lambda: self.execute_direct())
        self.pause_button.clicked.connect(lambda: self.controller.pause())
        self.resume_button.clicked.connect(lambda: self.controller.resume())
        self.stop_button.clicked.connect(lambda: self.controller.stop())
        self.import_button.clicked.connect(lambda: self.import_positions())
        self.export_button.clicked.connect(lambda: self.export_positions())
        self.save_button.clicked.connect(lambda: self.save_profile())
        self.load_button.clicked.connect(lambda: self.load_profile())
        self.positions.itemChanged.connect(lambda *_: self.commandChanged.emit())
        self.positions.itemSelectionChanged.connect(lambda *_: self.commandChanged.emit())
        self.commandChanged.connect(lambda: self.status.setText(self.preview_command()))
        self.add_position()
        self.status.setText(self.preview_command())

    def add_position(self, position: ClickPosition | None = None) -> None:
        pos = position or ClickPosition(name=f"Position {self.positions.rowCount() + 1}", x=100, y=100)
        row = self.positions.rowCount()
        self.positions.insertRow(row)
        enabled = QTableWidgetItem("")
        enabled.setFlags(enabled.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        enabled.setCheckState(Qt.CheckState.Checked if pos.enabled else Qt.CheckState.Unchecked)
        self.positions.setItem(row, 0, enabled)
        for col, value in enumerate([pos.name, pos.x, pos.y, pos.button, pos.clicks, pos.delay_ms, pos.interval_ms, pos.order, pos.priority, pos.random_radius, pos.jitter_ms], start=1):
            self.positions.setItem(row, col, QTableWidgetItem(str(value)))
        self.commandChanged.emit()

    def remove_position(self) -> None:
        row = self.positions.currentRow()
        if row >= 0:
            self.positions.removeRow(row)
            self.commandChanged.emit()

    def duplicate_position(self) -> None:
        row = self.positions.currentRow()
        if row < 0:
            return
        self.add_position(self.position_at(row))
        self.commandChanged.emit()

    def shift_position(self, direction: int) -> None:
        row = self.positions.currentRow()
        other = row + direction
        if row < 0 or other < 0 or other >= self.positions.rowCount():
            return
        current = self.position_at(row)
        swap = self.position_at(other)
        self._write_position(row, swap)
        self._write_position(other, current)
        self.positions.setCurrentCell(other, 0)
        self.commandChanged.emit()

    def capture_position(self) -> None:
        pos = QCursor.pos()
        row = self.positions.currentRow()
        if row < 0:
            row = 0
        self.positions.item(row, 2).setText(str(pos.x()))
        self.positions.item(row, 3).setText(str(pos.y()))
        self.commandChanged.emit()

    def _write_position(self, row: int, pos: ClickPosition) -> None:
        self.positions.item(row, 0).setCheckState(Qt.CheckState.Checked if pos.enabled else Qt.CheckState.Unchecked)
        values = [pos.name, pos.x, pos.y, pos.button, pos.clicks, pos.delay_ms, pos.interval_ms, pos.order, pos.priority, pos.random_radius, pos.jitter_ms]
        for col, value in enumerate(values, start=1):
            self.positions.item(row, col).setText(str(value))

    def position_at(self, row: int) -> ClickPosition:
        def value(col: int, fallback: int = 0) -> int:
            item = self.positions.item(row, col)
            return int(item.text()) if item and item.text().lstrip("-").isdigit() else fallback

        enabled_item = self.positions.item(row, 0)
        name_item = self.positions.item(row, 1)
        return ClickPosition(
            name=name_item.text() if name_item else f"Position {row + 1}",
            x=value(2),
            y=value(3),
            button=max(value(4, 1), 1),
            clicks=max(value(5, 1), 1),
            delay_ms=value(6),
            interval_ms=value(7, 100),
            order=value(8, row),
            enabled=enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True,
            priority=value(9, 1),
            random_radius=value(10),
            jitter_ms=value(11),
        )

    def positions_list(self) -> list[ClickPosition]:
        return [self.position_at(row) for row in range(self.positions.rowCount())]

    def profile(self) -> AutoClickerProfile:
        return AutoClickerProfile(
            positions=self.positions_list(),
            order=CommandOrder(self.order_combo.currentText()),
            clicks_per_second=self.cps_spin.value(),
            random_cps=self.random_cps.isChecked(),
            loop_forever=self.loop_forever.isChecked(),
            loops=self.loops_spin.value(),
            start_delay_ms=self.start_delay.value(),
            stop_delay_ms=self.stop_delay.value(),
            total_clicks=self.total_clicks.value(),
            movement_style=self.movement_style.currentText(),
            ellipse_radius_x=self.ellipse_x_spin.value(),
            ellipse_radius_y=self.ellipse_y_spin.value(),
            offset_radius_x=self.offset_x_spin.value(),
            offset_radius_y=self.offset_y_spin.value(),
            bezier_steps=self.bezier_steps.value(),
            target_window=dict(self._target_window),
        )

    def set_target_window(self, target: dict[str, Any]) -> None:
        self._target_window = dict(target)

    def load_profile_data(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            return
        self.cps_spin.setValue(_safe_float(data.get("clicks_per_second", self.cps_spin.value()), self.cps_spin.value()))
        self.random_cps.setChecked(bool(data.get("random_cps", self.random_cps.isChecked())))
        self.loop_forever.setChecked(bool(data.get("loop_forever", self.loop_forever.isChecked())))
        self.loops_spin.setValue(_safe_int(str(data.get("loops", self.loops_spin.value())), self.loops_spin.value()))
        self.start_delay.setValue(_safe_int(str(data.get("start_delay_ms", self.start_delay.value())), self.start_delay.value()))
        self.stop_delay.setValue(_safe_int(str(data.get("stop_delay_ms", self.stop_delay.value())), self.stop_delay.value()))
        self.total_clicks.setValue(_safe_int(str(data.get("total_clicks", self.total_clicks.value())), self.total_clicks.value()))
        self.order_combo.setCurrentText(str(data.get("order", self.order_combo.currentText())))
        self.movement_style.setCurrentText(str(data.get("movement_style", self.movement_style.currentText())))
        self.ellipse_x_spin.setValue(_safe_int(str(data.get("ellipse_radius_x", self.ellipse_x_spin.value())), self.ellipse_x_spin.value()))
        self.ellipse_y_spin.setValue(_safe_int(str(data.get("ellipse_radius_y", self.ellipse_y_spin.value())), self.ellipse_y_spin.value()))
        self.offset_x_spin.setValue(_safe_int(str(data.get("offset_radius_x", self.offset_x_spin.value())), self.offset_x_spin.value()))
        self.offset_y_spin.setValue(_safe_int(str(data.get("offset_radius_y", self.offset_y_spin.value())), self.offset_y_spin.value()))
        self.bezier_steps.setValue(max(_safe_int(str(data.get("bezier_steps", self.bezier_steps.value())), self.bezier_steps.value()), 2))
        self.set_target_window(data.get("target_window", {}))
        positions = data.get("positions", [])
        if isinstance(positions, list):
            self.positions.setRowCount(0)
            for entry in positions:
                if isinstance(entry, dict):
                    try:
                        self.add_position(ClickPosition(**entry))
                    except Exception:
                        continue

    def command_spec(self) -> CommandSpec | None:
        if not self.positions.rowCount():
            return None
        pos = self.position_at(self.positions.currentRow() if self.positions.currentRow() >= 0 else 0)
        return mouse_click(pos.button, pos.clicks, pos.interval_ms)

    def preview_command(self) -> str:
        if not self.positions.rowCount():
            return ""
        pos = self.position_at(self.positions.currentRow() if self.positions.currentRow() >= 0 else 0)
        return f"xdotool mousemove {pos.x} {pos.y} click {pos.button}"

    def execute_direct(self) -> bool:
        started = self.controller.start(self.profile())
        if not started:
            QMessageBox.information(self, "Auto Clicker", "The auto clicker is already running.")
        return started

    def import_positions(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import click positions", str(Path.home()), "JSON Files (*.json)")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.positions.setRowCount(0)
        for entry in data:
            self.add_position(ClickPosition(**entry))

    def export_positions(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export click positions", str(Path.home() / "click_positions.json"), "JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps([asdict(position) for position in self.positions_list()], indent=2), encoding="utf-8")

    def save_profile(self) -> None:
        self.export_positions()

    def load_profile(self) -> None:
        self.import_positions()


class TerminalTab(BaseCommandTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.command_edit = QLineEdit("xdotool getmouselocation --shell")
        self.preview = QLabel()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Raw xdotool command"))
        layout.addWidget(self.command_edit)
        layout.addWidget(self.preview)
        self.command_edit.textChanged.connect(lambda *_: self.commandChanged.emit())
        self.commandChanged.connect(lambda: self.preview.setText(self.preview_command()))
        self.preview.setText(self.preview_command())

    def command_spec(self) -> CommandSpec | None:
        try:
            return raw_command(self.command_edit.text())
        except ValueError:
            return None


class HistoryTab(BaseCommandTab):
    commandRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.search_edit = QLineEdit()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Pinned", "Favorite", "Timestamp", "Exit", "Command", "Stdout"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.rerun_button = QPushButton("Rerun")
        self.clear_button = QPushButton("Clear")
        self.export_button = QPushButton("Export")
        top = QHBoxLayout()
        top.addWidget(self.search_edit)
        top.addWidget(self.rerun_button)
        top.addWidget(self.clear_button)
        top.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.table.itemSelectionChanged.connect(lambda *_: self.commandChanged.emit())
        self.rerun_button.clicked.connect(lambda: self._rerun_selected())
        self.clear_button.clicked.connect(lambda: self.table.setRowCount(0))
        self.export_button.clicked.connect(lambda: self._export_history())

    def _export_history(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export history", str(Path.home() / "xdotool-history.json"), "JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.entries(), indent=2), encoding="utf-8")

    def _rerun_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 4)
            if item:
                self.commandRequested.emit(item.text())

    def _apply_filter(self) -> None:
        needle = self.search_edit.text().lower().strip()
        for row in range(self.table.rowCount()):
            text = " ".join(self.table.item(row, col).text() if self.table.item(row, col) else "" for col in range(self.table.columnCount()))
            self.table.setRowHidden(row, needle not in text.lower())

    def add_entry(self, entry: HistoryEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        pinned = QTableWidgetItem("Y" if entry.pinned else "")
        favorite = QTableWidgetItem("Y" if entry.favorite else "")
        self.table.setItem(row, 0, pinned)
        self.table.setItem(row, 1, favorite)
        self.table.setItem(row, 2, QTableWidgetItem(entry.timestamp))
        self.table.setItem(row, 3, QTableWidgetItem(str(entry.exit_code)))
        self.table.setItem(row, 4, QTableWidgetItem(entry.command))
        self.table.setItem(row, 5, QTableWidgetItem(entry.stdout[:80]))
        self._apply_filter()

    def entries(self) -> list[dict]:
        items: list[dict] = []
        for row in range(self.table.rowCount()):
            items.append({
                "pinned": self.table.item(row, 0).text() == "Y",
                "favorite": self.table.item(row, 1).text() == "Y",
                "timestamp": self.table.item(row, 2).text(),
                "exit_code": int(self.table.item(row, 3).text()),
                "command": self.table.item(row, 4).text(),
                "stdout": self.table.item(row, 5).text(),
            })
        return items

    def set_entries(self, entries: list[dict]) -> None:
        self.table.setRowCount(0)
        for entry in entries:
            self.add_entry(HistoryEntry(**entry))

    def preview_command(self) -> str:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 4)
            return item.text() if item else ""
        return ""

    def command_spec(self) -> CommandSpec | None:
        preview = self.preview_command()
        if not preview:
            return None
        try:
            return raw_command(preview)
        except ValueError:
            return None


class PresetsTab(BaseCommandTab):
    loadRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Category", "Payload"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.add_button = QPushButton("Add Current")
        self.delete_button = QPushButton("Delete")
        self.import_button = QPushButton("Import")
        self.export_button = QPushButton("Export")
        top = QHBoxLayout()
        top.addWidget(self.add_button)
        top.addWidget(self.delete_button)
        top.addWidget(self.import_button)
        top.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        self.add_button.clicked.connect(lambda: self._add_blank())
        self.delete_button.clicked.connect(lambda: self._delete_selected())
        self.import_button.clicked.connect(lambda: self._import_presets())
        self.export_button.clicked.connect(lambda: self._export_presets())
        self.table.cellDoubleClicked.connect(self._activate_selected)
        self.table.itemSelectionChanged.connect(lambda *_: self.commandChanged.emit())

    def _add_blank(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(f"Preset {row + 1}"))
        self.table.setItem(row, 1, QTableWidgetItem("custom"))
        self.table.setItem(row, 2, QTableWidgetItem(json.dumps({"command": ""})))
        self.commandChanged.emit()

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.commandChanged.emit()

    def _activate_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 2)
            if item:
                try:
                    payload = json.loads(item.text())
                except json.JSONDecodeError:
                    payload = item.text()
                if isinstance(payload, dict) and "command" in payload:
                    self.loadRequested.emit(str(payload["command"]))
                else:
                    self.loadRequested.emit(item.text())

    def _import_presets(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import presets", str(Path.home()), "JSON Files (*.json)")
        if not path:
            return
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.table.setRowCount(0)
        for preset in data:
            self.add_preset(PresetEntry(**preset))

    def _export_presets(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export presets", str(Path.home() / "xdotool-presets.json"), "JSON Files (*.json)")
        if not path:
            return
        Path(path).write_text(json.dumps(self.entries(), indent=2), encoding="utf-8")

    def add_preset(self, preset: PresetEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(preset.name))
        self.table.setItem(row, 1, QTableWidgetItem(preset.category))
        self.table.setItem(row, 2, QTableWidgetItem(json.dumps(preset.payload, ensure_ascii=False)))

    def entries(self) -> list[dict]:
        items: list[dict] = []
        for row in range(self.table.rowCount()):
            items.append({
                "name": self.table.item(row, 0).text(),
                "category": self.table.item(row, 1).text(),
                "payload": json.loads(self.table.item(row, 2).text()),
            })
        return items

    def set_entries(self, entries: list[dict]) -> None:
        self.table.setRowCount(0)
        for entry in entries:
            self.add_preset(PresetEntry(**entry))

    def preview_command(self) -> str:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 2)
            return item.text() if item else ""
        return ""

    def command_spec(self) -> CommandSpec | None:
        return None


class HotkeysTab(BaseCommandTab):
    hotkeysChanged = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(len(HOTKEY_ACTIONS), 4)
        self.table.setHorizontalHeaderLabels(["Action", "Category", "Shortcut", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.save_button = QPushButton("Apply & Save")
        self.reset_button = QPushButton("Reset Defaults")
        self.disable_button = QPushButton("Disable All")
        self.info_label = QLabel("Emergency stop always keeps a fallback on Ctrl+Alt+Escape.")
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.disable_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.info_label)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(lambda: self.save())
        self.reset_button.clicked.connect(lambda: self.reset_defaults())
        self.disable_button.clicked.connect(lambda: self.disable_all())
        self._populate_rows(hotkey_defaults())

    def _populate_rows(self, bindings: dict[str, str]) -> None:
        for row, spec in enumerate(HOTKEY_ACTIONS):
            action_item = QTableWidgetItem(spec.label)
            action_item.setFlags(action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            action_item.setData(Qt.ItemDataRole.UserRole, spec.name)
            category_item = QTableWidgetItem(spec.category)
            category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            shortcut_item = QTableWidgetItem(bindings.get(spec.name, spec.default))
            desc_item = QTableWidgetItem(spec.description)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, action_item)
            self.table.setItem(row, 1, category_item)
            self.table.setItem(row, 2, shortcut_item)
            self.table.setItem(row, 3, desc_item)

    def bindings(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            action_item = self.table.item(row, 0)
            shortcut_item = self.table.item(row, 2)
            if not action_item:
                continue
            name = str(action_item.data(Qt.ItemDataRole.UserRole) or action_item.text())
            values[name] = shortcut_item.text().strip() if shortcut_item else ""
        return values

    def load_from_config(self, bindings: dict[str, str]) -> None:
        self._populate_rows(normalize_hotkey_bindings(bindings))

    def save(self) -> None:
        values = self.bindings()
        self.hotkeysChanged.emit(values)
        QMessageBox.information(self, "Hotkeys", "Hotkeys saved. Global bindings will update immediately.")

    def reset_defaults(self) -> None:
        self._populate_rows(hotkey_defaults())

    def disable_all(self) -> None:
        self._populate_rows({spec.name: "" for spec in HOTKEY_ACTIONS})

    def command_spec(self) -> CommandSpec | None:
        return None


class AppTabs(QTabWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.keyboard = KeyboardTab()
        self.mouse = MouseTab()
        self.windows = WindowsTab()
        self.desktop = DesktopTab()
        self.typing = TypingTab()
        self.automation = StructuredAutomationTab()
        self.autoclicker = AutoClickerTab()
        self.terminal = TerminalTab()
        self.history = HistoryTab()
        self.presets = PresetsTab()
        self.hotkeys = HotkeysTab()
        self.addTab(self.keyboard, "Keyboard")
        self.addTab(self.mouse, "Mouse")
        self.addTab(self.windows, "Windows")
        self.addTab(self.desktop, "Desktop")
        self.addTab(self.typing, "Typing")
        self.addTab(self.automation, "Automation")
        self.addTab(self.autoclicker, "Auto Clicker")
        self.addTab(self.terminal, "Terminal")
        self.addTab(self.history, "History")
        self.addTab(self.presets, "Presets")
        self.addTab(self.hotkeys, "Hotkeys")

    def active_tab(self) -> BaseCommandTab:
        widget = self.currentWidget()
        assert isinstance(widget, BaseCommandTab)
        return widget

    def preview_command(self) -> str:
        tab = self.active_tab()
        return tab.preview_command()

    def command_spec(self) -> CommandSpec | None:
        tab = self.active_tab()
        return tab.command_spec()

    def execute_direct(self) -> bool:
        tab = self.active_tab()
        return tab.execute_direct()

    def select_named_tab(self, name: str) -> bool:
        mapping = {
            "keyboard": self.keyboard,
            "mouse": self.mouse,
            "windows": self.windows,
            "desktop": self.desktop,
            "typing": self.typing,
            "automation": self.automation,
            "autoclicker": self.autoclicker,
            "terminal": self.terminal,
            "history": self.history,
            "presets": self.presets,
            "hotkeys": self.hotkeys,
        }
        widget = mapping.get(name)
        if widget is None:
            return False
        self.setCurrentWidget(widget)
        return True
