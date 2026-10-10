"""
'List' tab.

Task/list data is loaded from:

    assets/data/user_saved_tasks.txt

The file contains a JSON array of task objects.

One ListItem is created for each task, in exactly the same order
as they appear in the file.

Deleting a task:
    1. Removes it from the UI.
    2. Removes the corresponding task from user_saved_tasks.txt.
"""

from pathlib import Path
import json

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPixmap,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QToolButton,
    QScrollArea,
)

# ============================================================
# Paths
# ============================================================

APP_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = (
    APP_DIR
    / "assets"
    / "images"
)

TASKS_FILE = (
    APP_DIR
    / "assets"
    / "data"
    / "user_saved_tasks.txt"
)


# ============================================================
# Colors
# ============================================================

LIST_BACKGROUND = "#093CA1"
ITEM_BACKGROUND = "#F8F8F8"

TITLE_COLOR = "#111111"
DESCRIPTION_COLOR = "#171717"

DELETE_COLOR = "#B5B5B5"
DELETE_HOVER_COLOR = "#969696"

TAG_TEXT_COLOR = "#4F5F78"
TAG_BG = "#EEF1F5"
TAG_BORDER = "#EEF1F5"


# ============================================================
# Delete button
# ============================================================

class DeleteButton(QToolButton):
    """Minimal trash button."""

    clicked_delete = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setFixedSize(28, 28)

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )

        self.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0px;
            }

            QToolButton:hover {
                background: rgba(0, 0, 0, 10);
                border-radius: 7px;
            }

            QToolButton:pressed {
                background: rgba(0, 0, 0, 18);
                border-radius: 7px;
            }
        """)

        self.clicked.connect(
            self.clicked_delete.emit
        )

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        color = QColor(
            DELETE_HOVER_COLOR
            if self.underMouse()
            else DELETE_COLOR
        )

        cx = self.width() / 2
        cy = self.height() / 2

        # --------------------------------------------------------
        # Trash body
        # --------------------------------------------------------

        painter.setPen(
            Qt.PenStyle.NoPen
        )
        painter.setBrush(color)

        body = QRectF(
            cx - 5,
            cy - 4,
            10,
            12,
        )

        path = QPainterPath()
        path.addRoundedRect(
            body,
            2,
            2,
        )

        painter.drawPath(path)

        # --------------------------------------------------------
        # Trash lid + handle
        # --------------------------------------------------------

        pen = painter.pen()
        pen.setColor(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(
            Qt.PenCapStyle.RoundCap
        )
        pen.setJoinStyle(
            Qt.PenJoinStyle.RoundJoin
        )

        painter.setPen(pen)
        painter.setBrush(
            Qt.BrushStyle.NoBrush
        )

        painter.drawLine(
            int(cx - 6),
            int(cy - 6),
            int(cx + 6),
            int(cy - 6),
        )

        painter.drawLine(
            int(cx - 2.5),
            int(cy - 9),
            int(cx + 2.5),
            int(cy - 9),
        )

        # --------------------------------------------------------
        # Inner lines
        # --------------------------------------------------------

        painter.setPen(
            QColor(ITEM_BACKGROUND)
        )

        painter.drawLine(
            int(cx - 2),
            int(cy - 1),
            int(cx - 2),
            int(cy + 5),
        )

        painter.drawLine(
            int(cx + 2),
            int(cy - 1),
            int(cx + 2),
            int(cy + 5),
        )

        painter.end()


# ============================================================
# Tag chip
# ============================================================

class TagChip(QFrame):
    """Small rounded tag."""

    def __init__(
        self,
        text: str,
        parent=None,
    ):
        super().__init__(parent)

        self.setFixedHeight(24)

        self.setStyleSheet(f"""
            QFrame {{
                background: {TAG_BG};
                border: 1px solid {TAG_BORDER};
                border-radius: 11px;
            }}
        """)

        layout = QHBoxLayout(self)

        layout.setContentsMargins(
            8,
            0,
            8,
            0,
        )

        layout.setSpacing(0)

        label = QLabel(
            f"#{text}"
        )

        label.setStyleSheet(f"""
            QLabel {{
                color: {TAG_TEXT_COLOR};
                background: transparent;
                border: none;
                font-size: 9px;
                font-weight: 500;
            }}
        """)

        layout.addWidget(label)


# ============================================================
# List item
# ============================================================

class ListItem(QFrame):
    """
    One task item.

    The complete task dictionary is stored in self.task_data so
    the exact corresponding entry can later be removed from disk.
    """

    removed = Signal(object)

    def __init__(
        self,
        task_data: dict,
        parent=None,
    ):
        super().__init__(parent)

        self.task_data = task_data

        self.name = str(
            task_data.get(
                "name",
                "Unnamed Task",
            )
        )

        self.description = str(
            task_data.get(
                "description",
                "",
            )
        )

        tags = task_data.get(
            "tags",
            [],
        )

        self.tags = (
            tags
            if isinstance(tags, list)
            else []
        )

        self.metadata_loc = str(
            task_data.get(
                "metadata_loc",
                "",
            )
        )

        self.setObjectName(
            "listItem"
        )

        self.setStyleSheet("""
            QFrame#listItem {
                background: #F8F8F8;
                border: solid;
                border-width: 1px;
                border-color: #DCE2EA;
                border-radius: 15px;
            }
        """)

        # ========================================================
        # Item layout
        # ========================================================

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            14,
            9,
            8,
            9,
        )

        layout.setSpacing(4)

        # ========================================================
        # Title row
        # ========================================================

        title_row = QHBoxLayout()

        title_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        title_row.setSpacing(4)

        title_label = QLabel(
            self.name
        )

        title_label.setStyleSheet("""
            QLabel {
                color: #111111;
                background: transparent;
                border: none;
                font-size: 15px;
                font-weight: 700;
            }
        """)

        title_row.addWidget(
            title_label,
            stretch=1,
        )

        # --------------------------------------------------------
        # Delete button
        # --------------------------------------------------------

        self.delete_button = DeleteButton()

        self.delete_button.clicked_delete.connect(
            self._on_delete
        )

        title_row.addWidget(
            self.delete_button,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        layout.addLayout(
            title_row
        )

        # ========================================================
        # Description
        # ========================================================

        description_label = QLabel(
            self.description
        )

        description_label.setWordWrap(
            True
        )

        description_label.setStyleSheet("""
            QLabel {
                color: #171717;
                background: transparent;
                border: none;
                font-size: 11px;
                font-weight: 400;
            }
        """)

        layout.addWidget(
            description_label
        )

        # ========================================================
        # Tags
        # ========================================================

        if self.tags:

            tags_layout = QHBoxLayout()

            tags_layout.setContentsMargins(
                0,
                2,
                0,
                0,
            )

            tags_layout.setSpacing(5)

            for tag in self.tags:

                tag_chip = TagChip(
                    str(tag)
                )

                tags_layout.addWidget(
                    tag_chip
                )

            tags_layout.addStretch()

            layout.addLayout(
                tags_layout
            )

        self.setMinimumHeight(
            76
        )

    def _on_delete(self):
        """Request removal of this task."""

        self.removed.emit(
            self
        )


# ============================================================
# List section
# ============================================================

class ListSection(QWidget):
    """
    Echo List page.

    Kept as NewSection so existing main.py imports continue to work.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # Keep MainContainer responsible for the background.
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )

        self.setStyleSheet(
            "background: transparent;"
        )

        # ========================================================
        # Root
        # ========================================================

        root = QVBoxLayout(self)

        root.setContentsMargins(
            26,
            18,
            26,
            28,
        )

        root.setSpacing(
            16
        )

        # ========================================================
        # Header
        # ========================================================

        header = QHBoxLayout()

        header.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        header.setSpacing(
            12
        )

        # --------------------------------------------------------
        # Robot logo
        # --------------------------------------------------------

        self.logo = QLabel()

        self.logo.setFixedSize(
            54,
            42,
        )

        self.logo.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.logo.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
            }
        """)

        logo_path = (
            ASSETS_DIR
            / "robot_face.png"
        )

        logo_pixmap = QPixmap(
            str(logo_path)
        )

        if not logo_pixmap.isNull():

            logo_pixmap = logo_pixmap.scaled(
                54,
                42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            self.logo.setPixmap(
                logo_pixmap
            )

        # --------------------------------------------------------
        # Title
        # --------------------------------------------------------

        title = QLabel(
            "E C H O"
        )

        title.setStyleSheet("""
            QLabel {
                color: #111111;
                background: transparent;
                border: none;
                font-family: "future";
                font-size: 35px;
                font-weight: 700;
                margin-bottom:5px;
            }
        """)

        header.addWidget(
            self.logo,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        header.addWidget(
            title,
            alignment=Qt.AlignmentFlag.AlignVCenter,
        )

        header.addStretch()

        root.addLayout(
            header
        )

        # ========================================================
        # List panel
        # ========================================================

        self.list_panel = QFrame()

        self.list_panel.setObjectName(
            "listPanel"
        )

        self.list_panel.setStyleSheet("""
            QFrame#listPanel {
                background: #EFEFEF;
                border: none;
                border-radius: 19px;
            }
        """)

        panel_layout = QVBoxLayout(
            self.list_panel
        )

        panel_layout.setContentsMargins(
            10,
            12,
            18,
            12,
        )

        # ========================================================
        # Scroll area
        # ========================================================

        self.scroll_area = QScrollArea()

        self.scroll_area.setWidgetResizable(
            True
        )

        self.scroll_area.setFrameShape(
            QFrame.Shape.NoFrame
        )

        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }

            QScrollArea > QWidget > QWidget {
                background: transparent;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 12px;
                margin: 10px 4px 10px 0px;
            }

            QScrollBar::handle:vertical {
                background: rgba(60, 60, 60, 70);
                border-radius: 3px;
                min-height: 20px;
            }

            QScrollBar::handle:vertical:hover {
                background: rgba(60, 60, 60, 110);
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        # --------------------------------------------------------
        # Scroll content widget
        # --------------------------------------------------------

        self.scroll_content = QWidget()

        self.scroll_content.setStyleSheet(
            "background: transparent;"
        )

        self.items_layout = QVBoxLayout(
            self.scroll_content
        )

        self.items_layout.setContentsMargins(
            0,
            8,
            18,
            8,
        )

        self.items_layout.setSpacing(
            17
        )

        # This stretch is created BEFORE tasks are inserted.
        #
        # Therefore add_item() can always insert before it without
        # reversing the order of the tasks.
        self.items_layout.addStretch()

        self.scroll_area.setWidget(
            self.scroll_content
        )

        panel_layout.addWidget(
            self.scroll_area
        )

        root.addWidget(
            self.list_panel,
            stretch=1,
        )

        # ========================================================
        # Load tasks
        # ========================================================

        self.load_tasks()

    # ============================================================
    # Reload tasks
    # ============================================================

    def reload_tasks(self):
        """
        Re-read user_saved_tasks.txt and rebuild the visible list.

        This is called every time the List tab is clicked.
        """

        # --------------------------------------------------------
        # Remove existing task widgets
        # --------------------------------------------------------

        while self.items_layout.count() > 1:
            item = self.items_layout.takeAt(0)

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        # --------------------------------------------------------
        # Load the latest file contents
        # --------------------------------------------------------

        self.load_tasks()

    # ============================================================
    # Load tasks
    # ============================================================

    def load_tasks(self):
        """
        Read user_saved_tasks.txt and create tasks in file order.
        """

        if not TASKS_FILE.exists():

            print(
                f"Task file not found: {TASKS_FILE}"
            )

            return

        try:

            with open(
                TASKS_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

        except json.JSONDecodeError as error:

            print(
                f"Invalid JSON in {TASKS_FILE}: {error}"
            )

            return

        except OSError as error:

            print(
                f"Could not read {TASKS_FILE}: {error}"
            )

            return

        # --------------------------------------------------------
        # Validate JSON root
        # --------------------------------------------------------

        if not isinstance(data, list):

            print(
                "user_saved_tasks.txt must contain a JSON list."
            )

            return

        # --------------------------------------------------------
        # Add tasks in EXACT file order
        # --------------------------------------------------------

        for task in data:

            if not isinstance(
                task,
                dict,
            ):
                continue

            self.add_item(
                task
            )

    # ============================================================
    # Add item
    # ============================================================

    def add_item(
        self,
        task_data: dict,
    ):
        """
        Add one task before the final stretch.

        Because the stretch already exists, this preserves the
        exact order in which tasks are inserted.
        """

        item = ListItem(
            task_data=task_data,
            parent=self.scroll_content,
        )

        item.removed.connect(
            self.remove_item
        )

        # --------------------------------------------------------
        # Insert before the stretch item
        # --------------------------------------------------------

        stretch_index = (
            self.items_layout.count() - 1
        )

        self.items_layout.insertWidget(
            stretch_index,
            item,
        )

    # ============================================================
    # Remove from UI + file
    # ============================================================

    def remove_item(
        self,
        item: ListItem,
    ):
        """
        Delete a task from both the UI and the JSON file.
        """

        # --------------------------------------------------------
        # Remove task from file first
        # --------------------------------------------------------

        success = self._remove_task_from_file(
            item.task_data
        )

        if not success:
            print(
                "Could not remove task from "
                f"{TASKS_FILE}"
            )

            return

        # --------------------------------------------------------
        # Remove from UI
        # --------------------------------------------------------

        self.items_layout.removeWidget(
            item
        )

        item.deleteLater()

    # ============================================================
    # Persist deletion
    # ============================================================

    def _remove_task_from_file(
        self,
        task_to_remove: dict,
    ) -> bool:
        """
        Remove the matching task dictionary from disk.

        The remaining tasks retain their original order.
        """

        if not TASKS_FILE.exists():
            return False

        try:

            with open(
                TASKS_FILE,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

        except (
            OSError,
            json.JSONDecodeError,
        ) as error:

            print(
                f"Could not read {TASKS_FILE}: {error}"
            )

            return False

        if not isinstance(data, list):
            return False

        # --------------------------------------------------------
        # Find the exact task
        # --------------------------------------------------------

        removed = False

        new_data = []

        for task in data:

            if (
                not removed
                and task == task_to_remove
            ):
                removed = True
                continue

            new_data.append(
                task
            )

        if not removed:
            print(
                "Task was not found in the saved task file."
            )

            return False

        # --------------------------------------------------------
        # Write updated file
        # --------------------------------------------------------

        try:

            with open(
                TASKS_FILE,
                "w",
                encoding="utf-8",
            ) as file:

                json.dump(
                    new_data,
                    file,
                    indent=4,
                )

                file.write(
                    "\n"
                )

        except OSError as error:

            print(
                f"Could not write {TASKS_FILE}: {error}"
            )

            return False

        return True
