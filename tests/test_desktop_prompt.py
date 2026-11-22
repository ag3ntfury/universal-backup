import unittest
from unittest.mock import patch
from universal_backup import desktop_prompt


class DesktopPromptTests(unittest.TestCase):
    @patch("universal_backup.desktop_prompt.shutil.which", return_value=None)
    @patch("universal_backup.desktop_prompt.notify")
    def test_missing_zenity_safely_declines(self, notify, which):
        self.assertEqual(desktop_prompt.ask("Example Job"), "no")
        notify.assert_called_once()

    @patch("universal_backup.desktop_prompt.shutil.which", return_value="/usr/bin/zenity")
    @patch("universal_backup.desktop_prompt.subprocess.run")
    def test_zenity_accept(self, run, which):
        run.return_value.returncode = 0
        self.assertEqual(desktop_prompt.ask("Example Job"), "yes")

    @patch("universal_backup.desktop_prompt.shutil.which", return_value="/usr/bin/zenity")
    @patch("universal_backup.desktop_prompt.subprocess.run")
    def test_zenity_skip(self, run, which):
        run.return_value.returncode = 5
        self.assertEqual(desktop_prompt.ask("Example Job"), "skip")

    @patch("universal_backup.desktop_prompt.shutil.which", return_value="/usr/bin/zenity")
    @patch("universal_backup.desktop_prompt.subprocess.run")
    def test_zenity_decline(self, run, which):
        run.return_value.returncode = 1
        self.assertEqual(desktop_prompt.ask("Example Job"), "no")


if __name__ == "__main__":
    unittest.main()
