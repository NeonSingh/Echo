"""Echo Session Replay.

Replays a JSONL session recorded by ``input.py``.

Supported events:
    - Active window switches
    - UI Automation based clicks
    - Coordinate based clicks
    - Mouse scrolling
    - Keyboard strokes
    - Key combinations
    - Recorded wait/inactivity periods

The module is reusable:

    from reader import replay_session
    replay_session("Assets/databox/Attendance.jsonl")

It can also be run directly:

    python reader.py Assets/databox/Attendance.jsonl
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pyautogui
import win32api
import win32con
import win32gui
import win32process
from pywinauto import Desktop


logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================

SESSION_FILE = "session_log.jsonl"

ACTION_DELAY = 0.15
WINDOW_TIMEOUT = 10.0
WINDOW_POLL_INTERVAL = 0.2
UI_ELEMENT_RETRY_INTERVAL = 2.0
UI_ELEMENT_ATTEMPTS = 3

APP_DIR = Path(__file__).resolve().parent


# ============================================================================
# REPLAY CONTEXT
# ============================================================================

@dataclass
class ReplayContext:
    """State that belongs to one replay session."""

    active_hwnd: int | None = None


# ============================================================================
# WINDOW ACTIVATION
# ============================================================================


def get_windows() -> list[tuple[int, str]]:
    """Return visible windows that have a non-empty title."""

    windows: list[tuple[int, str]] = []

    def collect(hwnd: int, _lparam) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd).strip()
        if title:
            windows.append((hwnd, title))

    win32gui.EnumWindows(collect, None)
    return windows


def find_window(title: str) -> tuple[int | None, str | None]:
    """Find an exact title first, then a case-insensitive substring match."""

    needle = str(title or "").strip().lower()
    if not needle:
        return None, None

    windows = get_windows()

    for hwnd, window_title in windows:
        if window_title.lower() == needle:
            return hwnd, window_title

    for hwnd, window_title in windows:
        if needle in window_title.lower():
            return hwnd, window_title

    return None, None


def bring_to_foreground(hwnd: int) -> None:
    """Restore/show a window and attempt to make it the foreground window."""

    win32gui.ShowWindow(
        hwnd,
        win32con.SW_RESTORE if win32gui.IsIconic(hwnd) else win32con.SW_SHOW,
    )

    target_tid, _ = win32process.GetWindowThreadProcessId(hwnd)
    current_tid = win32api.GetCurrentThreadId()
    attached = target_tid != current_tid

    if attached:
        try:
            win32process.AttachThreadInput(current_tid, target_tid, True)
        except Exception:
            attached = False

    try:
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            try:
                win32process.AttachThreadInput(current_tid, target_tid, False)
            except Exception:
                pass


def activate_window(title: str) -> int | None:
    """Activate a recorded window and wait until it becomes foreground."""

    hwnd, matched_title = find_window(title)
    if hwnd is None:
        logger.warning("Window not found: %s", title)
        return None

    logger.info("Activating window: %s", matched_title)
    deadline = time.monotonic() + WINDOW_TIMEOUT

    while time.monotonic() < deadline:
        if win32gui.GetForegroundWindow() == hwnd:
            logger.info("Window active: %s", matched_title)
            return hwnd

        try:
            bring_to_foreground(hwnd)
        except Exception as exc:
            logger.debug("Foreground activation failed for %s: %s", matched_title, exc)

        time.sleep(WINDOW_POLL_INTERVAL)

    logger.warning("Timed out waiting for window: %s", matched_title)
    return None


# ============================================================================
# UI AUTOMATION
# ============================================================================


def _matches(element, info: dict) -> bool:
    """Check whether a UIA element matches the recorded identity."""

    try:
        automation_id = str(element.automation_id() or "")
        name = str(element.window_text() or "")
        control_type = str(element.element_info.control_type or "")
        class_name = str(element.class_name() or "")
    except Exception:
        return False

    wanted_id = str(info.get("automation_id") or "")
    wanted_name = str(info.get("name") or "")
    wanted_type = str(info.get("control_type") or "")
    wanted_class = str(info.get("class_name") or "")

    if wanted_id:
        return (
            automation_id == wanted_id
            and (not wanted_type or control_type == wanted_type)
        )

    if wanted_name and name != wanted_name:
        return False
    if wanted_type and control_type != wanted_type:
        return False
    if wanted_class and class_name != wanted_class:
        return False

    return bool(wanted_name or wanted_type or wanted_class)


def find_ui_element(
    hwnd: int,
    info: dict,
    x: int | None = None,
    y: int | None = None,
):
    """Find a recorded UI element using UI Automation, then point lookup."""

    automation_id = str(info.get("automation_id") or "")

    try:
        desktop = Desktop(backend="uia")
        window = desktop.window(handle=hwnd)

        # Fast path: AutomationId is normally the most stable identifier.
        if automation_id:
            try:
                candidates = window.descendants(auto_id=automation_id)
            except Exception:
                candidates = []

            for element in candidates:
                if _matches(element, info):
                    return element

            # Some providers expose the ID but report an unexpected type.
            for element in candidates:
                try:
                    if str(element.automation_id() or "") == automation_id:
                        return element
                except Exception:
                    continue

        # Fallback: scan the window UIA tree.
        try:
            candidates = window.descendants()
        except Exception:
            candidates = []

        for element in candidates:
            if _matches(element, info):
                return element

    except Exception as exc:
        logger.debug("UIA window-tree search failed: %s", exc)

    # Last resort: inspect the element under the recorded point and walk up.
    if x is not None and y is not None:
        try:
            desktop = Desktop(backend="uia")
            element = desktop.from_point(int(x), int(y))

            for _ in range(12):
                if element is None:
                    break

                if _matches(element, info):
                    return element

                try:
                    element = element.parent()
                except Exception:
                    break

        except Exception as exc:
            logger.debug("UIA point lookup failed: %s", exc)

    return None


def click_ui_element(
    hwnd: int,
    info: dict,
    x: int,
    y: int,
) -> bool:
    """Find and click a recorded UI element."""

    for attempt in range(1, UI_ELEMENT_ATTEMPTS + 1):
        element = find_ui_element(hwnd, info, x, y)

        if element is not None:
            try:
                logger.info(
                    "UI click: type=%s name=%r id=%r",
                    info.get("control_type", ""),
                    info.get("name", ""),
                    info.get("automation_id", ""),
                )
                element.click_input()
                return True
            except Exception as exc:
                logger.warning("UI element found but click failed: %s", exc)

        if attempt < UI_ELEMENT_ATTEMPTS:
            logger.info(
                "UI element not ready; retrying in %.1fs (%d/%d)",
                UI_ELEMENT_RETRY_INTERVAL,
                attempt,
                UI_ELEMENT_ATTEMPTS,
            )
            time.sleep(UI_ELEMENT_RETRY_INTERVAL)

    logger.warning("Could not replay recorded UI element")
    return False


# ============================================================================
# KEYBOARD REPLAY
# ============================================================================

SPECIAL_KEYS = {
    "[ENTER]": "enter",
    "[TAB]": "tab",
    "[ESC]": "esc",
    "[BACKSPACE]": "backspace",
    "[SPACE]": "space",
    "[UP]": "up",
    "[DOWN]": "down",
    "[LEFT]": "left",
    "[RIGHT]": "right",
    "[HOME]": "home",
    "[END]": "end",
    "[DELETE]": "delete",
    "[INSERT]": "insert",
    "[PAGEUP]": "pageup",
    "[PAGEDOWN]": "pagedown",
    "[SHIFT]": "shift",
    "[CTRL]": "ctrl",
    "[ALT]": "alt",
    "[CMD]": "win",
}


def convert_key(key: str) -> str:
    """Convert recorded key notation to a pyautogui key name."""

    key = str(key).strip()
    return SPECIAL_KEYS.get(key.upper(), key)


def play_keystrokes(keys) -> None:
    """Replay individual recorded key presses."""

    logger.info("Keys: %s", keys)

    for key in keys:
        pyautogui.press(convert_key(key))


def play_combination(keys) -> None:
    """Replay a recorded key combination."""

    converted = [convert_key(key) for key in keys]

    if len(converted) < 2:
        logger.warning("Invalid key combination: %s", keys)
        return

    try:
        pyautogui.hotkey(*converted)
        logger.info("Hotkey: %s", converted)
    except Exception as exc:
        logger.warning("Key combination failed: %s -> %s", converted, exc)


# ============================================================================
# MOUSE REPLAY
# ============================================================================

CLICK_FUNCS = {
    "LEFT": pyautogui.click,
    "RIGHT": pyautogui.rightClick,
    "MIDDLE": pyautogui.middleClick,
}


def click_mouse(button: str, x: int, y: int) -> None:
    """Replay a coordinate-based mouse click."""

    pyautogui.moveTo(x, y)
    func = CLICK_FUNCS.get(str(button).upper())

    if func is None:
        logger.warning("Unknown mouse button: %s", button)
        return

    func()
    logger.info("Click: %s at (%d, %d)", button, x, y)


def scroll_mouse(
    direction: str,
    amount,
    x: int,
    y: int,
    delta=None,
) -> None:
    """Replay a global Windows mouse-wheel event."""

    pyautogui.moveTo(x, y)
    direction = str(direction).upper()
    amount = max(1, int(amount))

    if delta is None:
        delta = 120 * amount if direction == "UP" else -120 * amount
    else:
        delta = int(delta)

    try:
        win32api.mouse_event(
            win32con.MOUSEEVENTF_WHEEL,
            0,
            0,
            delta,
            0,
        )
        logger.info(
            "Scroll: %s delta=%d at (%d, %d)",
            direction,
            delta,
            x,
            y,
        )
    except Exception as exc:
        logger.warning("Windows scroll failed: %s", exc)


# ============================================================================
# JSONL PARSING / EVENT EXECUTION
# ============================================================================


def parse_line(line: str):
    """Parse one JSON object from the session file."""

    line = line.strip()
    if not line:
        return None

    try:
        return json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Could not parse JSON line: %r", line)
        return None


def execute_event(event: dict, context: ReplayContext) -> None:
    """Execute a single replay event."""

    event_type = event.get("event")

    if event_type in {"session_start", "session_end"}:
        return

    if event_type == "wait":
        duration = max(0.0, float(event.get("duration", 0)))
        logger.info("Wait: %.3fs", duration)
        time.sleep(duration)
        return

    if event_type == "active_window":
        hwnd = activate_window(event.get("title", ""))
        context.active_hwnd = hwnd
        return

    if event_type == "click":
        location = event.get("location") or {}
        x = location.get("x")
        y = location.get("y")

        if x is None or y is None:
            logger.warning("Click has no coordinates")
            return

        if event.get("interactive") is True:
            ui_info = event.get("ui_element")
            hwnd = context.active_hwnd or win32gui.GetForegroundWindow()

            if ui_info and hwnd:
                if not click_ui_element(hwnd, ui_info, int(x), int(y)):
                    logger.warning("UI replay failed; falling back to coordinates")
                    click_mouse(event.get("button", "LEFT"), int(x), int(y))
                return

        click_mouse(event.get("button", "LEFT"), int(x), int(y))
        return

    if event_type == "scroll":
        location = event.get("location") or {}
        x = location.get("x")
        y = location.get("y")

        if x is None or y is None:
            logger.warning("Scroll has no coordinates")
            return

        scroll_mouse(
            event.get("direction", "DOWN"),
            event.get("amount", 1),
            int(x),
            int(y),
            event.get("delta"),
        )
        return

    if event_type == "key_combination":
        play_combination(event.get("keys") or [])
        return

    if event_type == "key_strokes":
        play_keystrokes(event.get("keys") or [])
        return

    logger.warning("Unknown event: %s", event)


# ============================================================================
# SESSION REPLAY
# ============================================================================


def resolve_session_path(filename: str | Path) -> Path:
    """Resolve a supplied session path without changing the saved value."""

    path = Path(filename).expanduser()

    if path.is_absolute():
        return path

    candidates = (
        Path.cwd() / path,
        APP_DIR / path,
        APP_DIR.parent / path,
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    # Return the first conventional path so FileNotFoundError is useful.
    return candidates[0]


def replay_session(filename: str | Path) -> bool:
    """Replay one JSONL session and return ``True`` on successful completion."""

    if not filename:
        raise ValueError("A JSONL session filename is required.")

    session_path = resolve_session_path(filename)
    if not session_path.is_file():
        raise FileNotFoundError(f"Session file not found: {session_path}")

    logger.info("=== SESSION REPLAY START ===")
    logger.info("Session file: %s", session_path)

    context = ReplayContext()

    with session_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            event = parse_line(line)
            if event is None:
                continue

            logger.debug("[%d] %s", line_number, event)
            execute_event(event, context)

            # Wait events already contain their full delay.
            if event.get("event") != "wait":
                time.sleep(ACTION_DELAY)

    logger.info("=== SESSION REPLAY END ===")
    return True


# ============================================================================
# COMMAND-LINE ENTRY POINT
# ============================================================================


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    args = sys.argv[1:] if argv is None else argv

    if not args:
        print("Usage: python reader.py <session_file.jsonl>")
        return 1

    logging.basicConfig(
        level=logging.INFO,
        format="[READER] %(message)s",
    )

    try:
        replay_session(args[0])
    except Exception as exc:
        logger.exception("Session replay failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
