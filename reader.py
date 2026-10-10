"""
Echo Session Replay
===================

Replays a JSONL session recorded by input.py.

Supports:
    - Active window switches
    - UI Automation based clicks
    - Coordinate based clicks
    - Mouse scrolling
    - Keyboard strokes
    - Key combinations
    - Recorded wait/inactivity periods

Can be used in two ways:

    1. From another Python module:

        from reader import replay_session
        replay_session("Assets/databox/Attendance.jsonl")

    2. Directly from the terminal:

        python reader.py Assets/databox/Attendance.jsonl

If no file is supplied when run directly, SESSION_FILE is used.
"""

from __future__ import annotations

import json
import sys
import time

import pyautogui
import win32gui
import win32con
import win32api
import win32process

from pywinauto import Desktop


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SESSION_FILE = "session_log.jsonl"

ACTION_DELAY = 0.15
WINDOW_TIMEOUT = 10
WINDOW_POLL_INTERVAL = 0.2
UI_ELEMENT_RETRY_INTERVAL = 2
UI_ELEMENT_ATTEMPTS = 3


# --------------------------------------------------------------------------
# Window activation
# --------------------------------------------------------------------------

def get_windows():
    """Return all visible windows with titles."""
    windows = []

    def collect(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)

            if title:
                windows.append(
                    (hwnd, title)
                )

    win32gui.EnumWindows(
        collect,
        None,
    )

    return windows


def find_window(title):
    """Find exact title first, then substring match."""
    needle = title.strip().lower()

    for hwnd, window_title in get_windows():
        if window_title.strip().lower() == needle:
            return hwnd, window_title

    for hwnd, window_title in get_windows():
        if needle in window_title.lower():
            return hwnd, window_title

    return None, None


def bring_to_foreground(hwnd):
    """Try to bring a window to the foreground."""

    win32gui.ShowWindow(
        hwnd,
        (
            win32con.SW_RESTORE
            if win32gui.IsIconic(hwnd)
            else win32con.SW_SHOW
        ),
    )

    target_tid, _ = (
        win32process.GetWindowThreadProcessId(hwnd)
    )

    current_tid = (
        win32api.GetCurrentThreadId()
    )

    attached = target_tid != current_tid

    if attached:
        try:
            win32process.AttachThreadInput(
                current_tid,
                target_tid,
                True,
            )
        except Exception:
            attached = False

    try:
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)

    finally:
        if attached:
            try:
                win32process.AttachThreadInput(
                    current_tid,
                    target_tid,
                    False,
                )
            except Exception:
                pass


def activate_window(title):
    """Activate a recorded window and wait until it is foreground."""

    hwnd, matched_title = find_window(title)

    if hwnd is None:
        print(
            f"[WARNING] Window not found: {title}"
        )
        return None

    print(
        f"[WINDOW] Activating: {matched_title}"
    )

    deadline = (
        time.time()
        + WINDOW_TIMEOUT
    )

    while time.time() < deadline:

        if (
            win32gui.GetForegroundWindow()
            == hwnd
        ):
            print(
                f"[WINDOW] Active: {matched_title}"
            )
            return hwnd

        bring_to_foreground(hwnd)

        time.sleep(
            WINDOW_POLL_INTERVAL
        )

    print(
        "[WARNING] Timed out waiting for "
        f"window: {matched_title}"
    )

    return None


# --------------------------------------------------------------------------
# UI Automation
# --------------------------------------------------------------------------

def _matches(element, info):
    """Check whether a UIA element matches the recorded identity."""

    try:
        automation_id = str(
            element.automation_id() or ""
        )

        name = str(
            element.window_text() or ""
        )

        control_type = str(
            element.element_info.control_type
            or ""
        )

        class_name = str(
            element.class_name() or ""
        )

    except Exception:
        return False

    wanted_id = str(
        info.get("automation_id") or ""
    )

    wanted_name = str(
        info.get("name") or ""
    )

    wanted_type = str(
        info.get("control_type") or ""
    )

    wanted_class = str(
        info.get("class_name") or ""
    )

    if wanted_id:

        if automation_id != wanted_id:
            return False

        if (
            wanted_type
            and control_type != wanted_type
        ):
            return False

        return True

    if (
        wanted_name
        and name != wanted_name
    ):
        return False

    if (
        wanted_type
        and control_type != wanted_type
    ):
        return False

    if (
        wanted_class
        and class_name != wanted_class
    ):
        return False

    return bool(
        wanted_name
        or wanted_type
        or wanted_class
    )


def find_ui_element(
    hwnd,
    info,
    x=None,
    y=None,
):
    """Find a recorded UI element using UI Automation."""

    automation_id = str(
        info.get("automation_id") or ""
    )

    try:
        desktop = Desktop(
            backend="uia"
        )

        window = desktop.window(
            handle=hwnd
        )

        # First search by AutomationId.
        if automation_id:

            try:
                candidates = (
                    window.descendants(
                        auto_id=automation_id
                    )
                )

            except Exception:
                candidates = []

            for element in candidates:

                if _matches(
                    element,
                    info,
                ):
                    return element

            # Some providers expose the AutomationId
            # but report another control type.
            for element in candidates:

                try:

                    if (
                        str(
                            element.automation_id()
                            or ""
                        )
                        == automation_id
                    ):
                        return element

                except Exception:
                    pass

        # Search entire UIA tree.
        try:
            candidates = (
                window.descendants()
            )

        except Exception:
            candidates = []

        for element in candidates:

            if _matches(
                element,
                info,
            ):
                return element

    except Exception as e:

        print(
            f"[UIA] Window-tree search failed: {e}"
        )

    # Last resort: inspect recorded coordinates.
    if x is not None and y is not None:

        try:

            desktop = Desktop(
                backend="uia"
            )

            element = desktop.from_point(
                int(x),
                int(y),
            )

            for _ in range(12):

                if element is None:
                    break

                if _matches(
                    element,
                    info,
                ):
                    return element

                try:
                    element = element.parent()

                except Exception:
                    break

        except Exception as e:

            print(
                f"[UIA] Point lookup failed: {e}"
            )

    return None


def click_ui_element(
    hwnd,
    info,
    x,
    y,
):
    """Find and click a recorded UI element."""

    for attempt in range(
        1,
        UI_ELEMENT_ATTEMPTS + 1,
    ):

        element = find_ui_element(
            hwnd,
            info,
            x,
            y,
        )

        if element is not None:

            try:

                print(
                    "[UI CLICK] "
                    f"type={info.get('control_type', '')} "
                    f"name='{info.get('name', '')}' "
                    f"id='{info.get('automation_id', '')}'"
                )

                element.click_input()

                return True

            except Exception as e:

                print(
                    "[UIA] Element found, "
                    f"but click failed: {e}"
                )

        if attempt < UI_ELEMENT_ATTEMPTS:

            print(
                "[UIA] Element not ready. "
                f"Waiting {UI_ELEMENT_RETRY_INTERVAL}s "
                f"(attempt {attempt}/"
                f"{UI_ELEMENT_ATTEMPTS})..."
            )

            time.sleep(
                UI_ELEMENT_RETRY_INTERVAL
            )

    print(
        "[UIA] Could not replay "
        "recorded UI element."
    )

    return False


# --------------------------------------------------------------------------
# Keyboard replay
# --------------------------------------------------------------------------

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


def convert_key(key):
    key = str(key).strip()

    return SPECIAL_KEYS.get(
        key.upper(),
        key,
    )


def play_keystrokes(keys):
    print(
        f"[KEYS] {keys}"
    )

    for key in keys:
        pyautogui.press(
            convert_key(key)
        )


def play_combination(keys):
    """Replay a recorded key combination reliably."""

    converted = [
        convert_key(key)
        for key in keys
    ]

    if len(converted) < 2:

        print(
            "[WARNING] Invalid key "
            f"combination: {keys}"
        )

        return

    modifiers = {
        "ctrl",
        "shift",
        "alt",
        "win",
    }

    held = []

    try:

        for key in converted[:-1]:

            if key.lower() in modifiers:

                pyautogui.keyDown(
                    key.lower()
                )

                held.append(
                    key.lower()
                )

            else:

                pyautogui.keyDown(key)

                held.append(key)

        main_key = converted[-1]

        if len(main_key) == 1:
            main_key = main_key.lower()

        pyautogui.press(
            main_key
        )

        print(
            f"[HOTKEY] {converted}"
        )

    except Exception as e:

        print(
            "[WARNING] Key combination "
            f"failed: {converted} -> {e}"
        )

    finally:

        for key in reversed(held):

            try:
                pyautogui.keyUp(key)

            except Exception:
                pass


# --------------------------------------------------------------------------
# Mouse replay
# --------------------------------------------------------------------------

CLICK_FUNCS = {
    "LEFT": pyautogui.click,
    "RIGHT": pyautogui.rightClick,
    "MIDDLE": pyautogui.middleClick,
}


def click_mouse(
    button,
    x,
    y,
):
    pyautogui.moveTo(
        x,
        y,
    )

    func = CLICK_FUNCS.get(
        button.upper()
    )

    if func is None:

        print(
            "[WARNING] Unknown mouse "
            f"button: {button}"
        )

        return

    func()

    print(
        f"[CLICK] {button} "
        f"at ({x}, {y})"
    )


def scroll_mouse(
    direction,
    amount,
    x,
    y,
    delta=None,
):
    """Replay a global Windows mouse-wheel event."""

    pyautogui.moveTo(
        x,
        y,
    )

    direction = direction.upper()

    amount = max(
        1,
        int(amount),
    )

    if delta is None:

        delta = (
            120 * amount
            if direction == "UP"
            else -120 * amount
        )

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

        print(
            f"[SCROLL] {direction} "
            f"delta={delta} "
            f"at ({x}, {y})"
        )

    except Exception as e:

        print(
            "[WARNING] Windows scroll "
            f"failed: {e}"
        )


# --------------------------------------------------------------------------
# JSONL parsing
# --------------------------------------------------------------------------

def parse_line(line):
    """Parse one JSON object from the session file."""

    line = line.strip()

    if not line:
        return None

    try:

        return json.loads(line)

    except json.JSONDecodeError:

        print(
            f"[WARNING] Could not parse JSON: {line}"
        )

        return None


# --------------------------------------------------------------------------
# Event execution
# --------------------------------------------------------------------------

def execute_event(event):
    event_type = event.get(
        "event"
    )

    if event_type in (
        "session_start",
        "session_end",
    ):
        return

    if event_type == "wait":

        duration = max(
            0.0,
            float(
                event.get(
                    "duration",
                    0,
                )
            ),
        )

        print(
            f"[WAIT] {duration:.3f}s"
        )

        time.sleep(duration)

        return

    if event_type == "active_window":

        return activate_window(
            event["title"]
        )

    if event_type == "click":

        location = event.get(
            "location",
            {},
        )

        x = location.get("x")
        y = location.get("y")

        if x is None or y is None:

            print(
                "[WARNING] Click has "
                "no coordinates."
            )

            return

        if event.get(
            "interactive"
        ) is True:

            ui_info = event.get(
                "ui_element"
            )

            if ui_info:

                hwnd = (
                    win32gui.GetForegroundWindow()
                )

                if not click_ui_element(
                    hwnd,
                    ui_info,
                    x,
                    y,
                ):

                    print(
                        "[WARNING] UI replay "
                        "failed. Using coordinates."
                    )

                    click_mouse(
                        event["button"],
                        x,
                        y,
                    )

                return

        click_mouse(
            event["button"],
            x,
            y,
        )

        return

    if event_type == "scroll":

        location = event.get(
            "location",
            {},
        )

        x = location.get("x")
        y = location.get("y")

        if x is None or y is None:

            print(
                "[WARNING] Scroll has "
                "no coordinates."
            )

            return

        scroll_mouse(
            event["direction"],
            event.get(
                "amount",
                1,
            ),
            x,
            y,
            event.get("delta"),
        )

        return

    if event_type == "key_combination":

        play_combination(
            event["keys"]
        )

        return

    if event_type == "key_strokes":

        play_keystrokes(
            event["keys"]
        )

        return

    print(
        f"[WARNING] Unknown event: {event}"
    )


# --------------------------------------------------------------------------
# Session replay
# --------------------------------------------------------------------------

def replay_session(filename):
    """
    Replay the specified JSONL session.

    This is the function base.py will call.

    Example:

        replay_session(
            "Assets/databox/Attendance.jsonl"
        )
    """

    if not filename:
        raise ValueError(
            "A JSONL session filename is required."
        )

    print(
        "\n=== SESSION REPLAY START ==="
    )

    print(
        f"[READER] Session file: {filename}"
    )

    with open(
        filename,
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            event = parse_line(
                line
            )

            if event is None:
                continue

            print(
                f"[{line_number}] {event}"
            )

            execute_event(
                event
            )

            # Wait events already contain
            # their complete delay.
            if (
                event.get("event")
                != "wait"
            ):
                time.sleep(
                    ACTION_DELAY
                )

    print(
        "\n=== SESSION REPLAY END ===\n"
    )


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

if __name__ == "__main__":

    
    import sys

    if len(sys.argv) < 2:
        print("Usage: python reader.py <session_file.jsonl>")
        sys.exit(1)

    session_file = sys.argv[1]

    print("Session file:", session_file)
    print("Starting in 3 seconds...")
    time.sleep(3)

    replay_session(session_file)