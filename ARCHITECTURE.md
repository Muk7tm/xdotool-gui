# Architecture

The app is split into small modules so the UI stays lightweight and easy to extend.

## Core modules

- `config.py` loads and saves JSON state in `~/.config/xdotool-gui/`
- `command_builder.py` turns form inputs into `xdotool` argv lists and preview strings
- `executor.py` runs one command asynchronously with `subprocess`
- `automation.py` runs structured macro actions with retries, window sync, and pixel waits
- `autoclicker.py` runs multi-position click profiles with retrying X11 pointer movement
- `services/x11.py` handles window discovery, focus, and pixel sampling
- `services/runtime.py` centralizes retrying `xdotool` execution

## UI modules

- `tabs.py` contains the feature tabs
- `main_window.py` wires preview, execution, logs, and persistence together
- `main.py` starts the Qt application

## Data flow

1. A tab creates a `CommandSpec` or a direct runner profile.
2. The main window shows the generated command in the preview field.
3. On Execute, the command goes through the async runner or the direct runner.
4. Results are appended to the output panel and history.
