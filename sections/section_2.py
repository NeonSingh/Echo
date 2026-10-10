"""
'New' tab.

Task creation interface:
- Task name
- Description
- Tags
- Recording status
- Teach button
- Add button
- Clear button

Tasks are stored in:

    assets/data/user_saved_tasks.txt

The file contains a JSON array in the form:

[
    {
        "name": "Cyberpunk",
        "description": "2077 is cooked",
        "tags": [
            "steam",
            "game"
        ],
        "metadata_loc": "Cyberpunk.txt"
    }
]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    Signal,
    QTimer,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QPushButton,
    QFrame,
)


# ============================================================
# PATHS
# ============================================================

APP_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = (
    APP_DIR
    / "assets"
    / "images"
)

DATA_DIR = (
    APP_DIR
    / "assets"
    / "data"
)

TASKS_FILE = (
    DATA_DIR
    / "user_saved_tasks.txt"
)

LEARN_FILE = (
    APP_DIR
    / "learn.py"
)


# ============================================================
# UI COLORS
# ============================================================

TITLE_COLOR = "#B7BBC5"
TEXT_COLOR = "#9FA5B1"
PLACEHOLDER_COLOR = "#C5CBD6"
BORDER_COLOR = "#D4D9E2"

TAG_BG = "#F8F9FB"
TAG_BORDER = "#D6DCE6"

BUTTON_BG = "#242424"
BUTTON_TEXT = "#FFFFFF"

INPUT_TEXT = "#222222"

RECORDING_RED = "#C92C2C"
RECORDING_GREEN = "#25A35A"


# ============================================================
# RECORDING STATES
# ============================================================

STATE_NOT_RECORDING = "not_recording"
STATE_RECORDING = "recording"
STATE_RECORDED = "recorded"


# ============================================================
# CHECK INDICATOR
# ============================================================

class CheckIndicator(QLabel):
    """
    Displays unchecked.png when the related field is empty and
    checked.png when the related field contains user input.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedSize(18, 18)

        self.checked_pixmap = QPixmap(
            str(ASSETS_DIR / "checked.png")
        )

        self.unchecked_pixmap = QPixmap(
            str(ASSETS_DIR / "unchecked.png")
        )

        self.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
            }
        """)

        self.set_checked(False)

    def set_checked(self, checked: bool):
        pixmap = (
            self.checked_pixmap
            if checked
            else self.unchecked_pixmap
        )

        if pixmap.isNull():
            self.clear()
            return

        self.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def bind_to(self, widget):

        if isinstance(widget, QLineEdit):

            def update(text):
                self.set_checked(
                    bool(text.strip())
                )

            widget.textChanged.connect(update)

            update(widget.text())

        elif isinstance(widget, QTextEdit):

            def update():
                self.set_checked(
                    bool(
                        widget.toPlainText().strip()
                    )
                )

            widget.textChanged.connect(update)

            update()


# ============================================================
# TAG CHIP
# ============================================================

class TagChip(QFrame):
    """Rounded tag chip with a remove button."""

    removed = Signal(str)

    def __init__(
        self,
        text: str,
        parent=None,
    ):
        super().__init__(parent)

        self.tag_text = text

        self.setFixedHeight(32)

        self.setStyleSheet(f"""
            QFrame {{
                background: {TAG_BG};
                border: 1px solid {TAG_BORDER};
                border-radius: 14px;
            }}
        """)

        layout = QHBoxLayout(self)

        layout.setContentsMargins(
            10,
            0,
            7,
            0,
        )

        layout.setSpacing(6)

        label = QLabel(text)

        label.setStyleSheet("""
            QLabel {
                color: #4E535C;
                background: transparent;
                border: none;
                font-size: 11px;
            }
        """)

        remove_btn = QPushButton("×")

        remove_btn.setFixedSize(
            14,
            14,
        )

        remove_btn.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        remove_btn.setStyleSheet("""
            QPushButton {
                color: #A7ADB7;
                background: transparent;
                border: none;
                padding: 0px;
                font-size: 12px;
            }

            QPushButton:hover {
                color: #666666;
            }

            QPushButton:pressed {
                color: #444444;
            }
        """)

        remove_btn.clicked.connect(
            lambda: self.removed.emit(
                self.tag_text
            )
        )

        layout.addWidget(label)
        layout.addWidget(remove_btn)


# ============================================================
# TAG EDITOR
# ============================================================

class TagEditor(QFrame):
    """
    Interactive tag editor.

    Type a word or sentence and press Enter to create a tag.
    Existing tags can be removed individually.
    """

    tags_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.tags = []
        self.chips = {}

        self.setFixedHeight(50)

        self.setStyleSheet("""
            QFrame {
                background: #FFFFFF;
                border: 1px solid #BABEC4;
                border-radius: 14px;
            }
        """)

        self.layout = QHBoxLayout(self)

        self.layout.setContentsMargins(
            8,
            8,
            8,
            8,
        )

        self.layout.setSpacing(6)

        self.input = QLineEdit()

        self.input.setPlaceholderText(
            "Add tag..."
        )

        self.input.setMinimumWidth(80)

        self.input.setStyleSheet("""
            QLineEdit {
                background: transparent;
                color: #222222;
                border: none;
                padding: 0px 4px;
                font-size: 11px;
            }

            QLineEdit::placeholder {
                color: #AAB0BA;
            }

            QLineEdit:focus {
                border: none;
                outline: none;
            }
        """)

        self.input.returnPressed.connect(
            self._add_tag
        )

        self.layout.addWidget(
            self.input,
            stretch=1,
        )

    def _add_tag(self):
        text = self.input.text().strip()

        if not text:
            return

        if text in self.tags:
            self.input.clear()
            return

        self.tags.append(text)

        chip = TagChip(
            text,
            self,
        )

        chip.removed.connect(
            self._remove_tag
        )

        self.chips[text] = chip

        self.layout.insertWidget(
            self.layout.count() - 1,
            chip,
        )

        self.input.clear()

        self.tags_changed.emit(
            bool(self.tags)
        )

    def _remove_tag(self, text):
        if text not in self.tags:
            return

        self.tags.remove(text)

        chip = self.chips.pop(
            text,
            None,
        )

        if chip is not None:
            chip.deleteLater()

        self.tags_changed.emit(
            bool(self.tags)
        )

    def clear_tags(self):
        """Remove every existing tag."""

        for text in list(self.tags):

            chip = self.chips.pop(
                text,
                None,
            )

            if chip is not None:
                chip.deleteLater()

        self.tags.clear()

        self.input.clear()

        self.tags_changed.emit(False)

    def get_tags(self):
        return list(self.tags)


# ============================================================
# COUNTDOWN WIDGET
# ============================================================

class CountdownWidget(QWidget):
    """
    Independent frameless 3 -> 2 -> 1 countdown.

    This widget deliberately has no parent so it is independent
    from the minimized main application window.
    """

    finished = Signal()

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.setFixedSize(
            150,
            150,
        )

        self.number = 3

        self.label = QLabel(
            str(self.number),
            self,
        )

        self.label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.label.setGeometry(
            self.rect()
        )

        self.label.setStyleSheet("""
            QLabel {
                background: #00171D;
                color: white;
                border-radius: 75px;
                font-size: 64px;
                font-weight: 800;
            }
        """)

        self.timer = QTimer(self)

        self.timer.timeout.connect(
            self._next
        )

    def start(self):

        screen = QApplication.primaryScreen()

        if screen is not None:

            geometry = (
                screen.availableGeometry()
            )

            self.move(
                geometry.x()
                + (
                    geometry.width()
                    - self.width()
                ) // 2,

                geometry.y()
                + (
                    geometry.height()
                    - self.height()
                ) // 2,
            )

        self.show()
        self.raise_()
        self.activateWindow()

        QApplication.processEvents()

        self.timer.start(1000)

    def _next(self):

        self.number -= 1

        if self.number <= 0:

            self.timer.stop()
            self.close()

            self.finished.emit()

            return

        self.label.setText(
            str(self.number)
        )

    def closeEvent(self, event):

        self.timer.stop()

        event.accept()


# ============================================================
# NEW SECTION
# ============================================================

class NewSection(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.learn_process = None
        self.countdown = None
        self._process_timer = None

        # ========================================================
        # ROOT
        # ========================================================

        root = QVBoxLayout(self)

        root.setContentsMargins(
            50,
            30,
            90,
            18,
        )

        root.setSpacing(10)

        # ========================================================
        # TASK NAME
        # ========================================================

        name_row = QHBoxLayout()

        name_row.setContentsMargins(
            0,
            0,
            120,
            0,
        )

        name_row.setSpacing(8)

        self.name_check = CheckIndicator()

        self.task_name = QLineEdit()

        self.task_name.setPlaceholderText(
            "Task Name"
        )

        self.task_name.setFixedHeight(
            44
        )

        self.task_name.setStyleSheet(f"""
            QLineEdit {{
                background: #EBEBEB;
                color: {INPUT_TEXT};
                border: none;
                border-bottom: 2px solid {BORDER_COLOR};
                border-radius: 0px;
                padding: 0px 10px;
                font-size: 35px;
                font-weight: 700;
            }}

            QLineEdit::placeholder {{
                color: {TITLE_COLOR};
            }}

            QLineEdit:focus {{
                background: #EBEBEB;
                color: #111111;
                border-bottom: 2px solid #9FA5B1;
            }}
        """)

        self.name_check.bind_to(
            self.task_name
        )

        name_row.addWidget(
            self.name_check,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        name_row.addWidget(
            self.task_name,
            stretch=1,
        )

        root.addLayout(
            name_row
        )

        # ========================================================
        # DESCRIPTION
        # ========================================================

        description_row = QHBoxLayout()

        description_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        description_row.setSpacing(8)

        self.description_check = CheckIndicator()

        self.description = QTextEdit()

        self.description.setPlaceholderText(
            "Description"
        )

        self.description.setFixedHeight(
            125
        )

        self.description.setStyleSheet(f"""
            QTextEdit {{
                background: #FFFFFF;
                color: {INPUT_TEXT};
                border: 1px solid {BORDER_COLOR};
                border-radius: 14px;
                padding: 12px 14px;
                font-size: 13px;
            }}

            QTextEdit::placeholder {{
                color: {PLACEHOLDER_COLOR};
            }}

            QTextEdit:focus {{
                background: #FFFFFF;
                color: #111111;
                border: 1px solid #9FA5B1;
            }}
        """)

        self.description_check.bind_to(
            self.description
        )

        description_row.addWidget(
            self.description_check,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        description_row.addWidget(
            self.description,
            stretch=1,
        )

        root.addLayout(
            description_row
        )

        # ========================================================
        # TAGS
        # ========================================================

        tags_row = QHBoxLayout()

        tags_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        tags_row.setSpacing(8)

        self.tags_check = CheckIndicator()

        self.tags_editor = TagEditor()

        self.tags_editor.tags_changed.connect(
            self.tags_check.set_checked
        )

        tags_row.addWidget(
            self.tags_check,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        tags_row.addWidget(
            self.tags_editor,
            stretch=1,
        )

        root.addLayout(
            tags_row
        )

        # ========================================================
        # RECORDING
        # ========================================================

        recording_row = QHBoxLayout()

        recording_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        recording_row.setSpacing(8)

        self.recording_check = CheckIndicator()

        recording_status = QWidget()

        recording_status.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)

        recording_status_layout = QHBoxLayout(
            recording_status
        )

        recording_status_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        recording_status_layout.setSpacing(7)

        self.recording_dot = QLabel("●")

        self.recording_text = QLabel(
            "Not recording..."
        )

        recording_status_layout.addWidget(
            self.recording_dot
        )

        recording_status_layout.addWidget(
            self.recording_text
        )

        # ========================================================
        # TEACH BUTTON
        # ========================================================

        self.teach_button = QPushButton(
            "TEACH"
        )

        self.teach_button.setFixedHeight(
            40
        )

        self.teach_button.setFixedWidth(
            108
        )

        self.teach_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.teach_button.setStyleSheet(f"""
            QPushButton {{
                background: {BUTTON_BG};
                color: {BUTTON_TEXT};
                border: none;
                border-radius: 9px;
                font-size: 13px;
                font-weight: 700;
            }}

            QPushButton:hover {{
                background: #303030;
            }}

            QPushButton:pressed {{
                background: #181818;
            }}

            QPushButton:disabled {{
                background: #777777;
                color: #CCCCCC;
            }}
        """)

        self.teach_button.clicked.connect(
            self.start_teaching
        )

        recording_row.addWidget(
            self.recording_check,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        recording_row.addWidget(
            recording_status
        )

        recording_row.addStretch()

        recording_row.addWidget(
            self.teach_button
        )

        root.addLayout(
            recording_row
        )

        # ========================================================
        # PUSH ACTIONS DOWN
        # ========================================================

        root.addStretch()

        # ========================================================
        # ADD BUTTON
        # ========================================================

        self.add_button = QPushButton(
            "ADD"
        )

        self.add_button.setFixedHeight(
            40
        )

        self.add_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.add_button.setStyleSheet(f"""
            QPushButton {{
                background: {BUTTON_BG};
                color: {BUTTON_TEXT};
                border: none;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 700;
            }}

            QPushButton:hover {{
                background: #303030;
            }}

            QPushButton:pressed {{
                background: #181818;
            }}

            QPushButton:disabled {{
                background: #777777;
                color: #CCCCCC;
            }}
        """)

        self.add_button.clicked.connect(
            self.add_task
        )

        root.addWidget(
            self.add_button
        )

        # ========================================================
        # CLEAR BUTTON
        # ========================================================

        self.clear_button = QPushButton(
            "CLEAR"
        )

        self.clear_button.setFixedHeight(
            40
        )

        self.clear_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.clear_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {BUTTON_BG};
                border: 1px solid {BUTTON_BG};
                border-radius: 12px;
                font-size: 13px;
                font-weight: 700;
            }}

            QPushButton:hover {{
                background: rgba(0, 0, 0, 8);
            }}

            QPushButton:pressed {{
                background: rgba(0, 0, 0, 15);
            }}

            QPushButton:disabled {{
                color: #888888;
                border-color: #888888;
            }}
        """)

        self.clear_button.clicked.connect(
            self.clear_form
        )

        root.addWidget(
            self.clear_button
        )

        # Initial state.
        self._set_recording_state(
            STATE_NOT_RECORDING
        )

    # ============================================================
    # TASK DATA
    # ============================================================

    def _metadata_filename(self, task_name):
        """
        Convert task name into a safe metadata filename.
        """

        filename = task_name.strip()

        filename = re.sub(
            r'[<>:"/\\|?*]',
            "_",
            filename,
        )

        filename = re.sub(
            r"\s+",
            "_",
            filename,
        )

        filename = re.sub(
            r"_+",
            "_",
            filename,
        )

        filename = filename.strip(
            " ._"
        )

        if not filename:
            filename = "task"

        return f"assets/databox/{filename}.jsonl"

    def get_task_data(self):
        """
        Collect current form using the required task format.
        """

        task_name = (
            self.task_name
            .text()
            .strip()
        )

        return {
            "name": task_name,

            "description": (
                self.description
                .toPlainText()
                .strip()
            ),

            "tags": (
                self.tags_editor
                .get_tags()
            ),

            "metadata_loc": (
                self._metadata_filename(
                    task_name
                )
            ),
        }

    # ============================================================
    # LOAD TASKS
    # ============================================================

    def _load_tasks(self):
        """
        Read the existing task list.

        Returns an empty list when the file does not exist or
        cannot be parsed as a JSON list.
        """

        if not TASKS_FILE.exists():
            return []

        try:
            content = (
                TASKS_FILE
                .read_text(
                    encoding="utf-8"
                )
                .strip()
            )

            if not content:
                return []

            loaded = json.loads(content)

            if isinstance(loaded, list):
                return loaded

        except (
            OSError,
            json.JSONDecodeError,
        ) as exc:

            print(
                "Warning: could not read "
                "user_saved_tasks.txt:"
            )

            print(exc)

        return []

    # ============================================================
    # SAVE TASK
    # ============================================================

    def save_task(self):
        """
        Save the current task into user_saved_tasks.txt.

        IMPORTANT:
        This uses an UPSERT operation.

        If the same task already exists, it is replaced instead
        of appended again. This prevents TEACH + ADD from creating
        duplicate entries.
        """

        task = self.get_task_data()

        if not task["name"]:

            self.task_name.setFocus()

            return False

        try:

            TASKS_FILE.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            tasks = self._load_tasks()

            # ----------------------------------------------------
            # Find an existing task with the same name and
            # metadata filename.
            #
            # TEACH saves the task first.
            # ADD saves it again later.
            #
            # Instead of creating:
            #
            #   Task
            #   Task
            #
            # we replace the existing entry.
            # ----------------------------------------------------

            existing_index = None

            for index, existing_task in enumerate(tasks):

                if not isinstance(
                    existing_task,
                    dict,
                ):
                    continue

                same_name = (
                    existing_task.get("name", "").strip()
                    == task["name"]
                )

                same_metadata = (
                    existing_task.get("metadata_loc")
                    == task["metadata_loc"]
                )

                if same_name and same_metadata:

                    existing_index = index
                    break

            # ----------------------------------------------------
            # UPDATE existing task
            # ----------------------------------------------------

            if existing_index is not None:

                tasks[existing_index] = task

                # Remove any accidental duplicate copies of
                # this exact task that may already exist.
                cleaned_tasks = []

                already_kept = False

                for existing_task in tasks:

                    if not isinstance(
                        existing_task,
                        dict,
                    ):
                        cleaned_tasks.append(
                            existing_task
                        )
                        continue

                    same_name = (
                        existing_task.get("name", "").strip()
                        == task["name"]
                    )

                    same_metadata = (
                        existing_task.get("metadata_loc")
                        == task["metadata_loc"]
                    )

                    if same_name and same_metadata:

                        if already_kept:
                            continue

                        already_kept = True

                    cleaned_tasks.append(
                        existing_task
                    )

                tasks = cleaned_tasks

                print(
                    f"Task updated: {task['name']}"
                )

            # ----------------------------------------------------
            # ADD new task
            # ----------------------------------------------------

            else:

                tasks.append(task)

                print(
                    f"Task added: {task['name']}"
                )

            # ----------------------------------------------------
            # Write JSON
            # ----------------------------------------------------

            with TASKS_FILE.open(
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    tasks,
                    file,
                    indent=4,
                    ensure_ascii=False,
                )

                file.write("\n")

            print(
                f"Task file: {TASKS_FILE}"
            )

            return True

        except OSError as exc:

            print(
                f"Could not save task: {exc}"
            )

            return False

    # ============================================================
    # TEACH
    # ============================================================

    def start_teaching(self):
        """
        Teaching workflow:

        1. Validate the task.
        2. Save/update it.
        3. Minimize Echo.
        4. Show 3 -> 2 -> 1.
        5. Launch learn.py.
        6. Change status to Recording... once learn.py starts.
        7. When learn.py exits, change status to Recorded.
        8. Restore Echo.
        """

        # --------------------------------------------------------
        # Do not start another teaching process.
        # --------------------------------------------------------

        if (
            self.learn_process is not None
            and self.learn_process.poll() is None
        ):
            return

        # --------------------------------------------------------
        # Do not start another countdown.
        # --------------------------------------------------------

        if self.countdown is not None:
            return

        task = self.get_task_data()

        if not task["name"]:

            self.task_name.setFocus()

            return

        # --------------------------------------------------------
        # Save/update task before teaching.
        # --------------------------------------------------------

        if not self.save_task():
            return

        # --------------------------------------------------------
        # Disable buttons that could interfere with teaching.
        # --------------------------------------------------------

        self.teach_button.setEnabled(False)
        self.add_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        # --------------------------------------------------------
        # Start from NOT RECORDING.
        # --------------------------------------------------------

        self._set_recording_state(
            STATE_NOT_RECORDING
        )

        # --------------------------------------------------------
        # Minimize main Echo window.
        # --------------------------------------------------------

        main_window = self.window()

        if main_window is not None:
            main_window.showMinimized()

        # --------------------------------------------------------
        # Start independent countdown.
        # --------------------------------------------------------

        self.countdown = CountdownWidget()

        self.countdown.finished.connect(
            self._launch_learn_process
        )

        self.countdown.start()

    # ============================================================
    # LAUNCH LEARN.PY
    # ============================================================

    def _launch_learn_process(self):
        """
        Launch learn.py as an independent process.

        Recording becomes green only after Popen succeeds.
        """

        # Countdown has finished.
        self.countdown = None

        if not LEARN_FILE.exists():

            print(
                f"learn.py was not found: "
                f"{LEARN_FILE}"
            )

            self._finish_teaching(
                success=False
            )

            return

        try:

            self.learn_process = subprocess.Popen(
                [
                    sys.executable,
                    str(LEARN_FILE),
                ],
                cwd=str(APP_DIR),
            )

            print(
                "Started learn.py"
            )

            print(
                f"PID: {self.learn_process.pid}"
            )

            print(
                f"Python: {sys.executable}"
            )

            print(
                f"Working directory: {APP_DIR}"
            )

            print(
                f"Script: {LEARN_FILE}"
            )

            # ----------------------------------------------------
            # NOW show Recording...
            # ----------------------------------------------------

            self._set_recording_state(
                STATE_RECORDING
            )

            QApplication.processEvents()

            # ----------------------------------------------------
            # Monitor learn.py.
            # ----------------------------------------------------

            if self._process_timer is not None:

                self._process_timer.stop()
                self._process_timer.deleteLater()

            self._process_timer = QTimer(
                self
            )

            self._process_timer.timeout.connect(
                self._check_learn_process
            )

            self._process_timer.start(
                100
            )

        except Exception as exc:

            print(
                f"Could not start learn.py: "
                f"{exc}"
            )

            self.learn_process = None

            self._finish_teaching(
                success=False
            )

    # ============================================================
    # CHECK LEARN PROCESS
    # ============================================================

    def _check_learn_process(self):

        if self.learn_process is None:
            return

        return_code = (
            self.learn_process.poll()
        )

        # --------------------------------------------------------
        # Still running.
        # --------------------------------------------------------

        if return_code is None:
            return

        # --------------------------------------------------------
        # Stop monitor timer.
        # --------------------------------------------------------

        if self._process_timer is not None:

            self._process_timer.stop()

            self._process_timer.deleteLater()

            self._process_timer = None

        self.learn_process = None

        print(
            f"learn.py finished with code "
            f"{return_code}"
        )

        # --------------------------------------------------------
        # Recording finished.
        # --------------------------------------------------------

        self._finish_teaching(
            success=(return_code == 0)
        )

    # ============================================================
    # FINISH TEACHING
    # ============================================================

    def _finish_teaching(
        self,
        success: bool = True,
    ):
        """
        Finish the teaching process.

        After learn.py exits, the status becomes:

            Recorded
        """

        # --------------------------------------------------------
        # Show Recorded.
        # --------------------------------------------------------

        self._set_recording_state(
            STATE_RECORDED
        )

        QApplication.processEvents()

        # --------------------------------------------------------
        # Re-enable controls.
        # --------------------------------------------------------

        self.teach_button.setEnabled(
            True
        )

        self.add_button.setEnabled(
            True
        )

        self.clear_button.setEnabled(
            True
        )

        # --------------------------------------------------------
        # Restore main Echo window.
        # --------------------------------------------------------

        main_window = self.window()

        if main_window is not None:

            main_window.showNormal()

            main_window.raise_()

            main_window.activateWindow()

            QApplication.processEvents()

        # --------------------------------------------------------
        # Print result.
        # --------------------------------------------------------

        if success:

            print(
                "Teaching completed."
            )

            print(
                "Recording status: Recorded"
            )

        else:

            print(
                "Teaching process ended "
                "without a successful exit code."
            )

            print(
                "Recording status: Recorded"
            )

    # ============================================================
    # RECORDING STATE
    # ============================================================

    def _set_recording_state(
        self,
        state: str,
    ):
        """
        Update the recording indicator.

        STATE_NOT_RECORDING:
            red   ● Not recording...

        STATE_RECORDING:
            green ● Recording...

        STATE_RECORDED:
            green ● Recorded
        """

        # --------------------------------------------------------
        # NOT RECORDING
        # --------------------------------------------------------

        if state == STATE_NOT_RECORDING:

            self.recording_dot.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_RED};
                    font-size: 16px;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_text.setText(
                "Not recording..."
            )

            self.recording_text.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_RED};
                    font-size: 13px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_check.set_checked(
                False
            )

            return

        # --------------------------------------------------------
        # RECORDING
        # --------------------------------------------------------

        if state == STATE_RECORDING:

            self.recording_dot.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_GREEN};
                    font-size: 16px;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_text.setText(
                "Recording..."
            )

            self.recording_text.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_GREEN};
                    font-size: 13px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_check.set_checked(
                True
            )

            return

        # --------------------------------------------------------
        # RECORDED
        # --------------------------------------------------------

        if state == STATE_RECORDED:

            self.recording_dot.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_GREEN};
                    font-size: 16px;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_text.setText(
                "Recorded"
            )

            self.recording_text.setStyleSheet(
                f"""
                QLabel {{
                    color: {RECORDING_GREEN};
                    font-size: 13px;
                    font-weight: 700;
                    background: transparent;
                    border: none;
                }}
                """
            )

            self.recording_check.set_checked(
                True
            )

            return

        # --------------------------------------------------------
        # Unknown state
        # --------------------------------------------------------

        print(
            f"Warning: unknown recording state: {state}"
        )

        self._set_recording_state(
            STATE_NOT_RECORDING
        )

    # ============================================================
    # ADD TASK
    # ============================================================

    def add_task(self):
        """
        Save/update the current task and completely reset the form.

        If TEACH was used first, this does NOT create a second
        JSON entry because save_task() performs an upsert.
        """

        # --------------------------------------------------------
        # Do not ADD during active recording.
        # --------------------------------------------------------

        if (
            self.learn_process is not None
            and self.learn_process.poll() is None
        ):

            print(
                "Cannot add while recording is active."
            )

            return

        # --------------------------------------------------------
        # Do not ADD during countdown.
        # --------------------------------------------------------

        if self.countdown is not None:

            print(
                "Cannot add while teaching countdown is active."
            )

            return

        # --------------------------------------------------------
        # Save/update.
        # --------------------------------------------------------

        if not self.save_task():
            return

        # --------------------------------------------------------
        # IMPORTANT:
        # Completely reset the form after ADD.
        # This includes recording status.
        # --------------------------------------------------------

        self.clear_form()

        print(
            "Task added and form reset."
        )

    # ============================================================
    # CLEAR FORM
    # ============================================================

    def clear_form(self):
        """
        Completely reset the New tab.

        Resets:
            - Task name
            - Description
            - Tags
            - Recording status
            - Recording check indicator
        """

        # --------------------------------------------------------
        # Do not clear while recording.
        # --------------------------------------------------------

        if (
            self.learn_process is not None
            and self.learn_process.poll() is None
        ):

            print(
                "Cannot clear while recording is active."
            )

            return

        # --------------------------------------------------------
        # Do not clear during countdown.
        # --------------------------------------------------------

        if self.countdown is not None:

            print(
                "Cannot clear while teaching countdown is active."
            )

            return

        # --------------------------------------------------------
        # Reset text fields.
        # --------------------------------------------------------

        self.task_name.clear()

        self.description.clear()

        # --------------------------------------------------------
        # Reset tags.
        # --------------------------------------------------------

        self.tags_editor.clear_tags()

        # --------------------------------------------------------
        # IMPORTANT FIX:
        #
        # Use STATE_NOT_RECORDING instead of False.
        #
        # The previous version did:
        #
        #     self._set_recording_state(False)
        #
        # but _set_recording_state() expects a state string.
        # --------------------------------------------------------

        self._set_recording_state(
            STATE_NOT_RECORDING
        )

        # --------------------------------------------------------
        # Make sure TEACH is available again.
        # --------------------------------------------------------

        self.teach_button.setEnabled(
            True
        )

        self.add_button.setEnabled(
            True
        )

        self.clear_button.setEnabled(
            True
        )

        print(
            "New task form cleared."
        )