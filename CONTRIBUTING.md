# Contributing

Keep the project:

- fast to launch
- native-looking
- simple to maintain
- X11-only

## Style

- Use type hints
- Prefer small reusable widgets
- Keep `xdotool` as the backend
- Avoid adding heavyweight dependencies

## Testing

Run at least:

```bash
python -m py_compile $(find src -name '*.py' | sort)
QT_QPA_PLATFORM=offscreen python - <<'PY'
from PySide6.QtWidgets import QApplication
from xdotool_gui.main_window import MainWindow
app = QApplication([])
window = MainWindow()
print(window.windowTitle())
PY
```

