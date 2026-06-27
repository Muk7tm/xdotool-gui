from __future__ import annotations

import os
import subprocess
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal

from .models import CommandSpec, ExecutionResult


class _CommandWorker(QThread):
    finished = Signal(object)

    def __init__(self, spec: CommandSpec) -> None:
        super().__init__()
        self.spec = spec

    def run(self) -> None:
        started = datetime.now()
        try:
            proc = subprocess.run(
                self.spec.argv,
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                check=False,
            )
            result = ExecutionResult(
                argv=self.spec.argv,
                returncode=proc.returncode,
                stdout=proc.stdout,
                stderr=proc.stderr,
                started_at=started,
                finished_at=datetime.now(),
            )
        except FileNotFoundError as exc:
            result = ExecutionResult(
                argv=self.spec.argv,
                returncode=127,
                stdout="",
                stderr=str(exc),
                started_at=started,
                finished_at=datetime.now(),
            )
        except Exception as exc:  # pragma: no cover - defensive
            result = ExecutionResult(
                argv=self.spec.argv,
                returncode=1,
                stdout="",
                stderr=str(exc),
                started_at=started,
                finished_at=datetime.now(),
            )
        self.finished.emit(result)


class CommandExecutor(QObject):
    started = Signal(str)
    finished = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: _CommandWorker | None = None
        self._busy = False

    def busy(self) -> bool:
        return self._busy

    def run(self, spec: CommandSpec) -> bool:
        if self._busy:
            return False
        self._busy = True
        self.busyChanged.emit(True)
        self.started.emit(spec.preview)
        worker = _CommandWorker(spec)
        worker.finished.connect(self._on_finished)
        self._worker = worker
        worker.start()
        return True

    def _on_finished(self, result: ExecutionResult) -> None:
        self._busy = False
        self.busyChanged.emit(False)
        self.finished.emit(result)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None
