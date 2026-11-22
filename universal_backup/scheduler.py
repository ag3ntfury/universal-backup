from datetime import datetime, timedelta, timezone
from pathlib import Path
import fcntl
import json
import os
import re
import tempfile

RX = re.compile(r"^(\d+)(m|h|d|w|mo)$", re.I)


def parse_interval(value, minimum=1800):
    match = RX.fullmatch(value.strip()) if isinstance(value, str) else None
    if not match or int(match.group(1)) < 1:
        raise ValueError(f"invalid interval: {value!r}")
    amount, unit = int(match.group(1)), match.group(2).lower()
    seconds = amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800, "mo": 2592000}[unit]
    if seconds < minimum or seconds > 30 * 86400:
        raise ValueError("interval must be 30 minutes to 30 days")
    return timedelta(seconds=seconds)


def now():
    return datetime.now(timezone.utc)


class SchedulerState:
    """Atomic, restart-safe scheduler state with process-level file locking."""

    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.data = {"schema": 2, "jobs": {}}
        self.reload()

    def reload(self):
        if not self.path.exists():
            self.data = {"schema": 2, "jobs": {}}
            return
        data = json.loads(self.path.read_text())
        if data.get("schema") not in (1, 2) or not isinstance(data.get("jobs"), dict):
            raise ValueError("invalid scheduler state")
        self.data = data
        self.data["schema"] = 2
        for record in self.data["jobs"].values():
            record.setdefault("declined_until", None)
            record.setdefault("running", None)
            record.setdefault("last_attempt", None)
            record.setdefault("attempt_count", 0)

    def record(self, job_id):
        return self.data["jobs"].setdefault(job_id, {
            "last_success": None, "pending": False, "skip_until": None,
            "last_result": None, "last_error": None, "declined_until": None,
            "running": None, "last_attempt": None, "attempt_count": 0,
        })

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Merge latest on-disk state so independent worker updates
                # cannot be overwritten by a stale daemon copy.
                disk = {"schema": 2, "jobs": {}}
                if self.path.exists():
                    disk = json.loads(self.path.read_text())
                disk.setdefault("jobs", {})
                disk["jobs"].update(self.data.get("jobs", {}))
                payload = {"schema": 2, "jobs": disk["jobs"]}
                fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
                try:
                    with os.fdopen(fd, "w") as stream:
                        json.dump(payload, stream, indent=2)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, self.path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                self.data = payload
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def status(self, job, at=None):
        at = at or now()
        record = self.record(job["id"])
        last = datetime.fromisoformat(record["last_success"]) if record["last_success"] else None
        due_at = last + parse_interval(job["schedule"]["interval"]) if last else at
        skip = datetime.fromisoformat(record["skip_until"]) if record["skip_until"] else None
        declined = datetime.fromisoformat(record["declined_until"]) if record.get("declined_until") else None
        running = record.get("running")
        due = (at >= due_at or record["pending"]) and not (skip and at < skip) and not (declined and at < declined)
        return {"due": bool(due and not running), "due_at": due_at, "last_success": last,
                "pending": record["pending"], "running": running}

    def skipped(self, job_id, duration="15m", at=None):
        until = (at or now()) + parse_interval(duration, 60)
        self.record(job_id).update(pending=True, skip_until=until.isoformat(), last_result="skipped")
        self.save()
        return until

    def denied(self, job_id, interval=None, at=None):
        delay = parse_interval(interval) if interval else timedelta(days=1)
        self.record(job_id).update(last_result="denied", declined_until=((at or now()) + delay).isoformat())
        self.save()

    def begin(self, job_id, at=None):
        record = self.record(job_id)
        if record.get("running"):
            raise RuntimeError(f"job {job_id} is already marked running")
        stamp = at or now()
        record.update(
            pending=True, running={"started_at": stamp.isoformat(), "pid": os.getpid()},
            last_attempt=stamp.isoformat(), attempt_count=record.get("attempt_count", 0) + 1,
            last_result="running", last_error=None,
        )
        self.save()

    def recover_interrupted(self):
        recovered = []
        for job_id, record in self.data["jobs"].items():
            if record.get("running"):
                started = record["running"].get("started_at")
                record.update(running=None, pending=True, last_result="interrupted",
                              last_error=f"Previous worker interrupted (started {started})")
                recovered.append(job_id)
        if recovered:
            self.save()
        return recovered

    def success(self, job_id, at=None):
        self.record(job_id).update(
            last_success=(at or now()).isoformat(), pending=False, skip_until=None,
            declined_until=None, running=None, last_result="success", last_error=None,
        )
        self.save()

    def failure(self, job_id, error):
        self.record(job_id).update(
            pending=True, running=None, last_result="failed", last_error=str(error)[:500]
        )
        self.save()

    def pending(self, job_id):
        record = self.record(job_id)
        if not record.get("pending"):
            record["pending"] = True
            self.save()
