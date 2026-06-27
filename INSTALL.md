# Installation

## From a checkout

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/python -m xdotool_gui
```

## Arch Linux / CachyOS

Install the runtime dependency first:

```bash
sudo pacman -S xdotool python-pyside6
```

Then build and install from the project directory:

```bash
makepkg -si
```

Global hotkeys use `pynput` and the X11 backend. On Wayland, they will not behave the same way.

## Desktop integration

If you package this app system-wide, install:

- `packaging/xdotool-gui.desktop` to `/usr/share/applications/`
- `src/xdotool_gui/resources/icons/xdotool-gui.svg` to an icon theme location such as `/usr/share/icons/hicolor/scalable/apps/`
