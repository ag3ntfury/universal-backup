import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from universal_backup.cli import _execute
from universal_backup.devices import Device
from universal_backup.scheduler import SchedulerState
from universal_backup.engine import verify


class WorkerTests(unittest.TestCase):
    def test_worker_runs_job_already_marked_running(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source = base / "source"
            mount = base / "usb"
            source.mkdir()
            mount.mkdir()
            (source / "sample.txt").write_text("worker test")
            config = base / "job.yaml"
            config.write_text(f"""
id: worker-test
name: Worker Test
enabled: true
source:
  type: local
  paths: [{source}]
destination:
  device: {{type: storage, identifier_type: filesystem_uuid, uuid: FAKE-USB}}
  path: Backup
schedule: {{interval: 1d, mode: auto}}
backup: {{integrity: sha256, verify_after_backup: true}}
""")
            state_path = base / "state.json"
            state = SchedulerState(state_path)
            state.begin("worker-test")
            fake = Device("storage", "filesystem_uuid", "FAKE-USB", "Fake USB",
                          str(mount), {"system": False, "removable": True})
            findmnt_result = SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"filesystems": [{"target": str(mount), "uuid": "FAKE-USB"}]}),
                stderr="",
            )
            # _execute() performs its initial readiness scan through cli.DeviceInventory.
            # JobManager independently refreshes storage immediately before writing,
            # so its inventory and findmnt identity checks must be mocked separately.
            with patch("universal_backup.cli.DeviceInventory") as inventory, \
                 patch("universal_backup.manager.DeviceInventory") as manager_inventory, \
                 patch("universal_backup.manager.subprocess.run", return_value=findmnt_result):
                inventory.return_value.all.return_value = [fake]
                manager_inventory.return_value.storage.return_value = [fake]
                result = _execute(config, state_path)
            self.assertEqual(result, 0)
            record = SchedulerState(state_path).record("worker-test")
            self.assertIsNone(record["running"])
            self.assertFalse(record["pending"])
            self.assertEqual(record["last_result"], "success")
            self.assertEqual(verify(mount / "Backup")["versions"], 1)
