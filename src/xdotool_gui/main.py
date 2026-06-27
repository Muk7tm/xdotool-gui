from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("xdotool-gui")
    app.setOrganizationName("xdotool-gui")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
