# Architecture

Universal Backup is split into a core scheduler/engine and optional desktop surfaces.

- `config.py`: validates job YAML and discovers enabled jobs.
- `devices.py` and `device_monitor.py`: read-only storage/ADB inventory and debounced device events.
- `scheduler.py`: persistent due/pending/running state, atomic writes and interrupted-job recovery.
- `manager.py`: evaluates jobs and coordinates source staging plus engine execution.
- `engine.py`: versioned content-addressed backup, verification and restore.
- `resource_limits.py`: worker resource policy and systemd-scope launcher.
- `cli.py`: command-line interface and resident scheduler.
- `desktop.py`: optional Tk dashboard for job creation and service control.
- `desktop_prompt.py`: optional Zenity prompt and desktop notifications; headless fallback is safe-deny.

The systemd unit is installed per user. It starts the scheduler but does not elevate privileges. The daemon polls inventory on a configurable interval; direct event-to-job dispatch is future work. The desktop app and daemon share job profiles and state under XDG config/state directories.

The current release uses one global worker lock per state file and a separate daemon lock. Scheduler state records intent before a worker starts. A restarted daemon converts stale running markers into pending interrupted jobs. The engine's atomic version commit and content-addressed writes provide the current recovery boundary; this is not a transactional journal for every individual file operation.
