"""Tk desktop dashboard for Universal Backup.

The Add Job and Edit Job actions share one validated, multi-section editor.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import yaml

from .config import load_job
from .devices import DeviceInventory

APP = "Universal Backup"
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "universal-backup" / "jobs"
STATE_FILE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "universal-backup" / "state.json"
REFRESH_MS = 5000
BG = "#090d0a"
PANEL = "#101710"
GREEN = "#64f078"
TEXT = "#d9f5dd"
MUTED = "#a9b9aa"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args, "universal-backup.service"],
        text=True, capture_output=True, check=False,
    )


def _job_files():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([*CONFIG_DIR.glob("*.yaml"), *CONFIG_DIR.glob("*.yml")])


def _read_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"jobs": {}}
    except (OSError, ValueError, TypeError):
        return {"jobs": {}}


def _job_status(record: dict) -> str:
    if record.get("running"):
        return "Running"
    if record.get("pending"):
        return "Pending / retry"
    if record.get("last_result") == "success":
        return "Completed"
    if record.get("last_result") in ("failed", "interrupted"):
        return "Needs attention"
    return "Waiting for schedule"


def _safe_relative_path(value: str) -> str:
    """Normalize a destination-relative path and reject unsafe components."""
    raw = value.strip()
    if not raw:
        raise ValueError("Destination folder is required.")
    if "\x00" in raw or "\n" in raw or "\r" in raw or "\t" in raw:
        raise ValueError("Destination path cannot contain control characters.")
    # Accept either slash style, but always store POSIX-style relative paths.
    raw = raw.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("Destination must be a relative path, not an absolute path.")
    parts = [part.strip() for part in raw.split("/") if part.strip() not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("Destination path cannot be empty or contain '..'.")
    if any(part in (".", "..") for part in parts):
        raise ValueError("Destination path contains an unsafe component.")
    if any(any(ord(ch) < 32 for ch in part) for part in parts):
        raise ValueError("Destination path cannot contain control characters.")
    return "/".join(parts)


class JobEditor:
    """Modal editor for all supported local-job settings."""

    def __init__(self, parent, initial: dict | None = None, devices=None):
        self.parent = parent
        self.initial = dict(initial or {})
        self.devices = list(devices or [])
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("Edit backup job" if initial else "Add backup job")
        self.window.transient(parent)
        self.window.geometry("780x760")
        self.window.minsize(680, 620)
        self.window.configure(bg=BG)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)

        self.name = tk.StringVar(value=self.initial.get("name", ""))
        self.enabled = tk.BooleanVar(value=self.initial.get("enabled", True))
        self.interval = tk.StringVar(value=self.initial.get("schedule", {}).get("interval", "7d"))
        self.mode = tk.StringVar(value=self.initial.get("schedule", {}).get("mode", "prompt"))
        self.skip_reminder = tk.StringVar(value=self.initial.get("schedule", {}).get("skip_reminder", "15m"))
        self.destination_path = tk.StringVar(value=self.initial.get("destination", {}).get("path", ""))
        self.memory_high = tk.StringVar(value=str(self.initial.get("resources", {}).get("memory_high", "1G")))
        self.memory_max = tk.StringVar(value=str(self.initial.get("resources", {}).get("memory_max", "2G")))
        self.cpu_weight = tk.StringVar(value=str(self.initial.get("resources", {}).get("cpu_weight", 20)))
        self.io_weight = tk.StringVar(value=str(self.initial.get("resources", {}).get("io_weight", 20)))
        self.nice = tk.StringVar(value=str(self.initial.get("resources", {}).get("nice", 10)))
        self.ionice_class = tk.StringVar(value=str(self.initial.get("resources", {}).get("ionice_class", 3)))
        self.android_source = self.initial.get("source", {}).get("type") == "android"

        self.source_entries = []
        for entry in self.initial.get("source", {}).get("entries", []):
            self.source_entries.append({"name": str(entry.get("name", "")), "path": str(entry.get("path", ""))})
        if not self.source_entries and self.initial.get("source", {}).get("paths"):
            for index, path in enumerate(self.initial["source"]["paths"], 1):
                self.source_entries.append({"name": Path(str(path)).name or f"source-{index}", "path": str(path)})

        self._device_options = []
        self.device_var = tk.StringVar()
        self._prepare_devices()
        self._build()
        self.window.grab_set()
        self.window.focus_set()
        self.window.wait_window()

    def _prepare_devices(self):
        current_uuid = self.initial.get("destination", {}).get("device", {}).get("uuid")
        seen = set()
        for device in self.devices:
            if not device.mountpoint or (device.metadata or {}).get("system"):
                continue
            if not device.identifier or device.identifier in seen:
                continue
            seen.add(device.identifier)
            label = f"{device.label} — {device.mountpoint}  [UUID: {device.identifier}]"
            self._device_options.append((label, device.identifier, device.mountpoint))
        if current_uuid and current_uuid not in seen:
            label = f"Saved destination (currently unavailable)  [UUID: {current_uuid}]"
            self._device_options.append((label, current_uuid, None))
        selected = next((x[0] for x in self._device_options if x[1] == current_uuid), "")
        self.device_var.set(selected or (self._device_options[0][0] if self._device_options else ""))

    def _section(self, parent, title, subtitle=None):
        frame = tk.LabelFrame(parent, text=title, bg=BG, fg=GREEN, padx=12, pady=10)
        if subtitle:
            tk.Label(frame, text=subtitle, bg=BG, fg=MUTED, justify="left", anchor="w", wraplength=690).pack(fill="x", pady=(0, 8))
        return frame

    def _field(self, parent, label, variable, width=42):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, bg=BG, fg=TEXT, width=23, anchor="w").pack(side="left")
        entry = ttk.Entry(row, textvariable=variable, width=width)
        entry.pack(side="left", fill="x", expand=True)
        return entry

    def _build(self):
        heading = tk.Frame(self.window, bg=BG, padx=18, pady=12)
        heading.pack(fill="x")
        tk.Label(heading, text="BACKUP JOB CONFIGURATION", bg=BG, fg=GREEN,
                 font=("DejaVu Sans", 14, "bold")).pack(anchor="w")
        tk.Label(heading, text="Configure sources, destination, schedule and resource limits.",
                 bg=BG, fg=MUTED).pack(anchor="w", pady=(3, 0))

        notebook = ttk.Notebook(self.window)
        notebook.pack(fill="both", expand=True, padx=14, pady=8)

        general = tk.Frame(notebook, bg=BG, padx=14, pady=12)
        sources = tk.Frame(notebook, bg=BG, padx=14, pady=12)
        destination = tk.Frame(notebook, bg=BG, padx=14, pady=12)
        advanced = tk.Frame(notebook, bg=BG, padx=14, pady=12)
        notebook.add(general, text="General & Schedule")
        notebook.add(sources, text="Sources")
        notebook.add(destination, text="Destination")
        notebook.add(advanced, text="Resources")

        box = self._section(general, "Job identity")
        box.pack(fill="x", pady=(0, 10))
        self._field(box, "Job name", self.name)
        tk.Checkbutton(box, text="Job enabled", variable=self.enabled, bg=BG, fg=TEXT,
                       activebackground=BG, activeforeground=GREEN, selectcolor=PANEL).pack(anchor="w", pady=5)

        box = self._section(general, "Backup schedule", "Intervals: 30m to 30d. Examples: 30m, 12h, 1d, 7d.")
        box.pack(fill="x")
        self._field(box, "Backup interval", self.interval)
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", pady=5)
        tk.Label(row, text="When backup is due", bg=BG, fg=TEXT, width=23, anchor="w").pack(side="left")
        ttk.Combobox(row, textvariable=self.mode, values=("prompt", "auto"), state="readonly", width=18).pack(side="left")
        self._field(box, "Skip reminder", self.skip_reminder)

        box = self._section(sources, "Source folders",
                            "Add one or more local folders. Each source is backed up under its own named folder.")
        box.pack(fill="both", expand=True)
        if self.android_source:
            tk.Label(box, text="This profile uses an Android ADB source. Its Android device and remote paths are preserved unchanged in this editor.",
                     bg=BG, fg="#f0c66a", wraplength=680, justify="left").pack(anchor="w", pady=5)
            tk.Label(box, text="Local source editing is disabled for this Android profile.",
                     bg=BG, fg=MUTED).pack(anchor="w")
        else:
            columns = ("alias", "path")
            self.source_tree = ttk.Treeview(box, columns=columns, show="headings", height=11, selectmode="browse")
            self.source_tree.heading("alias", text="Source name")
            self.source_tree.heading("path", text="Folder path")
            self.source_tree.column("alias", width=150, minwidth=100)
            self.source_tree.column("path", width=470, minwidth=250)
            self.source_tree.pack(fill="both", expand=True, pady=5)
            for item in self.source_entries:
                self.source_tree.insert("", "end", values=(item["name"], item["path"]))
            buttons = tk.Frame(box, bg=BG)
            buttons.pack(fill="x", pady=6)
            ttk.Button(buttons, text="＋ Add folder", command=self.add_source).pack(side="left")
            ttk.Button(buttons, text="Remove selected", command=self.remove_source).pack(side="left", padx=7)
            ttk.Button(buttons, text="Rename source", command=self.rename_source).pack(side="left")

        box = self._section(destination, "Backup destination",
                            "Select a mounted non-system storage drive. The profile stores its filesystem UUID, not its mountpoint.")
        box.pack(fill="x", pady=(0, 10))
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", pady=5)
        tk.Label(row, text="Destination drive", bg=BG, fg=TEXT, width=23, anchor="w").pack(side="left")
        choices = [item[0] for item in self._device_options]
        self.device_combo = ttk.Combobox(row, textvariable=self.device_var, values=choices,
                                         state="readonly" if choices else "disabled", width=68)
        self.device_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Refresh drives", command=self.refresh_devices).pack(side="left", padx=(6, 0))
        self._field(box, "Folder on destination", self.destination_path)
        if not choices:
            tk.Label(box, text="No eligible mounted destination drive detected. Connect a non-system drive and refresh.",
                     bg=BG, fg="#f0c66a", wraplength=680, justify="left").pack(anchor="w", pady=5)

        box = self._section(advanced, "Worker resource limits",
                            "Conservative defaults. These limits apply to backup workers, not the desktop dashboard.")
        box.pack(fill="x")
        self._field(box, "Memory high", self.memory_high)
        self._field(box, "Memory maximum", self.memory_max)
        self._field(box, "CPU weight (1–10000)", self.cpu_weight)
        self._field(box, "I/O weight (1–10000)", self.io_weight)
        self._field(box, "Process nice (-20–19)", self.nice)
        self._field(box, "I/O priority class (1–3)", self.ionice_class)
        tk.Label(advanced, text="SHA-256 integrity and post-backup verification are mandatory. Automatic pruning remains disabled.",
                 bg=BG, fg=MUTED, wraplength=680, justify="left").pack(anchor="w", pady=14)

        footer = tk.Frame(self.window, bg=BG, padx=18, pady=12)
        footer.pack(fill="x")
        self.error_var = tk.StringVar()
        tk.Label(footer, textvariable=self.error_var, bg=BG, fg="#ff9a8d",
                 justify="left", wraplength=520).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(footer, text="Save job", command=self.save).pack(side="right", padx=8)

    def refresh_devices(self):
        current = self.device_var.get()
        self.devices = list(DeviceInventory().storage())
        self._device_options = []
        self._prepare_devices()
        values = [item[0] for item in self._device_options]
        self.device_combo.configure(values=values, state="readonly" if values else "disabled")
        if current in values:
            self.device_var.set(current)

    def add_source(self):
        path = filedialog.askdirectory(title="Choose a source folder", parent=self.window)
        if not path:
            return
        path = str(Path(path).expanduser().resolve())
        if any(Path(item["path"]).expanduser().resolve() == Path(path) for item in self.source_entries):
            messagebox.showwarning(APP, "That source folder is already in this job.", parent=self.window)
            return
        alias = Path(path).name or "source"
        used = {item["name"] for item in self.source_entries}
        base = alias
        counter = 2
        while alias in used:
            alias = f"{base}-{counter}"
            counter += 1
        self.source_entries.append({"name": alias, "path": path})
        self._render_sources()

    def _render_sources(self):
        for row in self.source_tree.get_children():
            self.source_tree.delete(row)
        for item in self.source_entries:
            self.source_tree.insert("", "end", values=(item["name"], item["path"]))

    def remove_source(self):
        selected = self.source_tree.selection()
        if not selected:
            return
        index = self.source_tree.index(selected[0])
        del self.source_entries[index]
        self._render_sources()

    def rename_source(self):
        selected = self.source_tree.selection()
        if not selected:
            messagebox.showinfo(APP, "Select a source folder first.", parent=self.window)
            return
        index = self.source_tree.index(selected[0])
        from tkinter import simpledialog
        name = simpledialog.askstring(APP, "Source name:", initialvalue=self.source_entries[index]["name"], parent=self.window)
        if name is None:
            return
        name = name.strip()
        if not name or any(ch in name for ch in ("/", "\\", "\x00")):
            messagebox.showerror(APP, "Enter a valid source name without path separators.", parent=self.window)
            return
        if any(i != index and item["name"] == name for i, item in enumerate(self.source_entries)):
            messagebox.showerror(APP, "Source names must be unique.", parent=self.window)
            return
        self.source_entries[index]["name"] = name
        self._render_sources()

    def _selected_device(self):
        return next((item for item in self._device_options if item[0] == self.device_var.get()), None)

    def _build_config(self):
        name = self.name.get().strip()
        if not name:
            raise ValueError("Enter a job name.")
        if len(name) > 100 or any(ord(ch) < 32 for ch in name):
            raise ValueError("Job name is too long or contains control characters.")

        original = self.initial
        if original:
            job_id = str(original["id"])
        else:
            job_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "backup-job"

        if self.android_source:
            source = dict(original["source"])
        else:
            if not self.source_entries:
                raise ValueError("Add at least one source folder.")
            normalized = []
            names = set()
            paths = set()
            for item in self.source_entries:
                alias = item["name"].strip()
                path = Path(item["path"]).expanduser().resolve()
                if not alias or alias in names:
                    raise ValueError("Source names must be non-empty and unique.")
                if not path.is_dir():
                    raise ValueError(f"Source folder does not exist or is not a directory:\n{path}")
                if str(path) in paths:
                    raise ValueError(f"Duplicate source folder:\n{path}")
                names.add(alias)
                paths.add(str(path))
                normalized.append({"name": alias, "path": str(path)})
            source = {"type": "local", "entries": normalized}

        selected_device = self._selected_device()
        if not selected_device:
            raise ValueError("Select a destination drive.")
        _, uuid, mountpoint = selected_device
        relative = _safe_relative_path(self.destination_path.get())

        if mountpoint and source.get("type") == "local":
            destination_root = (Path(mountpoint) / relative).resolve()
            for entry in source["entries"]:
                source_path = Path(entry["path"]).resolve()
                if source_path == destination_root or source_path in destination_root.parents or destination_root in source_path.parents:
                    raise ValueError(
                        "A source folder overlaps the backup destination. Choose a separate destination folder or source."
                    )

        try:
            cpu = int(self.cpu_weight.get())
            io_weight = int(self.io_weight.get())
            nice = int(self.nice.get())
            ionice = int(self.ionice_class.get())
        except ValueError as exc:
            raise ValueError("CPU weight, I/O weight, nice and I/O priority must be integers.") from exc
        if not 1 <= cpu <= 10000 or not 1 <= io_weight <= 10000:
            raise ValueError("CPU and I/O weights must be between 1 and 10000.")
        if not -20 <= nice <= 19:
            raise ValueError("Nice value must be between -20 and 19.")
        if ionice not in (1, 2, 3):
            raise ValueError("I/O priority class must be 1, 2 or 3.")

        config = dict(original)
        config.update({
            "id": job_id,
            "name": name,
            "enabled": bool(self.enabled.get()),
            "source": source,
            "destination": {
                "device": {"type": "storage", "identifier_type": "filesystem_uuid", "uuid": uuid},
                "path": relative,
            },
            "schedule": {
                **dict(original.get("schedule", {})),
                "interval": self.interval.get().strip(),
                "mode": self.mode.get(),
                "skip_reminder": self.skip_reminder.get().strip(),
            },
            "backup": {
                **dict(original.get("backup", {})),
                "integrity": "sha256",
                "verify_after_backup": True,
                "automatic_pruning": False,
            },
            "resources": {
                **dict(original.get("resources", {})),
                "memory_high": self.memory_high.get().strip(),
                "memory_max": self.memory_max.get().strip(),
                "cpu_weight": cpu,
                "io_weight": io_weight,
                "nice": nice,
                "ionice_class": ionice,
                "max_parallel_jobs": 1,
            },
        })
        return job_id, config

    def save(self):
        try:
            job_id, config = self._build_config()
            from .scheduler import parse_interval
            parse_interval(config["schedule"]["interval"])
            parse_interval(config["schedule"]["skip_reminder"], 60)
            if config["schedule"]["mode"] not in ("prompt", "auto"):
                raise ValueError("Backup mode must be prompt or auto.")

            if not self.initial:
                existing_ids = {p.stem for p in _job_files()}
                if job_id in existing_ids:
                    raise ValueError("A job with this ID already exists. Choose a different job name.")

            # Validate with the production loader before handing it to the dashboard.
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            fd, temp_path = tempfile.mkstemp(prefix=".editor-check-", suffix=".yaml", dir=CONFIG_DIR)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    yaml.safe_dump(config, stream, sort_keys=False, allow_unicode=True)
                load_job(temp_path)
            finally:
                Path(temp_path).unlink(missing_ok=True)

            self.result = (job_id, config)
            self.window.destroy()
        except Exception as exc:
            self.error_var.set(str(exc))


class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP)
        self.root.geometry("1180x760")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)
        self.jobs_by_id: dict[str, dict] = {}
        self.files_by_id: dict[str, Path] = {}
        self.state_data: dict = {"jobs": {}}
        self.refresh_after = None
        self._configure_style()
        self._build()
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL, rowheight=30)
        style.configure("Treeview.Heading", background="#1a2b1c", foreground="#a5f3ad", padding=6)
        style.map("Treeview", background=[("selected", "#245b31")], foreground=[("selected", "#ffffff")])
        style.configure("TButton", padding=7)
        style.configure("TLabel", background=BG, foreground=TEXT)

    def _build(self):
        header = tk.Frame(self.root, bg=BG, padx=20, pady=16)
        header.pack(fill="x")
        tk.Label(header, text="UNIVERSAL BACKUP", bg=BG, fg=GREEN, font=("DejaVu Sans", 20, "bold")).pack(anchor="w")
        tk.Label(header, text="Scheduled • Verified • Recoverable", bg=BG, fg=MUTED, font=("DejaVu Sans", 10)).pack(anchor="w", pady=(3, 0))

        status_bar = tk.Frame(self.root, bg=BG, padx=20, pady=6)
        status_bar.pack(fill="x")
        self.scheduler_status = tk.StringVar(value="Checking scheduler…")
        self.status_label = tk.Label(status_bar, textvariable=self.scheduler_status, bg=BG, fg="#f0c66a", font=("DejaVu Sans", 10, "bold"))
        self.status_label.pack(side="left")
        ttk.Button(status_bar, text="Refresh now", command=self.refresh).pack(side="right")
        ttk.Button(status_bar, text="Open jobs folder", command=self.open_jobs).pack(side="right", padx=8)

        device_frame = tk.LabelFrame(self.root, text="Connected devices", bg=BG, fg="#a5f3ad", padx=10, pady=8)
        device_frame.pack(fill="x", padx=20, pady=(8, 10))
        self.devices_text = tk.StringVar(value="Scanning for storage drives and authorised Android devices…")
        tk.Label(device_frame, textvariable=self.devices_text, bg=BG, fg="#c5d5c7", justify="left", anchor="w", wraplength=1080).pack(fill="x")

        jobs_frame = tk.Frame(self.root, bg=BG, padx=20, pady=4)
        jobs_frame.pack(fill="both", expand=True)
        tk.Label(jobs_frame, text="BACKUP JOBS", bg=BG, fg=GREEN, font=("DejaVu Sans", 11, "bold")).pack(anchor="w", pady=(0, 8))
        columns = ("name", "enabled", "mode", "interval", "last", "status")
        self.tree = ttk.Treeview(jobs_frame, columns=columns, show="headings", selectmode="browse")
        definitions = [
            ("name", "Backup job", 220), ("enabled", "Enabled", 70),
            ("mode", "Mode", 85), ("interval", "Frequency", 90),
            ("last", "Last successful backup", 190), ("status", "Status", 150),
        ]
        for col, title, width in definitions:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, minwidth=60, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.show_job_details)
        self.tree.bind("<Double-1>", lambda _event: self.edit_job())

        details = tk.LabelFrame(self.root, text="Selected job details", bg=BG, fg="#a5f3ad", padx=10, pady=7)
        details.pack(fill="x", padx=20, pady=(8, 4))
        self.details_text = tk.StringVar(value="Select a job to see its recent activity and any error details.")
        tk.Label(details, textvariable=self.details_text, bg=BG, fg="#c5d5c7", justify="left", anchor="w", wraplength=1080).pack(fill="x")

        controls = tk.Frame(self.root, bg=BG, padx=20, pady=12)
        controls.pack(fill="x")
        ttk.Button(controls, text="＋ Add job", command=self.add_job).pack(side="left")
        ttk.Button(controls, text="Edit selected", command=self.edit_job).pack(side="left", padx=(7, 0))
        ttk.Button(controls, text="Enable / disable job", command=self.toggle_job).pack(side="left", padx=7)
        ttk.Button(controls, text="Remove selected", command=self.remove_job).pack(side="right")
        ttk.Button(controls, text="Pause scheduler", command=self.stop_scheduler).pack(side="right", padx=7)
        ttk.Button(controls, text="Enable scheduler", command=self.start_scheduler).pack(side="right")

        tk.Label(self.root, text="SHA-256 verification  •  One backup at a time  •  No automatic retention deletion", bg=BG, fg="#718273", pady=8).pack(fill="x")

    def refresh(self):
        if self.refresh_after is not None:
            try:
                self.root.after_cancel(self.refresh_after)
            except tk.TclError:
                pass
            self.refresh_after = None
        selected = self.tree.selection()
        selected_id = selected[0] if selected else None
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.jobs_by_id.clear()
        self.files_by_id.clear()
        self.state_data = _read_state()
        errors = []
        for path in _job_files():
            try:
                job = load_job(path)
                job_id = job["id"]
                if job_id in self.jobs_by_id:
                    errors.append(f"Duplicate job ID: {job_id}")
                    continue
                self.jobs_by_id[job_id] = job
                self.files_by_id[job_id] = path
                record = self.state_data.get("jobs", {}).get(job_id, {})
                last = record.get("last_success") or "Never"
                self.tree.insert("", "end", iid=job_id, values=(
                    job["name"], "Yes" if job["enabled"] else "No",
                    job["schedule"]["mode"], job["schedule"]["interval"],
                    last, _job_status(record),
                ))
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        if selected_id and selected_id in self.jobs_by_id:
            self.tree.selection_set(selected_id)
            self.tree.focus(selected_id)
            self.show_job_details()
        elif not selected_id:
            self.details_text.set("Select a job to see its recent activity and any error details.")

        service = _systemctl("is-active")
        active = service.returncode == 0 and service.stdout.strip() == "active"
        self.scheduler_status.set("● Scheduler running" if active else "○ Scheduler paused")
        self.status_label.configure(fg="#65ed7c" if active else "#f0c66a")
        self._refresh_devices()
        if errors:
            self.details_text.set("Profile warnings: " + " | ".join(errors[:3]))
        self.refresh_after = self.root.after(REFRESH_MS, self.refresh)

    def _refresh_devices(self):
        try:
            devices = DeviceInventory().all()
            if not devices:
                self.devices_text.set("No mounted storage drives or authorised Android devices detected.")
                return
            lines = []
            for device in devices:
                if device.kind == "android":
                    lines.append(f"Android • {device.label} • ADB authorised")
                else:
                    meta = device.metadata or {}
                    flags = []
                    if meta.get("removable"):
                        flags.append("removable")
                    if meta.get("system"):
                        flags.append("system drive — not eligible as destination")
                    location = device.mountpoint or "not mounted"
                    lines.append(f"Storage • {device.label} • {location} • UUID {device.identifier} • {', '.join(flags) or 'fixed drive'}")
            self.devices_text.set("\n".join(lines[:8]))
        except Exception as exc:
            self.devices_text.set(f"Device scan unavailable: {exc}")

    def _selected_id(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP, "Select a backup job first.")
            return None
        return selected[0]

    def show_job_details(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        job_id = selected[0]
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        record = self.state_data.get("jobs", {}).get(job_id, {})
        source_type = job["source"]["type"]
        if source_type == "local":
            source_text = ", ".join(entry["path"] for entry in job["source"]["entries"])
        else:
            source_text = f"Android device {job['source'].get('device_id')} • " + ", ".join(entry["path"] for entry in job["source"]["entries"])
        lines = [f"Source: {source_text}",
                 f"Destination: UUID {job['destination']['device']['uuid']} → {job['destination']['path']}",
                 f"Last attempt: {record.get('last_attempt') or 'Never'}  |  Attempts: {record.get('attempt_count', 0)}",
                 f"Last result: {record.get('last_result') or 'Not run yet'}"]
        if record.get("last_error"):
            lines.append(f"Last error: {record['last_error']}")
        if record.get("running"):
            lines.append("A worker is marked as running. Detailed percentage progress is not available in this release.")
        self.details_text.set("\n".join(lines))

    def open_jobs(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(CONFIG_DIR)])
        except OSError as exc:
            messagebox.showerror(APP, f"Could not open the jobs folder: {exc}")

    def _save_profile(self, job_id: str, config: dict):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        path = self.files_by_id.get(job_id, CONFIG_DIR / f"{job_id}.yaml")
        fd, temporary = tempfile.mkstemp(prefix=f".{job_id}-", suffix=".yaml", dir=CONFIG_DIR)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                yaml.safe_dump(config, stream, sort_keys=False, allow_unicode=True)
                stream.flush()
                os.fsync(stream.fileno())
            load_job(temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except Exception as exc:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            messagebox.showerror(APP, f"The job profile was not saved because validation failed:\n{exc}")
            return False
        service = _systemctl("is-active")
        if service.returncode == 0 and service.stdout.strip() == "active":
            messagebox.showinfo(APP, "Backup job saved. The running scheduler will load this profile automatically. No running backup was interrupted.")
        else:
            messagebox.showinfo(APP, "Backup job saved. No backup has started. Enable the scheduler when you are ready.")
        self.refresh()
        return True

    def _open_editor(self, job_id=None):
        initial = None
        if job_id:
            try:
                raw = yaml.safe_load(self.files_by_id[job_id].read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("Job profile must contain a YAML mapping.")
                initial = raw
            except Exception as exc:
                messagebox.showerror(APP, f"Could not read the selected job profile:\n{exc}")
                return
        devices = DeviceInventory().storage()
        editor = JobEditor(self.root, initial=initial, devices=devices)
        if editor.result is None:
            return
        new_id, config = editor.result
        if not initial:
            existing_ids = {job["id"] for job in self.jobs_by_id.values()}
            if new_id in existing_ids:
                messagebox.showerror(APP, "A job with this ID already exists. Choose a different name.")
                return
        self._save_profile(new_id, config)

    def add_job(self):
        self._open_editor()

    def edit_job(self):
        job_id = self._selected_id()
        if job_id:
            record = self.state_data.get("jobs", {}).get(job_id, {})
            if record.get("running"):
                messagebox.showwarning(APP, "This job is currently marked as running. Wait until it finishes before editing its profile.")
                return
            self._open_editor(job_id)

    def toggle_job(self):
        job_id = self._selected_id()
        if not job_id:
            return
        job = self.jobs_by_id[job_id]
        config = yaml.safe_load(self.files_by_id[job_id].read_text(encoding="utf-8"))
        config["enabled"] = not bool(job["enabled"])
        if self._save_profile(job_id, config):
            messagebox.showinfo(APP, f"Job '{job['name']}' is now {'enabled' if config['enabled'] else 'disabled'}.")

    def start_scheduler(self):
        if not any(job["enabled"] for job in self.jobs_by_id.values()):
            messagebox.showwarning(APP, "Enable at least one backup job before enabling the scheduler.")
            return
        result = _systemctl("enable", "--now")
        if result.returncode:
            messagebox.showerror(APP, result.stderr.strip() or "Could not enable the scheduler. Check the systemd user service installation.")
        self.refresh()

    def stop_scheduler(self):
        result = _systemctl("disable", "--now")
        if result.returncode:
            messagebox.showerror(APP, result.stderr.strip() or "Could not pause the scheduler.")
        self.refresh()

    def remove_job(self):
        job_id = self._selected_id()
        if not job_id:
            return
        record = self.state_data.get("jobs", {}).get(job_id, {})
        if record.get("running"):
            messagebox.showwarning(APP, "This job is marked as running. Wait for it to finish before removing its profile.")
            return
        job = self.jobs_by_id[job_id]
        if not messagebox.askyesno(APP, f"Remove the profile '{job['name']}'?\n\nThis does not delete any backup data or existing backup versions.", parent=self.root):
            return
        self.files_by_id[job_id].unlink(missing_ok=True)
        self.refresh()

    def close(self):
        if self.refresh_after is not None:
            try:
                self.root.after_cancel(self.refresh_after)
            except tk.TclError:
                pass
        self.root.destroy()


def main():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"Cannot open the desktop interface: {exc}", file=sys.stderr)
        return 2
    Dashboard(root)
    root.mainloop()
    return 0
