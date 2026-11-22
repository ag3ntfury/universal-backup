import json
import os
import shutil
import subprocess
from pathlib import Path

from .devices import DeviceInventory, match_destination, match_android_source
from .engine import backup
from .android import stage_adb_sources


def _findmnt_filesystem(path, runner):
    """Return the mount target and filesystem UUID covering *path*."""
    try:
        result = runner(
            [
                "findmnt",
                "--json",
                "--target",
                str(path),
                "--output",
                "TARGET,UUID",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError("cannot verify destination filesystem identity") from exc

    if result.returncode != 0:
        raise RuntimeError("cannot verify destination filesystem identity")

    try:
        filesystems = json.loads(result.stdout).get("filesystems", [])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid destination filesystem information") from exc

    if not isinstance(filesystems, list) or len(filesystems) != 1:
        raise RuntimeError("destination filesystem information is ambiguous")

    filesystem = filesystems[0]
    target = filesystem.get("target")
    uuid = filesystem.get("uuid")
    if not isinstance(target, str) or not target or not isinstance(uuid, str) or not uuid:
        raise RuntimeError("destination filesystem UUID is unavailable")

    try:
        return Path(target).resolve(strict=True), uuid
    except OSError as exc:
        raise RuntimeError("destination mount target is unavailable") from exc


def _verify_expected_mount(mountpoint, expected_uuid, runner):
    """Require the configured UUID to be mounted at the selected mountpoint."""
    try:
        mountpoint = Path(mountpoint).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("configured backup filesystem is not mounted") from exc

    if not mountpoint.is_dir():
        raise RuntimeError("backup mountpoint is not a directory")

    actual_target, actual_uuid = _findmnt_filesystem(mountpoint, runner)
    if actual_target != mountpoint:
        raise RuntimeError("configured backup mountpoint is no longer mounted")
    if actual_uuid.casefold() != str(expected_uuid).casefold():
        raise RuntimeError("backup filesystem UUID does not match the configured destination")

    return mountpoint


def _reject_nested_mounts(mountpoint, root, runner):
    """Refuse mountpoints that intersect the backup path inside its filesystem."""
    try:
        result = runner(
            ["findmnt", "--json", "--list", "--output", "TARGET"],
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError("cannot inspect nested destination mountpoints") from exc

    if result.returncode != 0:
        raise RuntimeError("cannot inspect nested destination mountpoints")

    try:
        filesystems = json.loads(result.stdout).get("filesystems", [])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("invalid mountpoint listing") from exc

    if not isinstance(filesystems, list) or not filesystems:
        raise RuntimeError("mountpoint listing is empty or ambiguous")

    for filesystem in filesystems:
        target = filesystem.get("target") if isinstance(filesystem, dict) else None
        if not isinstance(target, str) or not target:
            raise RuntimeError("mountpoint listing contains an invalid target")
        mounted_path = Path(target).resolve(strict=False)
        # Ignore the selected filesystem mount itself and mounts outside it.
        # Reject mounts below, at, or between the selected mount and backup
        # root. The intermediate case matters when the destination is nested
        # below another mountpoint on the selected filesystem.
        inside_selected_mount = mounted_path != mountpoint and mountpoint in mounted_path.parents
        intersects_backup_path = (
            mounted_path == root
            or mounted_path in root.parents
            or root in mounted_path.parents
        )
        if inside_selected_mount and intersects_backup_path:
            raise RuntimeError(
                f"backup destination path intersects a nested mountpoint: {mounted_path}"
            )


def _destination_root(mountpoint, relative_path, expected_uuid, runner):
    """Validate the destination path and the filesystem containing it."""
    if not isinstance(relative_path, str) or not relative_path:
        raise RuntimeError("destination path must be a non-empty relative path")

    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or str(relative) == ".":
        raise RuntimeError("destination path must stay inside the configured filesystem")

    root = mountpoint / relative
    current = mountpoint
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("destination path contains a symbolic link")

    # For a not-yet-created destination, inspect its nearest existing parent.
    probe = root
    while not probe.exists() and not probe.is_symlink():
        parent = probe.parent
        if parent == probe:
            raise RuntimeError("cannot locate an existing destination parent")
        probe = parent

    if probe.is_symlink() or not probe.is_dir():
        raise RuntimeError("destination parent is not a safe directory")

    try:
        resolved_probe = probe.resolve(strict=True)
        resolved_root = root.resolve(strict=False)
    except OSError as exc:
        raise RuntimeError("cannot resolve backup destination path") from exc

    if resolved_probe != mountpoint and mountpoint not in resolved_probe.parents:
        raise RuntimeError("destination parent escapes the configured filesystem")
    if resolved_root != mountpoint and mountpoint not in resolved_root.parents:
        raise RuntimeError("destination path escapes the configured filesystem")

    _, parent_uuid = _findmnt_filesystem(probe, runner)
    if parent_uuid.casefold() != str(expected_uuid).casefold():
        raise RuntimeError("destination directory is on a different filesystem")

    # A mount below, at, or between the selected mount and backup root can
    # redirect writes, even when it reports the expected UUID (for example, a bind mount).
    _reject_nested_mounts(mountpoint, resolved_root, runner)

    return resolved_root


class JobManager:
    def __init__(self, state, inventory=None, mount_runner=None):
        self.state = state
        self.inventory = inventory if inventory is not None else DeviceInventory()
        self.mount_runner = mount_runner if mount_runner is not None else subprocess.run

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
        mount_fd = None
        stage = None
        try:
            expected_uuid = job["destination"]["device"]["uuid"]

            # Never trust the inventory snapshot captured by evaluate(); devices
            # can be removed or remounted between evaluation and execution.
            destination = match_destination(job, self.inventory.storage())
            if destination is None or not destination.mountpoint:
                raise RuntimeError("configured backup filesystem is not currently available")

            mount = _verify_expected_mount(
                destination.mountpoint, expected_uuid, self.mount_runner
            )

            # Keep the mounted directory open throughout the backup. This makes
            # an ordinary unmount fail while the worker is using the filesystem.
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            mount_fd = os.open(str(mount), flags)
            opened = os.fstat(mount_fd)
            current = os.stat(mount)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise RuntimeError("backup mount changed while it was being opened")

            # Recheck after opening to narrow the removal/remount race window.
            _verify_expected_mount(mount, expected_uuid, self.mount_runner)
            root = _destination_root(
                mount, job["destination"]["path"], expected_uuid, self.mount_runner
            )

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
            if mount_fd is not None:
                os.close(mount_fd)
