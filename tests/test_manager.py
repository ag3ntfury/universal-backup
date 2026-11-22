import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from universal_backup.devices import Device
from universal_backup.manager import JobManager
from universal_backup.scheduler import SchedulerState


class FakeInventory:
    def __init__(self, devices):
        self.devices = devices

    def storage(self):
        return list(self.devices)


class ManagerTests(unittest.TestCase):
    def test_local_missing_source_keeps_job_pending(self):
        with tempfile.TemporaryDirectory() as td:
            state = SchedulerState(Path(td) / "state.json")
            job = {
                "id": "missing-source",
                "source": {"type": "local", "entries": [{"name": "data", "path": str(Path(td) / "absent")}]},
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

    def _job_and_decision(self, td, destination_path="Backups"):
        base = Path(td)
        source = base / "source"
        mount = base / "usb"
        source.mkdir()
        mount.mkdir()
        state = SchedulerState(base / "state.json")
        job = {
            "id": "mount-check",
            "source": {"type": "local", "entries": [{"name": "data", "path": str(source)}]},
            "destination": {"device": {"uuid": "USB-UUID"}, "path": destination_path},
            "schedule": {"interval": "1d", "mode": "prompt"},
        }
        device = Device("storage", "filesystem_uuid", "USB-UUID", "USB", str(mount),
                        {"system": False, "removable": True})
        decision = {"job": job, "status": "ready", "destination": device}
        return state, job, mount, device, decision

    @staticmethod
    def _findmnt_runner(mount, uuid="USB-UUID", nested=None, submounts=()):
        def runner(args, **kwargs):
            if "--target" not in args:
                targets = [str(mount), *(str(path) for path in submounts)]
                if nested is not None:
                    targets.append(str(nested[0]))
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"filesystems": [{"target": path} for path in targets]}),
                    stderr="",
                )
            target = Path(args[args.index("--target") + 1])
            if nested is not None and target == nested[0]:
                reported_target, reported_uuid = nested
            else:
                reported_target, reported_uuid = mount, uuid
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"filesystems": [{"target": str(reported_target), "uuid": reported_uuid}]}),
                stderr="",
            )
        return runner

    def test_run_rechecks_uuid_before_calling_backup(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount, uuid="WRONG-UUID"),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "UUID does not match"):
                    manager.run(decision)
            backup_call.assert_not_called()
            self.assertFalse((mount / "Backups").exists())

    def test_run_refuses_destination_filesystem_that_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            manager = JobManager(state, inventory=FakeInventory([]), mount_runner=self._findmnt_runner(mount))
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "not currently available"):
                    manager.run(decision)
            backup_call.assert_not_called()
            self.assertFalse((mount / "Backups").exists())

    def test_run_refuses_destination_inside_a_different_nested_mount(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            nested_mount = mount / "Backups"
            nested_mount.mkdir()
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount, nested=(nested_mount, "OTHER-UUID")),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "different filesystem"):
                    manager.run(decision)
            backup_call.assert_not_called()

    def test_run_refuses_nested_mount_below_destination_root(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            nested_mount = mount / "Backups" / "mounted-subdirectory"
            nested_mount.mkdir(parents=True)
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount, submounts=[nested_mount]),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "nested mountpoint"):
                    manager.run(decision)
            backup_call.assert_not_called()

    def test_run_refuses_mountpoint_at_destination_root_even_with_same_uuid(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            nested_mount = mount / "Backups"
            nested_mount.mkdir()
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount, submounts=[nested_mount]),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "intersects a nested mountpoint"):
                    manager.run(decision)
            backup_call.assert_not_called()

    def test_run_refuses_intermediate_mountpoint_above_destination_root(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            job["destination"]["path"] = "Backups/Subdirectory"
            intermediate_mount = mount / "Backups"
            intermediate_mount.mkdir()
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount, submounts=[intermediate_mount]),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "intersects a nested mountpoint"):
                    manager.run(decision)
            backup_call.assert_not_called()

    def test_run_uses_fresh_mountpoint_from_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, old_mount, old_device, decision = self._job_and_decision(td)
            new_mount = Path(td) / "usb-new"
            new_mount.mkdir()
            new_device = Device("storage", "filesystem_uuid", "USB-UUID", "USB", str(new_mount),
                                {"system": False, "removable": True})
            manager = JobManager(
                state,
                inventory=FakeInventory([new_device]),
                mount_runner=self._findmnt_runner(new_mount),
            )
            with patch("universal_backup.manager.backup", return_value="V000001") as backup_call:
                self.assertEqual(manager.run(decision), "V000001")
            backup_call.assert_called_once()
            self.assertEqual(backup_call.call_args.args[1], new_mount / "Backups")
            self.assertFalse((old_mount / "Backups").exists())

    def test_run_refuses_when_mountpoint_is_covered_by_another_mount(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            runner = self._findmnt_runner(mount)
            def covered_runner(args, **kwargs):
                result = runner(args, **kwargs)
                target = Path(args[args.index("--target") + 1])
                if target == mount:
                    result.stdout = json.dumps({"filesystems": [{"target": "/", "uuid": "USB-UUID"}]})
                return result
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=covered_runner,
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "no longer mounted"):
                    manager.run(decision)
            backup_call.assert_not_called()
            self.assertFalse((mount / "Backups").exists())

    def test_run_refuses_destination_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            state, job, mount, device, decision = self._job_and_decision(td)
            outside = Path(td) / "outside"
            outside.mkdir()
            (mount / "Backups").symlink_to(outside, target_is_directory=True)
            manager = JobManager(
                state,
                inventory=FakeInventory([device]),
                mount_runner=self._findmnt_runner(mount),
            )
            with patch("universal_backup.manager.backup") as backup_call:
                with self.assertRaisesRegex(RuntimeError, "symbolic link"):
                    manager.run(decision)
            backup_call.assert_not_called()
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
