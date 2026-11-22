from pathlib import Path
import shutil
from .devices import match_destination, match_android_source
from .engine import backup
from .android import stage_adb_sources


class JobManager:
    def __init__(self, state):
        self.state = state

    def evaluate(self, jobs, devices, at=None):
        result = []
        for job in jobs:
            status = self.state.status(job, at)
            if not status["due"]:
                continue
            dest = match_destination(job, devices)
            source_device = match_android_source(job, devices) if job["source"]["type"] == "android" else True
            missing = []
            if dest is None:
                missing.append("destination")
            if source_device is None:
                missing.append("source")
            if job["source"]["type"] == "local":
                for entry in job["source"]["entries"]:
                    source_path = Path(entry["path"]).expanduser()
                    if not source_path.is_dir() or source_path.is_symlink():
                        missing.append("source:" + entry["name"])
            if missing:
                self.state.pending(job["id"])
                result.append({"job": job, "status": "waiting_for_device", "missing": missing, "destination": dest})
            else:
                result.append({"job": job, "status": "ready", "destination": dest})
        return result

    def run(self, decision):
        if decision["status"] != "ready":
            raise RuntimeError("job is not ready")
        job = decision["job"]
        mount = Path(decision["destination"].mountpoint).resolve()
        root = (mount / job["destination"]["path"]).resolve()
        if root != mount and mount not in root.parents:
            raise RuntimeError("destination path escapes mounted filesystem")
        stage = None
        try:
            if job["source"]["type"] == "android":
                stage, sources = stage_adb_sources(job["source"]["device_id"], job["source"]["entries"])
            else:
                sources = [(entry["name"], Path(entry["path"]).expanduser()) for entry in job["source"]["entries"]]
            version = backup(sources, root, job["id"])
            self.state.success(job["id"])
            return version
        except Exception as exc:
            self.state.failure(job["id"], exc)
            raise
        finally:
            if stage:
                shutil.rmtree(stage, ignore_errors=True)
