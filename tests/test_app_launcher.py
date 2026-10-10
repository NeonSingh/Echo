"""Offline tests for ECHO's explicit application-launch command handling."""

import unittest
from unittest.mock import patch

from backend_pipeline import app_launcher


class ExtractOpenAppRequestTests(unittest.TestCase):
    def test_supported_commands(self):
        cases = {
            "open Chrome": "Chrome",
            "Could you please open Visual Studio Code?": "Visual Studio Code",
            "Echo, launch Spotify": "Spotify",
            "start up Notepad for me": "Notepad",
            "please run Microsoft Word now": "Microsoft Word",
            "Echo can you open Windows Terminal": "Windows Terminal",
        }
        for spoken, expected in cases.items():
            with self.subTest(spoken=spoken):
                self.assertEqual(app_launcher.extract_open_app_request(spoken), expected)

    def test_rejects_non_commands(self):
        for spoken in ("tell me how to open Chrome", "I like Spotify", "open", ""):
            with self.subTest(spoken=spoken):
                self.assertIsNone(app_launcher.extract_open_app_request(spoken))

    def test_rejects_path_like_application_name_at_launch_boundary(self):
        result = app_launcher.launch_application(r"C:\\Windows\\System32\\notepad.exe")
        self.assertFalse(result.success)
        self.assertIn("application name", result.message)


class ResolveAppTests(unittest.TestCase):
    @patch("backend_pipeline.app_launcher._installed_apps")
    def test_alias_resolves_google_chrome(self, installed_apps):
        installed_apps.return_value = [
            app_launcher._InstalledApp("Google Chrome", r"C:\\Apps\\chrome.lnk", "shortcut"),
            app_launcher._InstalledApp("Firefox", r"C:\\Apps\\firefox.lnk", "shortcut"),
        ]
        result = app_launcher._resolve_application("chrome")
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "Google Chrome")

    @patch("backend_pipeline.app_launcher._launch_target")
    @patch("backend_pipeline.app_launcher._installed_apps")
    def test_launch_uses_resolved_target(self, installed_apps, launch_target):
        installed_apps.return_value = [
            app_launcher._InstalledApp("Notepad", r"C:\\Windows\\notepad.exe", "executable")
        ]
        result = app_launcher.launch_application("Notepad")
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Opening Notepad.")
        launch_target.assert_called_once()


if __name__ == "__main__":
    unittest.main()
