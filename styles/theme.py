"""
Shared color palette, fonts and layout constants used across the app.

Centralising these values here means every component and section pulls
from the same source of truth, so re-theming the app only requires
editing this one file.
"""


class Colors:
    # Outer app / page background
    APP_BG = "#e9e9ea"

    # Navigation bar
    NAV_BG = "#141414"
    ICON_INACTIVE = "#6b6b6b"
    ICON_ACTIVE = "#ffffff"
    ICON_ACTIVE_BG = "#2b2b2b"
    ICON_ACTIVE = "#FFFFFF"
    ICON_INACTIVE = "#A7A6A6"

    # Window controls (macOS-style traffic lights)
    CONTROLS_PILL_BG = "#3F3F3F"
    CONTROL_CLOSE = "#CF4949"    # blue
    CONTROL_MINIMIZE = "#56A8EB"  # yellow
    CONTROL_MAXIMIZE = "#DDD25B"  # red

    # Main content card
    CARD_BG = "#EBEBEB"
    MOUNTAIN_1 = "#cfcfcf"
    MOUNTAIN_2 = "#bcbcbd"
    MOUNTAIN_3 = "#a5a5a7"
    MOUNTAIN_4 = "#8d8d90"
    MOUNTAIN_5 = "#6f6f72"

    TEXT_DARK = "#1a1a1a"
    TEXT_MUTED = "#5a5a5a"

    BADGE_BG = "#2b2b2b"
    BADGE_TEXT = "#ffffff"
    BADGE_CHIP_BG = "#ffffff33"


class Fonts:
    FAMILY = "Segoe UI"
    BRAND_SIZE = 26
    TITLE_SIZE = 20
    BADGE_SIZE = 11


# Layout constants
RADIUS_WINDOW = 22
RADIUS_NAV = 20
RADIUS_CARD = 26
NAV_WIDTH = 75
CONTROLS_HEIGHT = 34
