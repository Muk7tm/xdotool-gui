from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QDialog,
    QDialogButtonBox,
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
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.addTab(self.output, "Output")
        self.bottom_tabs.addTab(self.log, "Log")
        self._build_ui()
        self._bind_signals()
        self._restore_geometry()
        self._load_state()
        self._install_shortcuts()
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
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.bottom_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(top)
        layout.addWidget(splitter)
        self.setCentralWidget(central)
        self.tabs.history.commandRequested.connect(self._run_history_command)
        self.tabs.presets.loadRequested.connect(self._load_preset_payload)
        self.tabs.hotkeys.hotkeysChanged.connect(self._apply_hotkeys)
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
        self.resize(width, height)

    def _load_state(self) -> None:
        self.tabs.history.set_entries(self.config.get("history", []))
        self.tabs.presets.set_entries(self.config.get("presets", []))
        self.tabs.hotkeys.load_from_config(self.config.get("hotkeys", {}))

    def _apply_hotkeys(self, bindings: dict[str, str]) -> None:
        self.config["hotkeys"] = bindings
        self.store.save(self.config)
        self._install_shortcuts()
        self.statusBar().showMessage("Hotkeys applied")

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
            self.log.appendPlainText(f"[{datetime.now().isoformat(timespec='seconds')}] started direct tab action")
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
        self.statusBar().showMessage("Running command")

    def _log_finished(self, result: object) -> None:
        if not isinstance(result, object):
            return
        exit_code = getattr(result, "returncode", 1)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        preview_text = getattr(result, "argv", [])
        command_text = preview(preview_text) if preview_text else self.preview_edit.text()
        self.output.appendPlainText(stdout.strip() or "(no stdout)")
        if stderr:
            self.output.appendPlainText(stderr.strip())
        self.log.appendPlainText(f"[{datetime.now().isoformat(timespec='seconds')}] exit={exit_code} {command_text}")
        self.tabs.history.add_entry(
            HistoryEntry(
                command=command_text,
                timestamp=datetime.now().isoformat(timespec="seconds"),
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
            )
        )
        self.statusBar().showMessage(f"Finished with exit code {exit_code}")

    def _busy_changed(self, busy: bool) -> None:
        self.execute_button.setEnabled(not busy)
        self._refresh_run_state()

    def _refresh_run_state(self) -> None:
        running = self.executor.busy() or self.tabs.automation.runner.active or self.tabs.autoclicker.controller.active
        self.execute_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

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
        self.log.appendPlainText(f"Hotkey error: {message}")

    def _select_tab(self, name: str) -> None:
        if self.tabs.select_named_tab(name):
            self.refresh_preview()

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
        self.store.save(self.config)
        self.statusBar().showMessage(f"Saved {ensure_config_dir()}")

    def _apply_theme(self) -> None:
        theme = self.config.get("theme", "system")
        if theme == "fusion":
            QApplication.setStyle("Fusion")
        else:
            QApplication.setStyle(self._default_style)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_state()
        super().closeEvent(event)
