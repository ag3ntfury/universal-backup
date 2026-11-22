import tempfile
import unittest
from pathlib import Path
from universal_backup.manager import JobManager
from universal_backup.scheduler import SchedulerState
from universal_backup.devices import Device


class ManagerTests(unittest.TestCase):
    def test_local_missing_source_keeps_job_pending(self):
        with tempfile.TemporaryDirectory() as td:
            state = SchedulerState(Path(td) / "state.json")
            job = {
                "id": "missing-source",
                "source": {"type": "local", "entries": [{"name": "data", "path": str(Path(td)/"absent")}]},
                "destination": {"device": {"uuid": "USB-UUID"}, "path": "Backups"},
                "schedule": {"interval": "1d", "mode": "prompt"},
            }
            decision = JobManager(state).evaluate([job], [])
            self.assertEqual(decision[0]["status"], "waiting_for_device")
            self.assertIn("source:data", decision[0]["missing"])
            self.assertTrue(state.status(job)["pending"])

    def test_ready_local_job_matches_uuid_and_existing_source(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source"
            mount = Path(td) / "usb"
            source.mkdir()
            mount.mkdir()
            state = SchedulerState(Path(td) / "state.json")
            job = {
                "id": "ready",
                "source": {"type": "local", "entries": [{"name": "data", "path": str(source)}]},
                "destination": {"device": {"uuid": "USB-UUID"}, "path": "Backups"},
                "schedule": {"interval": "1d", "mode": "prompt"},
            }
            device = Device("storage", "filesystem_uuid", "USB-UUID", "USB", str(mount),
                            {"system": False, "removable": True})
            decision = JobManager(state).evaluate([job], [device])
            self.assertEqual(decision[0]["status"], "ready")
