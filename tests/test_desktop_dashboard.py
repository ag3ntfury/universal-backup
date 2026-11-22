import unittest
from unittest.mock import patch
from types import SimpleNamespace

from universal_backup.desktop import _job_status, _systemctl


class DesktopDashboardHelperTests(unittest.TestCase):
    def test_job_status_prioritizes_running(self):
        self.assertEqual(_job_status({"running": {"pid": 1}, "pending": True}), "Running")

    def test_job_status_pending(self):
        self.assertEqual(_job_status({"pending": True}), "Pending / retry")

    def test_job_status_success(self):
        self.assertEqual(_job_status({"last_result": "success"}), "Completed")

    def test_job_status_failure(self):
        self.assertEqual(_job_status({"last_result": "failed"}), "Needs attention")

    @patch("universal_backup.desktop.subprocess.run")
    def test_systemctl_uses_user_service(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="active", stderr="")
        result = _systemctl("is-active")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_args.args[0], ["systemctl", "--user", "is-active", "universal-backup.service"])


if __name__ == "__main__":
    unittest.main()
