"""Echo Global Input Recorder.

Usage:
    python learn.py attendance_class

Output:
    assets/databox/attendance_class.jsonl

Press ` to stop recording.

The recorder writes to a task-specific temporary JSONL file while recording
and publishes it to <task_name>.jsonl only after all input listeners and the
window-monitor thread have stopped. This avoids Windows file-lock/race issues
that could leave the recorded session unsaved.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from pynput import keyboard, mouse
from pywinauto import Desktop
import win32gui


# ============================================================================
# PATHS
# ============================================================================


def find_project_root() -> Path:
    """Find the project directory containing assets/."""

    current = Path(__file__).resolve().parent

    if (current / "assets").is_dir():
        return current

    for parent in current.parents:
        if (parent / "assets").is_dir():
            return parent

    return current


PROJECT_ROOT = find_project_root()

ASSETS_DIR = PROJECT_ROOT / "assets"
DATABOX_DIR = ASSETS_DIR / "databox"


# ============================================================================
# CONFIGURATION
# ============================================================================

INACTIVITY_THRESHOLD = 4.0
ACTIVE_WINDOW_INTERVAL = 1.0

STOP_KEY = "`"

# The temporary file is task-specific so two recorder processes can never
# accidentally fight over one global session.jsonl file.


# ============================================================================
# TASK NAME
# ============================================================================


def get_task_name() -> str:
    """Get and sanitize the task name from the command line."""

    print(f"[ARGS] {sys.argv}", flush=True)

    if len(sys.argv) < 2:
        print("[WARNING] No task name supplied.", flush=True)
        print("[WARNING] Falling back to session.", flush=True)
        return "session"

    task_name = sys.argv[1].strip()

    if not task_name:
        print("[WARNING] Empty task name supplied.", flush=True)
        return "session"

    # Remove Windows-invalid filename characters.
    task_name = re.sub(r'[<>:"/\\|?*]', "_", task_name)

    # Convert whitespace to underscores.
    task_name = re.sub(r"\s+", "_", task_name)

    # Collapse repeated underscores.
    task_name = re.sub(r"_+", "_", task_name)

    # Remove unsafe leading/trailing characters.
    task_name = task_name.strip(" ._")

    if not task_name:
        return "session"

    print(f"[TASK] Task name: {task_name}", flush=True)
    return task_name


TASK_NAME = get_task_name()


# ============================================================================
# FILE PATHS
# ============================================================================

# The temporary file is hidden/task-specific and is never the final task file.
TEMP_FILE = DATABOX_DIR / f".{TASK_NAME}.recording.tmp.jsonl"
FINAL_FILE = DATABOX_DIR / f"{TASK_NAME}.jsonl"


# ============================================================================
# GLOBAL STATE
# ============================================================================

recording = False
running = True

log_file = None

# RLock is intentional: user_action_started() can acquire state_lock and then
# call record_wait_if_needed(), which may flush pending keys.
log_lock = threading.Lock()
state_lock = threading.RLock()

pending_keys: list[str] = []
held_modifiers: set[str] = set()

last_action_time: float | None = None


# ============================================================================
# LOGGING
# ============================================================================


def write_event(event: dict) -> bool:
    """Write one JSON object to the temporary JSONL file."""

    global log_file

    with log_lock:
        if log_file is None:
            print("[WARNING] log_file is not open.", flush=True)
            return False

        try:
            log_file.write(
                json.dumps(
                    event,
                    ensure_ascii=False,
                )
                + "\n"
            )
            log_file.flush()
            return True

        except Exception as exc:
            print(
                f"[ERROR] Failed to write event: {exc}",
                flush=True,
            )
            return False


def flush_keys() -> None:
    """Save pending normal keyboard strokes."""

    with state_lock:
        if not pending_keys:
            return

        keys = pending_keys.copy()
        pending_keys.clear()

    write_event({
        "event": "key_strokes",
        "keys": keys,
    })


# ============================================================================
# WAIT DETECTION
# ============================================================================


def record_wait_if_needed() -> None:
    global last_action_time

    now = time.monotonic()

    if last_action_time is None:
        last_action_time = now
        return

    inactive = now - last_action_time

    if inactive >= INACTIVITY_THRESHOLD:
        flush_keys()

        write_event({
            "event": "wait",
            "duration": round(inactive, 3),
        })

        print(
            f"[WAIT] {inactive:.2f}s",
            flush=True,
        )

    last_action_time = now


def user_action_started() -> bool:
    with state_lock:
        if not recording:
            return False

        record_wait_if_needed()

    return True


# ============================================================================
# UI AUTOMATION
# ============================================================================


def get_ui_element_at(x, y):
    try:
        desktop = Desktop(backend="uia")
        element = desktop.from_point(int(x), int(y))

        interactive_types = {
            "Button",
            "CheckBox",
            "ComboBox",
            "Edit",
            "Hyperlink",
            "ListItem",
            "MenuItem",
            "RadioButton",
            "Slider",
            "TabItem",
            "TreeItem",
        }

        for _ in range(12):
            if element is None:
                break

            try:
                info = element.element_info

                control_type = str(info.control_type or "")
                name = str(element.window_text() or "")
                automation_id = str(element.automation_id() or "")
                class_name = str(element.class_name() or "")

                if control_type in interactive_types:
                    return {
                        "control_type": control_type,
                        "name": name,
                        "automation_id": automation_id,
                        "class_name": class_name,
                    }

                element = element.parent()

            except Exception:
                break

    except Exception:
        pass

    return None


# ============================================================================
# ACTIVE WINDOW MONITOR
# ============================================================================


def active_window_monitor() -> None:
    previous_title = None

    while running:
        if recording:
            try:
                hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(hwnd)

                if title and title != previous_title:
                    flush_keys()

                    write_event({
                        "event": "active_window",
                        "title": title,
                    })

                    print(
                        f"[WINDOW] {title}",
                        flush=True,
                    )

                    previous_title = title

            except Exception as exc:
                print(
                    "[WARNING] Active window error: "
                    f"{exc}",
                    flush=True,
                )

        else:
            previous_title = None

        time.sleep(ACTIVE_WINDOW_INTERVAL)


# ============================================================================
# MOUSE
# ============================================================================


def on_click(x, y, button, pressed):
    if not pressed:
        return

    if not user_action_started():
        return

    flush_keys()

    ui_element = get_ui_element_at(x, y)

    write_event({
        "event": "click",
        "button": button.name.upper(),
        "interactive": ui_element is not None,
        "ui_element": ui_element,
        "location": {
            "x": int(x),
            "y": int(y),
        },
    })

    print(
        "[CLICK] "
        f"{button.name.upper()} "
        f"at ({int(x)}, {int(y)})",
        flush=True,
    )


def on_scroll(x, y, dx, dy):
    if not user_action_started():
        return

    flush_keys()

    direction = "UP" if dy > 0 else "DOWN"

    amount = max(
        1,
        abs(int(dy)),
    )

    delta = (
        120 * amount
        if direction == "UP"
        else -120 * amount
    )

    write_event({
        "event": "scroll",
        "direction": direction,
        "amount": amount,
        "delta": delta,
        "location": {
            "x": int(x),
            "y": int(y),
        },
    })

    print(
        "[SCROLL] "
        f"{direction} "
        f"amount={amount} "
        f"at ({int(x)}, {int(y)})",
        flush=True,
    )


# ============================================================================
# KEYBOARD
# ============================================================================

MODIFIER_KEYS = {
    keyboard.Key.shift: "[SHIFT]",
    keyboard.Key.shift_l: "[SHIFT]",
    keyboard.Key.shift_r: "[SHIFT]",
    keyboard.Key.ctrl: "[CTRL]",
    keyboard.Key.ctrl_l: "[CTRL]",
    keyboard.Key.ctrl_r: "[CTRL]",
    keyboard.Key.alt: "[ALT]",
    keyboard.Key.alt_l: "[ALT]",
    keyboard.Key.alt_r: "[ALT]",
    keyboard.Key.cmd: "[CMD]",
    keyboard.Key.cmd_l: "[CMD]",
    keyboard.Key.cmd_r: "[CMD]",
}

SPECIAL_KEYS = {
    keyboard.Key.enter: "[ENTER]",
    keyboard.Key.tab: "[TAB]",
    keyboard.Key.esc: "[ESC]",
    keyboard.Key.backspace: "[BACKSPACE]",
    keyboard.Key.space: "[SPACE]",
    keyboard.Key.up: "[UP]",
    keyboard.Key.down: "[DOWN]",
    keyboard.Key.left: "[LEFT]",
    keyboard.Key.right: "[RIGHT]",
    keyboard.Key.home: "[HOME]",
    keyboard.Key.end: "[END]",
    keyboard.Key.delete: "[DELETE]",
    keyboard.Key.insert: "[INSERT]",
    keyboard.Key.page_up: "[PAGEUP]",
    keyboard.Key.page_down: "[PAGEDOWN]",
}


def key_to_text(key):
    if key in SPECIAL_KEYS:
        return SPECIAL_KEYS[key]

    try:
        if key.char is not None:
            char = key.char

            if ord(char) < 32:
                return chr(ord(char) + 96)

            return char

    except AttributeError:
        pass

    return str(key).replace("Key.", "").upper()


# ============================================================================
# STOP
# ============================================================================


def is_stop_key(key) -> bool:
    try:
        return key.char == STOP_KEY
    except AttributeError:
        return False


def stop_and_exit() -> None:
    """Request shutdown; final file publishing is done by main()."""

    global running

    print(
        "[STOP KEY] ` pressed. Stopping listeners...",
        flush=True,
    )

    # IMPORTANT:
    # Do not close/rename the file from inside pynput's keyboard callback.
    # The callback itself is still executing and other listener threads may
    # still be active. main() will stop and join all listeners first, then
    # close and publish the file safely.
    running = False


def on_press(key):
    # Stop key.
    if is_stop_key(key):
        stop_and_exit()
        return False

    if not recording:
        return

    # Modifier.
    if key in MODIFIER_KEYS:
        with state_lock:
            held_modifiers.add(MODIFIER_KEYS[key])
        return

    key_text = key_to_text(key)

    if not user_action_started():
        return

    with state_lock:
        modifiers = list(held_modifiers)

    if modifiers:
        flush_keys()

        combination = modifiers + [key_text]

        write_event({
            "event": "key_combination",
            "keys": combination,
        })

        print(
            f"[HOTKEY] {combination}",
            flush=True,
        )

        return

    with state_lock:
        pending_keys.append(key_text)


def on_release(key):
    if key in MODIFIER_KEYS:
        with state_lock:
            held_modifiers.discard(MODIFIER_KEYS[key])


# ============================================================================
# FILE FINALIZATION
# ============================================================================


def close_recording_file() -> None:
    """Flush, fsync and close the recording file."""

    global log_file

    with log_lock:
        if log_file is None:
            return

        try:
            log_file.flush()
        except Exception:
            pass

        try:
            os.fsync(log_file.fileno())
        except Exception:
            pass

        try:
            log_file.close()
        except Exception as exc:
            print(
                f"[WARNING] Failed to close recording file: {exc}",
                flush=True,
            )

        log_file = None


def finalize_recording_file() -> bool:
    """Atomically publish the temporary recording as <task_name>.jsonl."""

    try:
        if not TEMP_FILE.exists():
            print(
                "[ERROR] Temporary recording file does not exist.",
                flush=True,
            )
            print(f"[ERROR] Expected: {TEMP_FILE}", flush=True)
            return False

        if TEMP_FILE.stat().st_size == 0:
            print(
                "[ERROR] Temporary recording file is empty.",
                flush=True,
            )
            return False

        print("[RENAME] Publishing recording:", flush=True)
        print(f"         {TEMP_FILE}", flush=True)
        print("      ->", flush=True)
        print(f"         {FINAL_FILE}", flush=True)

        # os.replace() is atomic on the same filesystem and replaces an
        # existing target without the separate unlink/rename race.
        os.replace(
            str(TEMP_FILE),
            str(FINAL_FILE),
        )

        if not FINAL_FILE.exists():
            print(
                "[ERROR] Publish completed but target cannot be found.",
                flush=True,
            )
            return False

        size = FINAL_FILE.stat().st_size

        if size == 0:
            print(
                "[ERROR] Final recording file is empty.",
                flush=True,
            )
            return False

        print("[SUCCESS] Recording saved.", flush=True)
        print(f"[SAVED] {FINAL_FILE}", flush=True)
        print(f"[SAVED] Size: {size} bytes", flush=True)

        return True

    except PermissionError as exc:
        print(
            "[ERROR] Windows denied access while publishing the recording.",
            flush=True,
        )
        print(
            f"        {exc}",
            flush=True,
        )
        print(
            "[ERROR] The temporary file has been kept so the recording is not lost:",
            flush=True,
        )
        print(f"        {TEMP_FILE}", flush=True)
        return False

    except OSError as exc:
        print(
            "[ERROR] Failed to publish recording:",
            flush=True,
        )
        print(f"        {exc}", flush=True)
        print(
            "[ERROR] Temporary recording remains at:",
            flush=True,
        )
        print(f"        {TEMP_FILE}", flush=True)
        return False

    except Exception as exc:
        print(
            "[ERROR] Unexpected finalization error:",
            flush=True,
        )
        print(f"        {exc}", flush=True)
        return False


# ============================================================================
# RECORDING
# ============================================================================


def start_recording() -> bool:
    global recording
    global log_file
    global last_action_time

    with state_lock:
        if recording:
            return True

    try:
        DATABOX_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )
    except Exception as exc:
        print(
            "[FATAL] Cannot create databox directory:",
            flush=True,
        )
        print(f"        {DATABOX_DIR}", flush=True)
        print(f"        {exc}", flush=True)
        return False

    # Remove only this task's stale temporary file.
    if TEMP_FILE.exists():
        print(
            f"[CLEANUP] Removing old temporary file: {TEMP_FILE}",
            flush=True,
        )

        try:
            TEMP_FILE.unlink()
        except Exception as exc:
            print(
                "[FATAL] Cannot remove old temporary file:",
                flush=True,
            )
            print(f"        {exc}", flush=True)
            return False

    try:
        log_file = open(
            TEMP_FILE,
            "w",
            encoding="utf-8",
            buffering=1,
        )
    except Exception as exc:
        print(
            "[FATAL] Cannot create temporary recording file:",
            flush=True,
        )
        print(f"        {TEMP_FILE}", flush=True)
        print(f"        {exc}", flush=True)
        log_file = None
        return False

    try:
        if not TEMP_FILE.exists():
            raise OSError(
                "Temporary file was opened but cannot be found."
            )
    except Exception as exc:
        print(
            "[FATAL] Temporary recording file verification failed:",
            flush=True,
        )
        print(f"        {exc}", flush=True)
        close_recording_file()
        return False

    with state_lock:
        recording = True
        last_action_time = time.monotonic()
        pending_keys.clear()
        held_modifiers.clear()

    if not write_event({
        "event": "session_start",
        "task_name": TASK_NAME,
    }):
        with state_lock:
            recording = False
        close_recording_file()
        return False

    print("========================================", flush=True)
    print(" Echo Recorder", flush=True)
    print(f" Task: {TASK_NAME}", flush=True)
    print(f" Temporary file: {TEMP_FILE}", flush=True)
    print(f" Final file:     {FINAL_FILE}", flush=True)
    print(f" Exists: {TEMP_FILE.exists()}", flush=True)
    print(" Recording started.", flush=True)
    print(" Press ` to stop.", flush=True)
    print("========================================", flush=True)

    return True


def stop_recording() -> bool:
    global recording
    global last_action_time

    with state_lock:
        if not recording:
            return FINAL_FILE.exists()

        # Prevent any new callbacks from entering the write path once
        # finalization starts. Listeners have already been stopped/joined by
        # main() at this point.
        recording = False

    flush_keys()

    # Record a meaningful trailing inactivity period before the session end.
    if last_action_time is not None:
        inactive = time.monotonic() - last_action_time

        if inactive >= INACTIVITY_THRESHOLD:
            write_event({
                "event": "wait",
                "duration": round(inactive, 3),
            })

    write_event({
        "event": "session_end",
    })

    with state_lock:
        last_action_time = None
        pending_keys.clear()
        held_modifiers.clear()

    close_recording_file()

    if not TEMP_FILE.exists():
        print(
            "[ERROR] Temporary file disappeared before finalization.",
            flush=True,
        )
        return False

    temp_size = TEMP_FILE.stat().st_size

    print(
        f"[TEMP] Recording closed: {TEMP_FILE}",
        flush=True,
    )
    print(
        f"[TEMP] Size: {temp_size} bytes",
        flush=True,
    )

    success = finalize_recording_file()

    if not success:
        print(
            "[ERROR] Recording was not published and remains available at:",
            flush=True,
        )
        print(f"        {TEMP_FILE}", flush=True)

    return success


# ============================================================================
# MAIN
# ============================================================================


def main() -> int:
    global running

    print("[START] Echo recorder launching...", flush=True)
    print(f"[ARGS] {sys.argv}", flush=True)
    print(f"[PROJECT] {PROJECT_ROOT}", flush=True)
    print(f"[DATABOX] {DATABOX_DIR}", flush=True)
    print(f"[TASK] {TASK_NAME}", flush=True)
    print(f"[TEMP] {TEMP_FILE}", flush=True)
    print(f"[FINAL] {FINAL_FILE}", flush=True)

    if not start_recording():
        return 1

    # Keep references in main so they can be stopped/joined deterministically.
    window_thread = threading.Thread(
        target=active_window_monitor,
        daemon=True,
        name="EchoActiveWindowMonitor",
    )

    keyboard_listener = keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
    )

    mouse_listener = mouse.Listener(
        on_click=on_click,
        on_scroll=on_scroll,
    )

    try:
        window_thread.start()
        keyboard_listener.start()
        mouse_listener.start()

        print(
            "[READY] Global listeners started.",
            flush=True,
        )

        while running:
            time.sleep(0.1)

    except KeyboardInterrupt:
        print(
            "[INFO] KeyboardInterrupt received.",
            flush=True,
        )

    finally:
        # --------------------------------------------------------------
        # 1. Stop producers first.
        # --------------------------------------------------------------
        running = False

        try:
            keyboard_listener.stop()
        except Exception:
            pass

        try:
            mouse_listener.stop()
        except Exception:
            pass

        # --------------------------------------------------------------
        # 2. Wait for pynput callbacks to finish.
        # --------------------------------------------------------------
        try:
            keyboard_listener.join(timeout=2.0)
        except Exception:
            pass

        try:
            mouse_listener.join(timeout=2.0)
        except Exception:
            pass

        # --------------------------------------------------------------
        # 3. Stop and join the active-window monitor.
        # --------------------------------------------------------------
        try:
            window_thread.join(timeout=2.0)
        except Exception:
            pass

        # --------------------------------------------------------------
        # 4. ONLY NOW close and publish the JSONL file.
        # --------------------------------------------------------------
        if recording:
            stop_recording()

        print(
            "[EXIT] Echo recorder closed.",
            flush=True,
        )

    return 0


# ============================================================================
# ENTRY POINT
# ============================================================================


if __name__ == "__main__":
    sys.exit(main())
