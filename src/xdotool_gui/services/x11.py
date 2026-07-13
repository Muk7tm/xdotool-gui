from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency fallback
    Image = None  # type: ignore[assignment]

try:  # pragma: no cover - imported dynamically when X11 is available
    from Xlib import X, display
    from Xlib.error import BadWindow
except Exception as exc:  # pragma: no cover - environment-specific
    display = None  # type: ignore[assignment]
    X = None  # type: ignore[assignment]
    BadWindow = Exception  # type: ignore[assignment]
    _X11_IMPORT_ERROR = exc
else:  # pragma: no cover - import side effect only
    _X11_IMPORT_ERROR = None

from ..models import WindowInfo, WindowTarget


def parse_color(value: str) -> tuple[int, int, int]:
    text = value.strip().lower()
    if not text:
        raise ValueError("Color value is empty.")
    if text.startswith("#"):
        text = text[1:]
    if text.startswith("rgb(") and text.endswith(")"):
        text = text[4:-1]
    if "," in text:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) != 3:
            raise ValueError(f"Invalid RGB color: {value}")
        rgb = tuple(max(0, min(255, int(part))) for part in parts)
        return rgb  # type: ignore[return-value]
    if len(text) == 6:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    raise ValueError(f"Unsupported color format: {value}")


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return max(abs(left[index] - right[index]) for index in range(3))


@dataclass(slots=True)
class WindowSearchResult:
    window: WindowInfo
    matched: bool


class X11Inspector:
    def __init__(self) -> None:
        if display is None or X is None:
            raise RuntimeError(f"X11 helpers unavailable: {_X11_IMPORT_ERROR}")
        self._display = display.Display()
        self._root = self._display.screen().root

    @property
    def display(self):  # type: ignore[override]
        return self._display

    def close(self) -> None:
        try:
            self._display.close()
        except Exception:
            pass

    def pointer_position(self) -> tuple[int, int]:
        pointer = self._root.query_pointer()
        data = pointer._data
        return int(data["root_x"]), int(data["root_y"])

    def window_exists(self, window_id: int) -> bool:
        try:
            window = self._display.create_resource_object("window", int(window_id))
            window.get_attributes()
            return True
        except Exception:
            return False

    def window_title(self, window_id: int) -> str:
        window = self._display.create_resource_object("window", int(window_id))
        return self._get_window_title(window)

    def list_windows(self) -> list[WindowInfo]:
        results: list[WindowInfo] = []
        try:
            children = self._root.query_tree().children
        except Exception:
            return results
        for window in children:
            info = self._describe_window(window)
            if info is not None:
                results.append(info)
        return results

    def search_windows(self, title: str = "", wm_class: str = "", regex: str = "") -> list[WindowInfo]:
        title = title.strip()
        wm_class = wm_class.strip()
        pattern = re.compile(regex, re.IGNORECASE) if regex.strip() else None
        results: list[WindowInfo] = []
        for window in self.list_windows():
            if title and title.lower() not in window.title.lower():
                continue
            if wm_class and wm_class.lower() not in window.wm_class.lower():
                continue
            if pattern is not None and not pattern.search(window.title) and not pattern.search(window.wm_class):
                continue
            results.append(window)
        return results

    def resolve_target(self, target: WindowTarget) -> WindowInfo | None:
        if target.window_id.strip():
            try:
                window_id = int(target.window_id, 0)
            except ValueError:
                window_id = -1
            if window_id > 0 and self.window_exists(window_id):
                info = self._describe_window(self._display.create_resource_object("window", window_id))
                if info is not None:
                    return info
        candidates = self.search_windows(title=target.title, wm_class=target.wm_class, regex=target.title if target.regex else "")
        return candidates[0] if candidates else None

    def focus_window(self, window_id: int) -> None:
        window = self._display.create_resource_object("window", int(window_id))
        window.set_input_focus(X.RevertToParent, X.CurrentTime)
        try:
            window.configure(stack_mode=X.Above)
        except Exception:
            pass
        self._display.sync()

    def pixel_rgb(self, x: int, y: int) -> tuple[int, int, int]:
        image = self._root.get_image(int(x), int(y), 1, 1, X.ZPixmap, 0xFFFFFFFF)
        raw = image.data
        if Image is not None:
            for mode in ("BGRX", "BGRA", "RGBX"):
                try:
                    return Image.frombytes("RGB", (1, 1), raw, "raw", mode).getpixel((0, 0))
                except Exception:
                    continue
        if len(raw) >= 4:
            return int(raw[2]), int(raw[1]), int(raw[0])
        if len(raw) == 3:
            return int(raw[2]), int(raw[1]), int(raw[0])
        raise RuntimeError("Unable to decode pixel color from X11 image data.")

    def _describe_window(self, window) -> WindowInfo | None:
        try:
            attrs = window.get_attributes()
        except BadWindow:
            return None
        except Exception:
            return None
        title = self._get_window_title(window)
        wm_class = self._get_window_class(window)
        pid = self._get_window_pid(window)
        desktop = self._get_window_desktop(window)
        geometry = self._get_window_geometry(window)
        mapped = bool(getattr(attrs, "map_state", 0) == X.IsViewable)
        if not title and not wm_class and not mapped:
            return None
        return WindowInfo(
            window_id=int(window.id),
            title=title,
            wm_class=wm_class,
            pid=pid,
            desktop=desktop,
            x=geometry[0],
            y=geometry[1],
            width=geometry[2],
            height=geometry[3],
            mapped=mapped,
        )

    def _get_window_title(self, window) -> str:
        for atom_name in ("_NET_WM_NAME", "WM_NAME"):
            try:
                atom = self._display.intern_atom(atom_name)
                value = window.get_full_property(atom, 0)
            except Exception:
                value = None
            if value is not None and value.value:
                raw = value.value
                if isinstance(raw, bytes):
                    try:
                        return raw.decode("utf-8", errors="replace")
                    except Exception:
                        return raw.decode(errors="replace")
                return str(raw)
        return ""

    def _get_window_class(self, window) -> str:
        try:
            value = window.get_wm_class()
        except Exception:
            value = None
        if not value:
            return ""
        if isinstance(value, (tuple, list)):
            return " ".join(part for part in value if part)
        return str(value)

    def _get_window_pid(self, window) -> int:
        try:
            atom = self._display.intern_atom("_NET_WM_PID")
            value = window.get_full_property(atom, 0)
            if value and value.value:
                return int(value.value[0])
        except Exception:
            pass
        return 0

    def _get_window_desktop(self, window) -> int:
        try:
            atom = self._display.intern_atom("_NET_WM_DESKTOP")
            value = window.get_full_property(atom, 0)
            if value and value.value:
                return int(value.value[0])
        except Exception:
            pass
        return -1

    def _get_window_geometry(self, window) -> tuple[int, int, int, int]:
        try:
            geom = window.get_geometry()
            return int(geom.x), int(geom.y), int(geom.width), int(geom.height)
        except Exception:
            return 0, 0, 0, 0
