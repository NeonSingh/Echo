# Echo


A modular, frameless desktop application shell built with Python and PySide6,
matching the provided reference design: a dark rounded navigation sidebar,
macOS-style window controls, and a rounded main content card with a
layered "mountain" backdrop and ECHO branding on the Home tab.

<img width="1125" height="687" alt="Screenshot 2026-10-10 084738" src="https://github.com/user-attachments/assets/b04005ee-2e29-4556-ad54-2100ae7f8d21" />

## Project structure

```
app/
├── main.py                  # Application entry point
├── requirements.txt         # Dependencies
├── README.md                # This file
│
├── components/
│   ├── navigation_bar.py    # Sidebar + icon nav buttons
│   ├── window_controls.py   # Close / minimize / maximize dots
│   └── main_container.py    # Rounded content card + section stack
│
├── sections/
│   ├── home.py               # Home tab (mountain scene + branding)
│   ├── section_2.py          # Billing tab
│   ├── section_3.py          # New tab
│   ├── section_4.py          # Documents tab
│   └── section_5.py          # Settings tab
│
├── backend_pipeline/
│   └── app_launcher.py       # Installed-app discovery and safe launching
│
├── tests/
│   └── test_app_launcher.py  # Offline command-recognition/launch tests
│
├── assets/                   # icons / images / fonts (optional, currently empty —
│                              #   all current visuals are painted in code)
└── styles/
    └── theme.py               # Shared colors, fonts, layout constants
```

Each file in `sections/` is a self-contained `QWidget` subclass, so new tabs
can be developed independently and dropped into `main.py` without touching
the navigation bar, window controls, or other sections.

## Setup

1. Create a virtual environment (recommended):

   ```bash
   python -m venv .venv
   source .venv/bin/activate   # on Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

## Run

```bash
python main.py
```

## Voice application launching

The voice backend recognizes explicit requests such as `open Chrome`, `launch Spotify`,
`start Notepad`, and `open Visual Studio Code` before it checks saved automation tags
or sends a request to Ollama. On Windows, it discovers applications from Start Menu
shortcuts, registered App Paths entries, and executable names on `PATH`; common app
name aliases are included. Launching uses the resolved shortcut/executable directly and
does not pass the spoken request to a shell. If no installed application matches, ECHO
shows a message instead of claiming it opened.

Run the offline command-recognition tests with `python -m unittest discover -s tests`.

## Notes on behaviour

- **Frameless & draggable** — the window has no native title bar. Click and
  drag any empty background area to move the window; double-click the
  background to maximize/restore.
- **Window controls** — the top-right dots are custom-painted, wired to
  close, minimize, and maximize/restore the window (red = close,
  yellow = minimize, green = maximize, per the spec).
- **Resizing** — a small grip in the bottom-right corner lets you resize the
  window; `setMinimumSize` prevents the layout from collapsing.
- **Rounded corners** — both the outer window and the main content card use
  a `QPainterPath` + `QRegion` mask so their corners are genuinely rounded
  (not just painted), including on window resize.
- **No external image assets required** — the app-mark icon, nav icons, and
  the layered mountain backdrop are all drawn procedurally with `QPainter`,
  so the app runs as-is. Swap in real assets under `assets/` and update the
  relevant widgets if you'd rather use image files/SVGs.

## Adding a new tab

1. Create `sections/section_6.py` with a `QWidget` subclass.
2. Add an `(icon_name, tooltip)` entry to `NavigationBar.SECTIONS` in
   `components/navigation_bar.py`, and draw its icon case in
   `NavButton.paintEvent`.
3. In `main.py`, import the new section and call
   `self.main_container.add_section(YourSection())`.
