# xdotool-gui

`xdotool-gui` is a lightweight PySide6 frontend for `xdotool` on Linux X11 desktops.

It focuses on fast startup, a simple Qt-style interface, and direct command generation rather than reimplementing window automation itself.

## Highlights

- Keyboard, mouse, window, desktop, typing, automation, terminal, history, presets, and auto-clicker tabs
- Async command execution through `subprocess`
- X11-backed window discovery, focus management, and pixel sampling
- Structured JSON macros with wait-for-pixel and wait-for-window actions
- Live command preview and copy-to-clipboard support
- JSON configuration stored in `~/.config/xdotool-gui/`
- Global hotkeys on X11 via `pynput`
- Works well on KDE Plasma and other X11 desktops

## Quick Start

```bash
python -m pip install -r requirements.txt
python -m xdotool_gui
```

If your system Python is externally managed, create a local virtualenv first:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m xdotool_gui
```

You need:

- Linux
- X11
- `xdotool`
- `python-xlib`
- Python 3.13+

## Files Worth Reading

- [INSTALL.md](INSTALL.md)
- [BUILD.md](BUILD.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
