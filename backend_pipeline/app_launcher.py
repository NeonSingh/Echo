"""Local application launching for ECHO.

Recognizes explicit requests such as "open Chrome" and launches an installed
application without passing user text through a shell. Windows is the primary
target, with support for Start Menu shortcuts, registered App Paths entries,
and executables available on PATH.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of a launch attempt, suitable for displaying to the user."""

    success: bool
    requested_name: str
    app_name: str | None
    message: str


@dataclass(frozen=True)
class _InstalledApp:
    name: str
    target: str
    kind: str  # "shortcut", "executable", "mac_app", or "uri"


# Each key is a common phrase the user may say; values are equivalent names
# that can appear in Start Menu shortcuts or the App Paths registry.
_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome", "google chrome"),
    "chrome browser": ("google chrome", "chrome"),
    "google chrome": ("google chrome", "chrome"),
    "edge": ("edge", "microsoft edge"),
    "edge browser": ("microsoft edge", "edge"),
    "microsoft edge": ("microsoft edge", "edge"),
    "firefox": ("firefox", "mozilla firefox"),
    "mozilla firefox": ("mozilla firefox", "firefox"),
    "brave": ("brave", "brave browser"),
    "brave browser": ("brave browser", "brave"),
    "vscode": ("visual studio code", "vs code", "code"),
    "vs code": ("visual studio code", "vs code", "code"),
    "visual studio code": ("visual studio code", "vs code", "code"),
    "notepad": ("notepad",),
    "calculator": ("calculator", "windows calculator", "calc"),
    "calc": ("calculator", "windows calculator", "calc"),
    "file explorer": ("file explorer", "explorer"),
    "explorer": ("file explorer", "explorer"),
    "word": ("word", "microsoft word"),
    "microsoft word": ("microsoft word", "word"),
    "excel": ("excel", "microsoft excel"),
    "microsoft excel": ("microsoft excel", "excel"),
    "powerpoint": ("powerpoint", "microsoft powerpoint"),
    "microsoft powerpoint": ("microsoft powerpoint", "powerpoint"),
    "outlook": ("outlook", "microsoft outlook"),
    "teams": ("teams", "microsoft teams"),
    "microsoft teams": ("microsoft teams", "teams"),
    "spotify": ("spotify",),
    "discord": ("discord",),
    "whatsapp": ("whatsapp", "whatsapp desktop"),
    "telegram": ("telegram", "telegram desktop"),
    "zoom": ("zoom", "zoom workplace"),
    "paint": ("paint", "mspaint", "paint 3d"),
    "snipping tool": ("snipping tool",),
    "task manager": ("task manager", "taskmgr"),
    "settings": ("settings", "windows settings"),
    "control panel": ("control panel", "control"),
    "terminal": ("terminal", "windows terminal"),
    "windows terminal": ("windows terminal", "terminal"),
    "cmd": ("command prompt", "cmd"),
    "command prompt": ("command prompt", "cmd"),
    "powershell": ("powershell", "windows powershell"),
    "windows powershell": ("windows powershell", "powershell"),
}

_WAKE_PREFIX = re.compile(r"^(?:hey\s+)?echo\b[\s,:;.!-]*", re.IGNORECASE)
_OPEN_COMMAND = re.compile(
    r"^(?:(?:please|kindly)\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+)?"
    r"(?:please\s+)?"
    r"(?:open|launch|start|run)\s+(?:up\s+)?(.+?)\s*$",
    re.IGNORECASE,
)


def _normalize_name(value: str) -> str:
    value = str(value or "").casefold().strip()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def extract_open_app_request(transcription: str) -> str | None:
    """Extract an app name only when a transcription starts with a launch verb.

    Accepted examples:
        "open Chrome"
        "Could you please open Visual Studio Code?"
        "Echo, launch Spotify"
        "start up Notepad for me"

    Arbitrary sentences are not treated as commands.
    """

    text = str(transcription or "").strip()
    if not text:
        return None

    text = _WAKE_PREFIX.sub("", text, count=1).strip()
    match = _OPEN_COMMAND.match(text)
    if not match:
        return None

    app_name = match.group(1).strip().strip(" \t\r\n.,!?;:")
    app_name = re.sub(r"\s+(?:for me|please|now)$", "", app_name, flags=re.IGNORECASE)
    app_name = re.sub(r"^(?:the\s+)?(?:app|application)\s+(?:called|named)\s+", "", app_name, flags=re.IGNORECASE)
    app_name = re.sub(r"^the\s+", "", app_name, flags=re.IGNORECASE).strip()
    app_name = re.sub(r"\s+(?:app|application)$", "", app_name, flags=re.IGNORECASE).strip()

    if not app_name or not re.search(r"[\w]", app_name, flags=re.UNICODE):
        return None

    return app_name


def _start_menu_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform != "win32":
        return roots

    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _installed_from_start_menu() -> Iterable[_InstalledApp]:
    for root in _start_menu_roots():
        if not root.is_dir():
            continue
        try:
            shortcuts = root.rglob("*.lnk")
            for shortcut in shortcuts:
                try:
                    if shortcut.is_file():
                        yield _InstalledApp(shortcut.stem, str(shortcut), "shortcut")
                except OSError:
                    continue
        except OSError:
            continue


def _installed_from_app_paths() -> Iterable[_InstalledApp]:
    """Enumerate registered Windows executable targets, when on Windows."""
    if sys.platform != "win32":
        return

    try:
        import winreg  # Windows-only standard-library module
    except ImportError:
        return

    app_paths_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = (0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))

    seen: set[tuple[str, str]] = set()
    for root in roots:
        for view in dict.fromkeys(views):
            try:
                with winreg.OpenKey(root, app_paths_key, 0, winreg.KEY_READ | view) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for index in range(count):
                        try:
                            entry_name = winreg.EnumKey(key, index)
                            with winreg.OpenKey(key, entry_name) as entry:
                                value, _ = winreg.QueryValueEx(entry, None)
                            if not isinstance(value, str) or not value.strip():
                                continue
                            # App Paths normally stores a quoted or plain executable path.
                            expanded = os.path.expandvars(value.strip().strip('"'))
                            executable = Path(expanded)
                            if not executable.is_file():
                                continue
                            identity = (entry_name.casefold(), str(executable).casefold())
                            if identity in seen:
                                continue
                            seen.add(identity)
                            yield _InstalledApp(Path(entry_name).stem, str(executable), "executable")
                        except (OSError, ValueError):
                            continue
            except OSError:
                continue


def _installed_from_path() -> Iterable[_InstalledApp]:
    """Resolve straightforward executable names available through PATH."""
    if sys.platform == "win32":
        extensions = (".exe", ".com")
    else:
        extensions = ("",)

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        path = Path(directory)
        if not path.is_dir():
            continue
        try:
            for executable in path.iterdir():
                if not executable.is_file() or not os.access(executable, os.X_OK):
                    continue
                if sys.platform == "win32" and executable.suffix.casefold() not in extensions:
                    continue
                yield _InstalledApp(executable.stem, str(executable), "executable")
        except OSError:
            continue


def _installed_macos_apps() -> Iterable[_InstalledApp]:
    if sys.platform != "darwin":
        return
    roots = (Path("/Applications"), Path.home() / "Applications")
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for app_path in root.glob("*.app"):
                if app_path.is_dir():
                    yield _InstalledApp(app_path.stem, str(app_path), "mac_app")
        except OSError:
            continue


def _installed_apps() -> list[_InstalledApp]:
    """Discover installed apps without using the user's text as shell input."""
    found: list[_InstalledApp] = []
    seen: set[tuple[str, str, str]] = set()

    sources = (
        _installed_from_start_menu(),
        _installed_from_app_paths(),
        _installed_from_path(),
        _installed_macos_apps(),
    )
    for source in sources:
        for item in source:
            key = (item.name.casefold(), os.path.normcase(item.target), item.kind)
            if key in seen:
                continue
            seen.add(key)
            found.append(item)

    return found


def _candidate_names(requested_name: str) -> list[str]:
    normalized = _normalize_name(requested_name)
    normalized = re.sub(r"\s+(?:exe|lnk|app)$", "", normalized)
    aliases = _APP_ALIASES.get(normalized, (normalized,))
    result: list[str] = []
    for name in aliases:
        candidate = _normalize_name(name)
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _resolve_application(requested_name: str) -> _InstalledApp | None:
    apps = _installed_apps()
    if not apps:
        return None

    candidate_names = _candidate_names(requested_name)
    normalized_apps = [(_normalize_name(app.name), app) for app in apps]

    # Prefer exact display-name / executable-name matches in alias order.
    for candidate in candidate_names:
        for app_name, app in normalized_apps:
            if candidate and candidate == app_name:
                return app

    # A conservative fuzzy match handles minor transcription mistakes without
    # making guesses across unrelated app names.
    best_app: _InstalledApp | None = None
    best_score = 0.0
    for candidate in candidate_names:
        for app_name, app in normalized_apps:
            if not candidate or not app_name:
                continue
            score = SequenceMatcher(None, candidate, app_name).ratio()
            if score > best_score:
                best_score = score
                best_app = app

    return best_app if best_score >= 0.90 else None


def _launch_target(app: _InstalledApp) -> None:
    """Launch one resolved installed target. Never uses shell=True."""
    if app.kind == "shortcut":
        if sys.platform == "win32":
            os.startfile(app.target)  # type: ignore[attr-defined]
            return
        raise OSError("Windows Start Menu shortcuts can only be opened on Windows.")

    if app.kind == "mac_app":
        subprocess.Popen(["open", "-a", app.target], close_fds=True)
        return

    if app.kind == "uri":
        if sys.platform != "win32":
            raise OSError("Windows app URIs can only be opened on Windows.")
        os.startfile(app.target)  # type: ignore[attr-defined]
        return

    target = Path(app.target)
    if not target.is_file():
        raise FileNotFoundError(f"Application executable no longer exists: {target}")

    kwargs = {"close_fds": True}
    if sys.platform == "win32":
        # Keep a GUI launch quiet; no shell parsing is involved.
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    subprocess.Popen([str(target)], **kwargs)


def launch_application(app_name: str) -> LaunchResult:
    """Find and launch an installed application by its display/executable name."""
    requested_name = str(app_name or "").strip()
    if not requested_name:
        return LaunchResult(False, requested_name, None, "Tell me which application to open.")

    # Avoid accidentally treating an arbitrary path, URL, or a command string
    # as an application name.
    if any(char in requested_name for char in ("/", "\\", "\n", "\r", "\0")):
        return LaunchResult(
            False,
            requested_name,
            None,
            "Please say the application name, not a file path or command.",
        )

    app = _resolve_application(requested_name)
    if app is None and sys.platform == "win32":
        # Windows Settings is a URI-activated app and may not have a normal
        # Start Menu shortcut on every installation. The URI is a constant,
        # never text constructed from the voice transcription.
        if _normalize_name(requested_name) in {"settings", "windows settings"}:
            app = _InstalledApp("Settings", "ms-settings:", "uri")

    if app is None:
        return LaunchResult(
            False,
            requested_name,
            None,
            f"I couldn't find an installed app named “{requested_name}”. Try its full app name.",
        )

    try:
        _launch_target(app)
    except Exception as exc:
        return LaunchResult(
            False,
            requested_name,
            app.name,
            f"I found {app.name}, but couldn't open it: {exc}",
        )

    return LaunchResult(True, requested_name, app.name, f"Opening {app.name}.")
