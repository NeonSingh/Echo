"""
Documents / Documentation tab.

Uses the same visual structure as the Echo List page:
    - Echo robot + ECHO
    - Large rounded gray content panel
    - Scrollable content
    - Two documentation cards per row

Each documentation card keeps:
    - Block / command heading
    - Category
    - Description
    - Execution syntax
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
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


# ============================================================
# Colors
# ============================================================

PANEL_BACKGROUND = "#EBEBEB"

CARD_BACKGROUND = "#F8F8F8"
CARD_BORDER = "#D9DDE3"

CODE_BACKGROUND = "#D8D8D8"

TEXT_PRIMARY = "#111111"
TEXT_SECONDARY = "#4F5F78"
CODE_TEXT = "#35445C"

CATEGORY_BACKGROUND = "#E9EDF3"
CATEGORY_TEXT = "#637895"


# ============================================================
# Documentation data
# ============================================================

DOCUMENTATION = [
    {
        "name": "OPEN APP",
        "category": "System",
        "description": (
            "Launches an application by name or executable path."
        ),
        "syntax": (
            '<open_app> "app name" </open_app>'
        ),
    },
    {
        "name": "SEARCH WEBSITE",
        "category": "Web",
        "description": (
            "Searches the web using a search engine."
        ),
        "syntax": (
            '<search> "your query" </search>'
        ),
    },
    {
        "name": "OPEN URL",
        "category": "Web",
        "description": (
            "Opens a specific URL in the default browser."
        ),
        "syntax": (
            '<open_url> "https://example.com" </open_url>'
        ),
    },
    {
        "name": "TYPE TEXT",
        "category": "Input",
        "description": (
            "Types text into the currently focused field."
        ),
        "syntax": (
            '<type_text> "Your text here" </type_text>'
        ),
    },
    {
        "name": "CLICK ELEMENT",
        "category": "UI",
        "description": (
            "Clicks a UI element using its identifier or coordinates."
        ),
        "syntax": (
            '<click> "element_id" </click>'
        ),
    },
    {
        "name": "PRESS KEY",
        "category": "Input",
        "description": (
            "Presses a keyboard key or key combination."
        ),
        "syntax": (
            '<press_key> "enter" </press_key>'
        ),
    },
    {
        "name": "WAIT",
        "category": "Control",
        "description": (
            "Pauses execution for a specified time or condition."
        ),
        "syntax": (
            '<wait> 2s </wait>'
        ),
    },
    {
        "name": "SCREENSHOT",
        "category": "Media",
        "description": (
            "Takes a screenshot of the current screen."
        ),
        "syntax": (
            '<screenshot> "filename.png" </screenshot>'
        ),
    },
    {
        "name": "RUN COMMAND",
        "category": "System",
        "description": (
            "Executes a shell command in the terminal."
        ),
        "syntax": (
            '<run_command> "ls -la" </run_command>'
        ),
    },
    {
        "name": "FIND TEXT",
        "category": "Vision",
        "description": (
            "Searches for text on the screen and returns its position."
        ),
        "syntax": (
            '<find_text> "text to find" </find_text>'
        ),
    },
    {
        "name": "SAVE VALUE",
        "category": "Data",
        "description": (
            "Stores a value so it can be reused later in an automation."
        ),
        "syntax": (
            '<save> "variable" = "value" </save>'
        ),
    },
    {
        "name": "USE VALUE",
        "category": "Data",
        "description": (
            "Uses a previously saved value in another command."
        ),
        "syntax": (
            '<use> "variable" </use>'
        ),
    },
]


# ============================================================
# Documentation Card
# ============================================================

class DocumentationCard(QFrame):
    """
    One documentation card.

    The information structure remains unchanged:
        heading
        category
        description
        execution syntax
    """

    def __init__(
        self,
        documentation: dict,
        parent=None,
    ):
        super().__init__(parent)

        self.documentation = documentation

        self.setObjectName(
            "documentationCard"
        )

        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        self.setMinimumHeight(
            128
        )

        self.setStyleSheet(
            f"""
            QFrame#documentationCard {{
                background: {CARD_BACKGROUND};
                border: 1px solid {CARD_BORDER};
                border-radius: 15px;
            }}
            """
        )

        # ========================================================
        # Card layout
        # ========================================================

        layout = QVBoxLayout(self)

        layout.setContentsMargins(
            14,
            11,
            14,
            12,
        )

        layout.setSpacing(
            6
        )

        # ========================================================
        # Heading row
        # ========================================================

        heading_row = QHBoxLayout()

        heading_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        heading_row.setSpacing(
            8
        )

        # --------------------------------------------------------
        # Block heading
        # --------------------------------------------------------

        heading = QLabel(
            documentation["name"]
        )

        heading.setStyleSheet(
            f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                background: transparent;
                border: none;
                font-size: 15px;
                font-weight: 700;
            }}
            """
        )

        heading_row.addWidget(
            heading,
            stretch=1,
        )

        # --------------------------------------------------------
        # Category badge
        # --------------------------------------------------------

        category = QLabel(
            documentation["category"]
        )

        category.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        category.setStyleSheet(
            f"""
            QLabel {{
                color: {CATEGORY_TEXT};
                background: {CATEGORY_BACKGROUND};
                border: none;
                border-radius: 10px;
                padding: 4px 9px;
                font-size: 9px;
                font-weight: 600;
            }}
            """
        )

        heading_row.addWidget(
            category,
            alignment=Qt.AlignmentFlag.AlignTop,
        )

        layout.addLayout(
            heading_row
        )

        # ========================================================
        # Description
        # ========================================================

        description = QLabel(
            documentation["description"]
        )

        description.setWordWrap(
            True
        )

        description.setStyleSheet(
            f"""
            QLabel {{
                color: {TEXT_SECONDARY};
                background: transparent;
                border: none;
                font-size: 10px;
            }}
            """
        )

        layout.addWidget(
            description
        )

        # ========================================================
        # Execution syntax
        # ========================================================

        syntax_frame = QFrame()

        syntax_frame.setObjectName(
            "syntaxFrame"
        )

        syntax_frame.setStyleSheet(
            f"""
            QFrame#syntaxFrame {{
                background: {CODE_BACKGROUND};
                border: none;
                border-radius: 9px;
            }}
            """
        )

        syntax_layout = QHBoxLayout(
            syntax_frame
        )

        syntax_layout.setContentsMargins(
            9,
            5,
            9,
            5,
        )

        syntax = QLabel(
            documentation["syntax"]
        )

        syntax.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        syntax.setStyleSheet(
            f"""
            QLabel {{
                color: {CODE_TEXT};
                background: transparent;
                border: none;
                font-family: "Consolas", "Cascadia Code", monospace;
                font-size: 9px;
            }}
            """
        )

        syntax_layout.addWidget(
            syntax
        )

        layout.addWidget(
            syntax_frame
        )


# ============================================================
# Documents Section
# ============================================================

class DocumentsSection(QWidget):
    """Echo documentation page matching the List page structure."""

    def __init__(
        self,
        parent=None,
    ):
        super().__init__(parent)

        # --------------------------------------------------------
        # Keep MainContainer responsible for its own background.
        # --------------------------------------------------------

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

        # Same basic proportions as ListSection
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

        logo = QLabel()

        logo.setFixedSize(
            54,
            42,
        )

        logo.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        logo.setStyleSheet(
            """
            QLabel {
                background: transparent;
                border: none;
            }
            """
        )

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

            logo.setPixmap(
                logo_pixmap
            )

        # --------------------------------------------------------
        # ECHO Documentation
        # --------------------------------------------------------

        title = QLabel(
            "E C H O"
        )

        title.setStyleSheet(
            f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                background: transparent;
                border: none;
                font-family: "future";
                font-size: 35px;
                font-weight: 700;
                margin-bottom:5px;
            }}
            """
        )

        header.addWidget(
            logo,
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
        # Large gray documentation panel
        # ========================================================

        self.documentation_panel = QFrame()

        self.documentation_panel.setObjectName(
            "documentationPanel"
        )

        self.documentation_panel.setStyleSheet(
            f"""
            QFrame#documentationPanel {{
                background: {PANEL_BACKGROUND};
                border: none;
                border-radius: 19px;
            }}
            """
        )

        panel_layout = QVBoxLayout(
            self.documentation_panel
        )

        # Match the List page inner margins.
        panel_layout.setContentsMargins(
            10,
            12,
            10,
            12,
        )

        panel_layout.setSpacing(
            0
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

        self.scroll_area.setStyleSheet(
            """
            QScrollArea {
                background: transparent;
                border: none;
            }

            QScrollArea > QWidget > QWidget {
                background: transparent;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 8px 4px 8px 0px;
            }

            QScrollBar::handle:vertical {
                background: rgba(70, 70, 70, 75);
                border-radius: 3px;
                min-height: 35px;
            }

            QScrollBar::handle:vertical:hover {
                background: rgba(70, 70, 70, 110);
            }

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }

            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            """
        )

        # ========================================================
        # Scroll content
        # ========================================================

        scroll_content = QWidget()

        scroll_content.setStyleSheet(
            "background: transparent;"
        )

        grid = QVBoxLayout(
            scroll_content
        )

        # Right margin keeps cards away from scrollbar.
        grid.setContentsMargins(
            3,
            8,
            20,
            8,
        )

        grid.setSpacing(
            14
        )

        # ========================================================
        # Two-column documentation grid
        # ========================================================

        for row_start in range(
            0,
            len(DOCUMENTATION),
            2,
        ):

            row = QHBoxLayout()

            row.setContentsMargins(
                0,
                0,
                0,
                0,
            )

            row.setSpacing(
                14
            )

            # ----------------------------------------------------
            # Left documentation card
            # ----------------------------------------------------

            left_card = DocumentationCard(
                DOCUMENTATION[row_start]
            )

            row.addWidget(
                left_card,
                stretch=1,
            )

            # ----------------------------------------------------
            # Right documentation card
            # ----------------------------------------------------

            if (
                row_start + 1
                < len(DOCUMENTATION)
            ):

                right_card = DocumentationCard(
                    DOCUMENTATION[row_start + 1]
                )

                row.addWidget(
                    right_card,
                    stretch=1,
                )

            else:

                empty = QWidget()

                row.addWidget(
                    empty,
                    stretch=1,
                )

            grid.addLayout(
                row
            )

        grid.addStretch()

        # ========================================================
        # Attach scroll content
        # ========================================================

        self.scroll_area.setWidget(
            scroll_content
        )

        panel_layout.addWidget(
            self.scroll_area
        )

        # ========================================================
        # Add panel to page
        # ========================================================

        root.addWidget(
            self.documentation_panel,
            stretch=1,
        )