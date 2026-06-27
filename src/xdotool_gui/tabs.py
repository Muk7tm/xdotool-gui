from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
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
from .models import AutoClickerProfile, AutomationStep, ClickPosition, CommandSpec, CommandOrder, HistoryEntry, PresetEntry


class BaseCommandTab(QWidget):
    commandChanged = Signal()

    def preview_command(self) -> str:
        spec = self.command_spec()
        return spec.preview if spec else ""

    def command_spec(self) -> CommandSpec | None:
        return None

    def execute_direct(self) -> bool:
        return False


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
        self.capture_button = QPushButton("Capture Position")
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
        form = QFormLayout()
        form.addRow("Action", self.action_combo)
        form.addRow("Search / term", self.search_edit)
        form.addRow("Window id", self.window_id)
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("Width", self.w_spin)
        form.addRow("Height", self.h_spin)
        form.addRow("Desktop", self.desktop_spin)
        box = QGroupBox("Windows")
        box.setLayout(form)
        layout = QVBoxLayout(self)
        layout.addWidget(box)
        self.preview = QLabel()
        layout.addWidget(self.preview)
        for widget in [self.action_combo, self.search_edit, self.window_id, self.x_spin, self.y_spin, self.w_spin, self.h_spin, self.desktop_spin]:
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
        self.counter = QLabel("0")
        self.status = QLabel("idle")
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
        self.capture_button = QPushButton("Capture Position")
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
        )

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
        self.automation = AutomationTab()
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
