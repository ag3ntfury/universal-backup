import fcntl
import tempfile
import unittest
from pathlib import Path
from universal_backup.cli import _daemon, _launch_worker, _reload_jobs


class DaemonTests(unittest.TestCase):
    def test_second_daemon_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "jobs"
            config.mkdir()
            (config / "job.yaml").write_text("""
id: test
name: Test
enabled: true
source:
  type: local
  paths: [/definitely/not/a/real/source]
destination:
  device: {type: storage, identifier_type: filesystem_uuid, uuid: FAKE}
  path: Test
schedule: {interval: 1d, mode: auto}
backup: {integrity: sha256, verify_after_backup: true}
""")
            state = Path(td) / "state.json"
            lock_path = state.with_suffix(state.suffix + ".daemon.lock")
            with lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(RuntimeError):
                    _daemon(config, state, 1)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def test_worker_launch_lock_prevents_parallel_worker(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "state.json"
            lock_path = state.with_suffix(state.suffix + ".worker.lock")
            with lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = _launch_worker({"id": "j", "_config_path": "unused", "resources": {}}, state)
                self.assertEqual(result, 75)
                self.assertFalse(state.exists())
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class JobReloadTests(unittest.TestCase):
    def test_reload_picks_up_added_job(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "job.yaml"
            config.write_text("""
id: reload-test
name: Reload Test
enabled: true
source:
  type: local
  paths: [/tmp/reload-source]
destination:
  device: {type: storage, identifier_type: filesystem_uuid, uuid: RELOAD-UUID}
  path: Backups/Reload
schedule: {interval: 1d, mode: prompt}
backup: {integrity: sha256, verify_after_backup: true}
""")
            jobs = _reload_jobs(td, [])
            self.assertEqual([job["id"] for job in jobs], ["reload-test"])

    def test_invalid_edit_keeps_last_valid_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "broken.yaml"
            config.write_text("not: [valid")
            previous = [{"id": "known-good"}]
            self.assertEqual(_reload_jobs(td, previous), previous)
