import argparse
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

from .theme import banner, paint, GREEN, AMBER, RED
from .config import load_job, discover_jobs
from .devices import DeviceInventory
from .device_monitor import DeviceMonitor, format_device
from .scheduler import SchedulerState
from .manager import JobManager
from .devices import match_destination, match_android_source
from .resource_limits import run_limited
from .desktop_prompt import ask as desktop_ask, notify as desktop_notify


def _state(path):
    return SchedulerState(Path(path).expanduser())

def _execute(config_path, state_path):
    job = load_job(config_path)
    state = _state(state_path)
    devices = DeviceInventory().all()
    destination = match_destination(job, devices)
    source_device = match_android_source(job, devices) if job["source"]["type"] == "android" else True
    missing = []
    if destination is None:
        missing.append("destination")
    if source_device is None:
        missing.append("source")
    if job["source"]["type"] == "local":
        for entry in job["source"]["entries"]:
            source_path = Path(entry["path"]).expanduser()
            if not source_path.is_dir() or source_path.is_symlink():
                missing.append("source:" + entry["name"])
    if missing:
        state.failure(job["id"], "Worker could not find required " + ", ".join(missing))
        print(paint("[WAIT] Required " + ", ".join(missing) + " unavailable", AMBER))
        return 3
    decision = {"job": job, "status": "ready", "destination": destination}
    try:
        version = JobManager(state).run(decision)
        print(paint(f"[SUCCESS] {job['name']}: {version}", GREEN))
        return 0
    except Exception as exc:
        print(paint(f"[FAILED] {job['name']}: {exc}", RED), file=sys.stderr)
        return 2

def _reload_jobs(config_dir, current_jobs):
    """Load current profiles, retaining the last valid set on parse errors."""
    try:
        return discover_jobs(config_dir)
    except Exception as exc:
        print(paint(f"[CONFIG] Could not reload job profiles: {exc}. Keeping the last valid configuration.", AMBER), flush=True)
        return current_jobs


def _launch_worker(job, state_path):
    """Serialize all worker launches, persist intent, and reconcile worker state."""
    state_path = Path(state_path).expanduser()
    lock_path = state_path.with_suffix(state_path.suffix + ".worker.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(paint("[BUSY] Another Universal Backup worker is already running.", AMBER), flush=True)
            return 75

        state = _state(state_path)
        state.begin(job["id"])
        env = dict(os.environ)
        env["UNIVERSAL_BACKUP_WORKER"] = "1"
        command = [
            sys.executable, "-m", "universal_backup.cli", "execute",
            job["_config_path"], "--state-file", str(state_path),
        ]
        code = run_limited(command, job.get("resources"), env=env)
        state.reload()
        if code != 0:
            state.failure(job["id"], f"Worker exited with status {code}")
        return code


def _daemon(config_dir, state_path, poll_interval):
    jobs = discover_jobs(config_dir)
    if not jobs:
        print(paint(f"[IDLE] No enabled YAML jobs in {config_dir}", AMBER))
        return 0
    state = _state(state_path)
    # Prevent two scheduler daemons from processing the same profile set.
    lock_path = Path(state_path).with_suffix(Path(state_path).suffix + ".daemon.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    daemon_lock = lock_path.open("a+")
    try:
        fcntl.flock(daemon_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        daemon_lock.close()
        raise RuntimeError("another Universal Backup scheduler is already running")

    recovered = state.recover_interrupted()
    if recovered:
        print(paint(f"[RECOVERY] Interrupted jobs returned to pending: {', '.join(recovered)}", AMBER))
    manager = JobManager(state)
    waiting_reported = set()
    print(paint(f"[SCHEDULER] Loaded {len(jobs)} enabled job(s). Polling every {poll_interval:g}s. Ctrl+C to stop."))
    try:
        while True:
            state.reload()
            # Reload desktop-managed profiles without restarting the daemon.
            # A malformed edit never replaces the last known-good job set.
            jobs = _reload_jobs(config_dir, jobs)
            devices = DeviceInventory().all()
            decisions = manager.evaluate(jobs, devices)
            for decision in decisions:
                job = decision["job"]
                if decision["status"] != "ready":
                    signature = (job["id"], tuple(decision["missing"]))
                    if signature not in waiting_reported:
                        print(paint(f"[WAIT] {job['name']}: {', '.join(decision['missing'])}", AMBER), flush=True)
                        waiting_reported.add(signature)
                    continue
                waiting_reported = {x for x in waiting_reported if x[0] != job["id"]}
                mode = job["schedule"]["mode"]
                if mode == "prompt":
                    if os.environ.get("UNIVERSAL_BACKUP_DESKTOP") == "1":
                        answer = desktop_ask(job["name"])
                    else:
                        answer = input(paint(f"[DUE] {job['name']} — [Y]es / [N]o / [S]kip: ", AMBER)).strip().lower()
                    if answer in ("s", "skip"):
                        until = state.skipped(job["id"], job["schedule"].get("skip_reminder", "15m"))
                        print(paint(f"[SKIPPED] Reminder after {until.isoformat()}", AMBER))
                        desktop_notify("Backup postponed", f"{job['name']} will be checked again later.")
                        continue
                    if answer not in ("y", "yes"):
                        state.denied(job["id"], job["schedule"]["interval"])
                        print(paint(f"[DECLINED] {job['name']}; reconsider after its interval.", AMBER))
                        desktop_notify("Backup not started", f"{job['name']} was declined.")
                        continue
                print(paint(f"[START] {job['name']} ({mode})", GREEN), flush=True)
                code = _launch_worker(job, state_path)
                state.reload()
                if code == 0:
                    print(paint(f"[DONE] {job['name']}", GREEN), flush=True)
                    desktop_notify("Backup completed", f"{job['name']} finished successfully.")
                else:
                    state.failure(job["id"], f"Worker exited with status {code}")
                    print(paint(f"[ERROR] {job['name']} worker exited with status {code}; job remains pending.", RED), flush=True)
                    desktop_notify("Backup failed", f"{job['name']} failed (exit {code}). It remains pending for retry.", "critical")
                # Enforce a single worker at a time and refresh due decisions
                # before another job is considered.
                break
            time.sleep(poll_interval)
    finally:
        fcntl.flock(daemon_lock.fileno(), fcntl.LOCK_UN)
        daemon_lock.close()

def main(argv=None):
    parser = argparse.ArgumentParser(prog="universal-backup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    validate = sub.add_parser("validate")
    validate.add_argument("config")
    run = sub.add_parser("run")
    run.add_argument("config")
    run.add_argument("--state-file", default=str(Path.home()/".local/state/universal-backup/state.json"))
    tick = sub.add_parser("tick")
    tick.add_argument("--config-dir", default="config")
    tick.add_argument("--state-file", default="state/scheduler.json")
    daemon = sub.add_parser("daemon", help="run persistent multi-job scheduler")
    daemon.add_argument("--config-dir", default="config")
    daemon.add_argument("--state-file", default=str(Path.home()/".local/state/universal-backup/state.json"))
    daemon.add_argument("--poll-interval", type=float, default=5.0)
    ui = sub.add_parser("ui", help="open the desktop dashboard")
    monitor = sub.add_parser("monitor", help="watch supported device connections")
    monitor.add_argument("--interval", type=float, default=2.0)
    monitor.add_argument("--no-initial", action="store_true")
    execute = sub.add_parser("execute", help=argparse.SUPPRESS)
    execute.add_argument("config")
    execute.add_argument("--state-file", required=True)

    args = parser.parse_args(argv)
    banner()
    try:
        if args.cmd == "ui":
            from .desktop import main as desktop_main
            return desktop_main()

        if args.cmd == "devices":
            devices = DeviceInventory().all()
            for index, device in enumerate(devices, 1):
                print(paint(f"[{index}] {format_device(device)}"))
            if not devices:
                print(paint("[WAIT] No supported devices detected", AMBER))
            return 0

        if args.cmd == "monitor":
            print(paint("[MONITOR] Watching supported storage and authorised Android devices. Ctrl+C to stop."))
            def report(event, device):
                color = AMBER if event == "disconnected" else GREEN
                print(paint(f"[{event.upper()}] {format_device(device)}", color), flush=True)
            DeviceMonitor(interval=args.interval).watch(report, emit_initial=not args.no_initial)
            return 0

        if args.cmd == "validate":
            job = load_job(args.config)
            print(paint(f"[OK] {job['name']} configuration valid", GREEN))
            return 0

        if args.cmd == "execute":
            return _execute(args.config, args.state_file)

        if args.cmd == "daemon":
            if args.poll_interval < 1:
                raise ValueError("poll interval must be at least 1 second")
            return _daemon(args.config_dir, Path(args.state_file).expanduser(), args.poll_interval)

        if args.cmd == "run":
            job = load_job(args.config)
            state = _state(args.state_file)
            decision = JobManager(state).evaluate([job], DeviceInventory().all())
            if not decision or decision[0]["status"] != "ready":
                print(paint("[WAIT] Job is not due or required devices are unavailable", AMBER))
                return 3
            if job["schedule"]["mode"] == "prompt":
                answer = input(paint("Start backup? [y/N]: ", AMBER)).strip().lower()
                if answer not in ("y", "yes"):
                    state.denied(job["id"], job["schedule"]["interval"])
                    return 1
            return _launch_worker(job, Path(args.state_file).expanduser())

        if args.cmd == "tick":
            jobs = discover_jobs(args.config_dir)
            state = _state(args.state_file)
            decisions = JobManager(state).evaluate(jobs, DeviceInventory().all())
            for decision in decisions:
                job = decision["job"]
                if decision["status"] != "ready":
                    print(paint(f"[WAIT] {job['name']}: {', '.join(decision['missing'])}", AMBER))
                else:
                    print(paint(f"[DUE] {job['name']} ({job['schedule']['mode']})", GREEN))
            if not decisions:
                print(paint("[IDLE] No due jobs", AMBER))
            return 0
    except KeyboardInterrupt:
        print(paint("\\n[STOP] Universal Backup stopped", AMBER))
        return 130
    except Exception as exc:
        print(paint(f"[ERROR] {exc}", RED), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
