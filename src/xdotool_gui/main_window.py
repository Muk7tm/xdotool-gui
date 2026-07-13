from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QCursor, QGuiApplication, QIcon, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .command_builder import preview
from .config import ConfigStore, ensure_config_dir
from .executor import CommandExecutor
from .models import HistoryEntry, PresetEntry
from .services.hotkeys import HotkeyManager
from .tabs import AppTabs, BaseCommandTab


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, store: ConfigStore) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Settings")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["system", "fusion"])
        self.theme_combo.setCurrentText(store.data.get("theme", "system"))
        form = QFormLayout()
        form.addRow("Theme", self.theme_combo)
        form.addRow(QLabel("Hotkeys are configured on the Hotkeys tab."))
        self.setLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self) -> None:  # type: ignore[override]
        self.store.data["theme"] = self.theme_combo.currentText()
        self.store.save(self.store.data)
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("xdotool-gui")
        self.resize(1280, 860)
        icon_path = Path(__file__).resolve().parent / "resources" / "icons" / "xdotool-gui.svg"
        self.setWindowIcon(QIcon(str(icon_path)))
        self._default_style = QApplication.style().objectName() or "Fusion"
        self.store = ConfigStore()
        self.config = self.store.load()
        self._apply_theme()
        self.executor = CommandExecutor(self)
        self.tabs = AppTabs(self)
        self.hotkeys = HotkeyManager(self)
        self._shortcuts: list[QShortcut] = []
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(1000)
        self._autosave_timer.timeout.connect(self._save_state)
        self.preview_edit = QLineEdit()
        self.preview_edit.setReadOnly(True)
        self.execute_button = QPushButton("Execute")
        self.copy_button = QPushButton("Copy")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log_auto_scroll = QCheckBox("Auto-scroll")
        self.log_auto_scroll.setChecked(True)
        self.save_log_button = QPushButton("Save Log")
        self.clear_log_button = QPushButton("Clear Log")
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.output, "Output")
        self.bottom_tabs.addTab(self.log, "Log")
        self._coords_label = QLabel("0, 0")
        self._state_label = QLabel("Ready")
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(250)
        self._ui_timer.timeout.connect(self._update_live_coordinates)
        self._build_ui()
        self._bind_signals()
        self._restore_geometry()
        self._load_state()
        self._install_shortcuts()
        self._ui_timer.start()
        self._refresh_run_state()
        self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        execute_action = QAction("Execute", self)
        execute_action.setShortcut(QKeySequence.StandardKey.Refresh)
        clear_action = QAction("Clear Output", self)
        save_preset_action = QAction("Save Preset", self)
        history_action = QAction("Save History", self)
        hotkeys_action = QAction("Hotkeys", self)
        settings_action = QAction("Settings", self)
        about_action = QAction("About", self)
        toolbar.addAction(execute_action)
        toolbar.addAction(clear_action)
        toolbar.addAction(save_preset_action)
        toolbar.addAction(history_action)
        toolbar.addAction(hotkeys_action)
        toolbar.addAction(settings_action)
        toolbar.addAction(about_action)
        self.addToolBarBreak()
        top = QGroupBox("Command Preview")
        top_layout = QHBoxLayout(top)
        top_layout.addWidget(self.preview_edit)
        top_layout.addWidget(self.execute_button)
        top_layout.addWidget(self.copy_button)
        top_layout.addWidget(self.stop_button)
        log_controls = QWidget()
        log_layout = QHBoxLayout(log_controls)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.save_log_button)
        log_layout.addWidget(self.clear_log_button)
        log_layout.addWidget(self.log_auto_scroll)
        log_layout.addStretch(1)
        log_panel = QWidget()
        log_panel_layout = QVBoxLayout(log_panel)
        log_panel_layout.addWidget(log_controls)
        log_panel_layout.addWidget(self.bottom_tabs)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(log_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(top)
        layout.addWidget(splitter)
        self.setCentralWidget(central)
        self.statusBar().addPermanentWidget(self._state_label)
        self.statusBar().addPermanentWidget(self._coords_label)
        self.tabs.history.commandRequested.connect(self._run_history_command)
        self.tabs.presets.loadRequested.connect(self._load_preset_payload)
        self.tabs.hotkeys.hotkeysChanged.connect(self._apply_hotkeys)
        self.tabs.windows.windowTargetChanged.connect(self._set_window_target)
        self.tabs.automation.commandChanged.connect(self._refresh_state_labels)
        self.tabs.autoclicker.commandChanged.connect(self._refresh_state_labels)
        execute_action.triggered.connect(lambda: self.execute_current())
        clear_action.triggered.connect(lambda: self.output.clear())
        save_preset_action.triggered.connect(lambda: self._save_current_preset())
        history_action.triggered.connect(lambda: self._save_state())
        hotkeys_action.triggered.connect(lambda: self.show_hotkeys())
        settings_action.triggered.connect(lambda: self.show_settings())
        about_action.triggered.connect(lambda: self.show_about())
        self.execute_button.clicked.connect(lambda: self.execute_current())
        self.copy_button.clicked.connect(lambda: self._copy_preview())
        self.stop_button.clicked.connect(lambda: self._stop_active())
        self.save_log_button.clicked.connect(lambda: self._save_log())
        self.clear_log_button.clicked.connect(lambda: self.log.clear())
        self.executor.started.connect(self._log_started)
        self.executor.finished.connect(self._log_finished)
        self.executor.busyChanged.connect(self._busy_changed)
        self.tabs.automation.runner.stateChanged.connect(lambda _state: self._refresh_run_state())
        self.tabs.autoclicker.controller.stateChanged.connect(lambda _state: self._refresh_run_state())
        self.hotkeys.activated.connect(self._dispatch_hotkey)
        self.hotkeys.statusChanged.connect(self.statusBar().showMessage)
        self.hotkeys.error.connect(self._hotkey_error)

    def _bind_signals(self) -> None:
        for tab in [
            self.tabs.keyboard,
            self.tabs.mouse,
            self.tabs.windows,
            self.tabs.desktop,
            self.tabs.typing,
            self.tabs.automation,
            self.tabs.autoclicker,
            self.tabs.terminal,
            self.tabs.history,
            self.tabs.presets,
        ]:
            tab.commandChanged.connect(self.refresh_preview)
        self.tabs.currentChanged.connect(self.refresh_preview)
        self.refresh_preview()

    def _restore_geometry(self) -> None:
        window = self.config.get("window", {})
        width = int(window.get("width", 1280))
        height = int(window.get("height", 860))
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geometry = screen.availableGeometry()
            width = min(width, max(geometry.width() - 40, 1024))
            height = min(height, max(geometry.height() - 80, 720))
        self.resize(width, height)

    def _load_state(self) -> None:
        self.tabs.history.set_entries(self.config.get("history", []))
        self.tabs.presets.set_entries(self.config.get("presets", []))
        self.tabs.hotkeys.load_from_config(self.config.get("hotkeys", {}))
        self.tabs.windows.set_target(self.config.get("window_target", {}))
        automation_target = self.config.get("window_target", {})
        self.tabs.automation.set_target_window(automation_target)
        self.tabs.autoclicker.set_target_window(automation_target)
        logging_cfg = self.config.get("logging", {})
        self.log_auto_scroll.setChecked(bool(logging_cfg.get("auto_scroll", True)))
        automation_cfg = self.config.get("automation", {})
        if isinstance(automation_cfg, dict):
            self.tabs.automation.macro_name.setText(str(automation_cfg.get("macro_name", self.tabs.automation.macro_name.text())))
            self.tabs.automation.loop_forever.setChecked(bool(automation_cfg.get("loop_forever", self.tabs.automation.loop_forever.isChecked())))
            self.tabs.automation.repeat_spin.setValue(_coerce_int(automation_cfg.get("repeat", self.tabs.automation.repeat_spin.value()), self.tabs.automation.repeat_spin.value()))
            self.tabs.automation.confirm_infinite.setChecked(bool(automation_cfg.get("confirm_infinite_loops", True)))
            self.tabs.automation.max_runtime.setValue(_coerce_int(automation_cfg.get("max_runtime_minutes", self.tabs.automation.max_runtime.value()), self.tabs.automation.max_runtime.value()))
            self.tabs.automation.max_failures.setValue(_coerce_int(automation_cfg.get("max_failures", self.tabs.automation.max_failures.value()), self.tabs.automation.max_failures.value()))
            self.tabs.automation.continue_on_timeout.setChecked(bool(automation_cfg.get("continue_on_timeout", False)))
            self.tabs.automation.stop_on_window_loss.setChecked(bool(automation_cfg.get("stop_on_window_loss", True)))
            self.tabs.automation.retry_count.setValue(max(_coerce_int(automation_cfg.get("retry_count", self.tabs.automation.retry_count.value()), self.tabs.automation.retry_count.value()), 1))
            self.tabs.automation.retry_delay.setValue(_coerce_int(automation_cfg.get("retry_delay_ms", self.tabs.automation.retry_delay.value()), self.tabs.automation.retry_delay.value()))
            self.tabs.automation.delay_mode.setCurrentText(str(automation_cfg.get("delay_mode", self.tabs.automation.delay_mode.currentText())))
            self.tabs.automation.fixed_delay.setValue(_coerce_int(automation_cfg.get("fixed_delay_ms", self.tabs.automation.fixed_delay.value()), self.tabs.automation.fixed_delay.value()))
            self.tabs.automation.random_min.setValue(_coerce_int(automation_cfg.get("random_delay_min_ms", self.tabs.automation.random_min.value()), self.tabs.automation.random_min.value()))
            self.tabs.automation.random_max.setValue(_coerce_int(automation_cfg.get("random_delay_max_ms", self.tabs.automation.random_max.value()), self.tabs.automation.random_max.value()))
            self.tabs.automation.gaussian_mean.setValue(_coerce_int(automation_cfg.get("gaussian_mean_ms", self.tabs.automation.gaussian_mean.value()), self.tabs.automation.gaussian_mean.value()))
            self.tabs.automation.gaussian_stdev.setValue(_coerce_int(automation_cfg.get("gaussian_stdev_ms", self.tabs.automation.gaussian_stdev.value()), self.tabs.automation.gaussian_stdev.value()))
        last_macro = self.config.get("last_macro")
        if not last_macro:
            macros = self.config.get("macros", [])
            if isinstance(macros, list) and macros:
                candidate = macros[-1]
                if isinstance(candidate, dict):
                    last_macro = candidate
        if isinstance(last_macro, dict) and (last_macro.get("actions") or last_macro.get("name") or last_macro.get("options")):
            try:
                self.tabs.automation._load_macro_data(last_macro, replace=True)
            except Exception as exc:
                self.log.appendPlainText(f"[{datetime.now().isoformat(timespec='seconds')}] warning: failed to load last macro: {exc}")
        click_profiles = self.config.get("click_profiles", [])
        if isinstance(click_profiles, list) and click_profiles:
            first_profile = click_profiles[0]
            if isinstance(first_profile, dict):
                try:
                    self.tabs.autoclicker.load_profile_data(first_profile)
                except Exception as exc:
                    self.log.appendPlainText(f"[{datetime.now().isoformat(timespec='seconds')}] warning: failed to load click profile: {exc}")

    def _apply_hotkeys(self, bindings: dict[str, str]) -> None:
        self.config["hotkeys"] = bindings
        self.store.save(self.config)
        self._install_shortcuts()
        self.statusBar().showMessage("Hotkeys applied")
        self._schedule_save_state()

    def _install_shortcuts(self) -> None:
        hotkeys = self.config.get("hotkeys", {})
        if self.hotkeys.configure({name: str(value) for name, value in hotkeys.items()}):
            for shortcut in self._shortcuts:
                shortcut.setParent(None)
                shortcut.deleteLater()
            self._shortcuts.clear()
            return
        for shortcut in self._shortcuts:
            shortcut.setParent(None)
            shortcut.deleteLater()
        self._shortcuts.clear()
        mapping = {
            "start": self.execute_current,
            "stop": self._stop_active,
            "pause": self._pause_active,
            "resume": self._resume_active,
            "capture_position": self._capture_position,
            "toggle_clicking": self._toggle_clicking,
            "emergency_stop": self._stop_active,
        }
        for name, handler in mapping.items():
            sequence = str(hotkeys.get(name, "")).strip()
            if not sequence:
                continue
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(lambda handler=handler: handler())
            self._shortcuts.append(shortcut)

    def refresh_preview(self, *_: object) -> None:
        text = self.tabs.preview_command()
        self.preview_edit.setText(text)
        self.statusBar().showMessage("Preview updated" if text else "Ready")

    def execute_current(self) -> None:
        if self.tabs.execute_direct():
            self._append_log("Automation started")
            self._refresh_run_state()
            return
        spec = self.tabs.command_spec()
        if spec is None:
            QMessageBox.information(self, "xdotool-gui", "Nothing to execute on this tab.")
            return
        if not self.executor.run(spec):
            QMessageBox.information(self, "xdotool-gui", "Another command is already running.")

    def _log_started(self, command_text: str) -> None:
        self.output.appendPlainText(f"$ {command_text}")
        self._append_log(f"Running command: {command_text}", "INFO")
        self.statusBar().showMessage("Running command")

    def _log_finished(self, result: object) -> None:
        if result is None:
            return
        exit_code = getattr(result, "returncode", 1)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        preview_text = getattr(result, "argv", [])
        command_text = preview(preview_text) if preview_text else self.preview_edit.text()
        self.output.appendPlainText(stdout.strip() or "(no stdout)")
        if stderr:
            self.output.appendPlainText(stderr.strip())
        level = "INFO" if exit_code == 0 else "ERROR"
        self._append_log(f"exit={exit_code} {command_text}", level)
        self.tabs.history.add_entry(
            HistoryEntry(
                command=command_text,
                timestamp=datetime.now().isoformat(timespec="seconds"),
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        )
        self._schedule_save_state()
        self.statusBar().showMessage(f"Finished with exit code {exit_code}")

    def _busy_changed(self, busy: bool) -> None:
        self.execute_button.setEnabled(not busy)
        self._refresh_run_state()

    def _refresh_run_state(self) -> None:
        running = self.executor.busy() or self.tabs.automation.runner.active or self.tabs.autoclicker.controller.active
        self.execute_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self._state_label.setText("Running" if running else "Ready")
        self._coords_label.setText(self._coords_text())

    def _copy_preview(self) -> None:
        text = self.preview_edit.text()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Command copied to clipboard")

    def _run_history_command(self, command: str) -> None:
        self.tabs.terminal.command_edit.setText(command)
        self.tabs.setCurrentWidget(self.tabs.terminal)
        self.refresh_preview()
        self.execute_current()

    def _load_preset_payload(self, payload: str) -> None:
        self.tabs.terminal.command_edit.setText(payload)
        self.tabs.setCurrentWidget(self.tabs.terminal)
        self.refresh_preview()

    def _save_current_preset(self) -> None:
        command_text = self.preview_edit.text().strip()
        if not command_text:
            QMessageBox.information(self, "xdotool-gui", "There is no command preview to save yet.")
            return
        tab_name = self.tabs.tabText(self.tabs.currentIndex())
        preset = PresetEntry(
            name=f"{tab_name} preset {self.tabs.presets.table.rowCount() + 1}",
            category=tab_name.lower().replace(" ", "_"),
            payload={"command": command_text, "source_tab": tab_name},
        )
        self.tabs.presets.add_preset(preset)
        self.statusBar().showMessage(f"Saved preset from {tab_name}")

    def _stop_active(self) -> None:
        self.tabs.automation.runner.stop()
        self.tabs.autoclicker.controller.stop()
        self.statusBar().showMessage("Stop requested")

    def _pause_active(self) -> None:
        self.tabs.automation.runner.pause()
        self.tabs.autoclicker.controller.pause()
        self.statusBar().showMessage("Pause requested")

    def _resume_active(self) -> None:
        self.tabs.automation.runner.resume()
        self.tabs.autoclicker.controller.resume()
        self.statusBar().showMessage("Resume requested")

    def _capture_position(self) -> None:
        current = self.tabs.active_tab()
        if hasattr(current, "capture_position"):
            current.capture_position()
            self.refresh_preview()

    def _toggle_clicking(self) -> None:
        if self.tabs.autoclicker.controller.active:
            self.tabs.autoclicker.controller.stop()
        else:
            self.tabs.autoclicker.execute_direct()
        self._refresh_run_state()

    def _dispatch_hotkey(self, name: str) -> None:
        mapping = {
            "execute_current": self.execute_current,
            "save_preset": self._save_current_preset,
            "save_history": self._save_state,
            "show_settings": self.show_settings,
            "show_hotkeys": self.show_hotkeys,
            "show_about": self.show_about,
            "refresh_preview": self.refresh_preview,
            "copy_preview": self._copy_preview,
            "quit_app": self.close,
            "stop_active": self._stop_active,
            "pause_active": self._pause_active,
            "resume_active": self._resume_active,
            "capture_position": self._capture_position,
            "toggle_clicking": self._toggle_clicking,
            "emergency_stop": self._stop_active,
            "tab_keyboard": lambda: self._select_tab("keyboard"),
            "tab_mouse": lambda: self._select_tab("mouse"),
            "tab_windows": lambda: self._select_tab("windows"),
            "tab_desktop": lambda: self._select_tab("desktop"),
            "tab_typing": lambda: self._select_tab("typing"),
            "tab_automation": lambda: self._select_tab("automation"),
            "tab_autoclicker": lambda: self._select_tab("autoclicker"),
            "tab_terminal": lambda: self._select_tab("terminal"),
            "tab_history": lambda: self._select_tab("history"),
            "tab_presets": lambda: self._select_tab("presets"),
            "tab_hotkeys": lambda: self._select_tab("hotkeys"),
        }
        action = mapping.get(name)
        if action:
            action()

    def _hotkey_error(self, message: str) -> None:
        self._append_log(f"Hotkey error: {message}", "ERROR")

    def _select_tab(self, name: str) -> None:
        if self.tabs.select_named_tab(name):
            self.refresh_preview()

    def _append_log(self, message: str, level: str = "INFO") -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.log.appendPlainText(f"[{timestamp}] {level}: {message}")
        if self.log_auto_scroll.isChecked():
            self.log.moveCursor(QTextCursor.MoveOperation.End)

    def _save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save log", str(Path.home() / "xdotool-gui.log"), "Log Files (*.log *.txt);;All Files (*)")
        if not path:
            return
        Path(path).write_text(self.log.toPlainText(), encoding="utf-8")
        self.statusBar().showMessage(f"Log saved to {path}")

    def _set_window_target(self, target: dict[str, object]) -> None:
        self.config["window_target"] = dict(target)
        self.tabs.windows.set_target(self.config["window_target"])
        self.tabs.automation.set_target_window(self.config["window_target"])
        self.tabs.autoclicker.set_target_window(self.config["window_target"])
        self._append_log("Window target updated", "INFO")
        self._schedule_save_state()

    def _refresh_state_labels(self) -> None:
        self._coords_label.setText(self._coords_text())
        if self.tabs.currentWidget() is self.tabs.automation:
            self._state_label.setText("Editing macro")
        self._schedule_save_state()

    def _update_live_coordinates(self) -> None:
        self._coords_label.setText(self._coords_text())

    def _coords_text(self) -> str:
        pos = QCursor.pos()
        return f"{pos.x()}, {pos.y()}"

    def show_settings(self) -> None:
        if SettingsDialog(self, self.store).exec() == QDialog.DialogCode.Accepted:
            self.config = self.store.data
            self._apply_theme()
            self._install_shortcuts()

    def show_hotkeys(self) -> None:
        self._select_tab("hotkeys")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About xdotool-gui",
            "xdotool-gui is a lightweight PySide6 frontend that builds and executes xdotool commands on X11.",
        )

    def _save_state(self) -> None:
        self.config["window"] = {"width": self.width(), "height": self.height(), "x": self.x(), "y": self.y()}
        self.config["history"] = self.tabs.history.entries()
        self.config["presets"] = self.tabs.presets.entries()
        self.config["window_target"] = asdict(self.tabs.automation.target_window())
        self.config["logging"] = {"auto_scroll": self.log_auto_scroll.isChecked()}
        self.config["automation"] = {
            "macro_name": self.tabs.automation.macro_name.text(),
            "loop_forever": self.tabs.automation.loop_forever.isChecked(),
            "repeat": self.tabs.automation.repeat_spin.value(),
            "confirm_infinite_loops": self.tabs.automation.confirm_infinite.isChecked(),
            "max_runtime_minutes": self.tabs.automation.max_runtime.value(),
            "max_failures": self.tabs.automation.max_failures.value(),
            "continue_on_timeout": self.tabs.automation.continue_on_timeout.isChecked(),
            "stop_on_window_loss": self.tabs.automation.stop_on_window_loss.isChecked(),
            "retry_count": self.tabs.automation.retry_count.value(),
            "retry_delay_ms": self.tabs.automation.retry_delay.value(),
            "delay_mode": self.tabs.automation.delay_mode.currentText(),
            "fixed_delay_ms": self.tabs.automation.fixed_delay.value(),
            "random_delay_min_ms": self.tabs.automation.random_min.value(),
            "random_delay_max_ms": self.tabs.automation.random_max.value(),
            "gaussian_mean_ms": self.tabs.automation.gaussian_mean.value(),
            "gaussian_stdev_ms": self.tabs.automation.gaussian_stdev.value(),
        }
        try:
            self.config["click_profiles"] = [asdict(self.tabs.autoclicker.profile())]
        except Exception as exc:
            self._append_log(f"Unable to serialize click profile: {exc}", "ERROR")
        try:
            self.config["last_macro"] = self.tabs.automation._macro_document()
        except Exception as exc:
            self._append_log(f"Unable to serialize macro: {exc}", "ERROR")
        self.store.save(self.config)
        self.statusBar().showMessage(f"Saved {ensure_config_dir()}")
        self._state_label.setText("Saved")

    def _schedule_save_state(self) -> None:
        self._autosave_timer.start()

    def _apply_theme(self) -> None:
        theme = self.config.get("theme", "system")
        if theme == "fusion":
            QApplication.setStyle("Fusion")
        else:
            QApplication.setStyle(self._default_style)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.tabs.automation.stop_recording()
        except Exception:
            pass
        self._autosave_timer.stop()
        self._save_state()
        super().closeEvent(event)
