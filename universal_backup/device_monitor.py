"""Read-only device monitor with stable-presence debounce."""
from __future__ import annotations

import shutil
import subprocess
import time
from .devices import Device, DeviceInventory


def device_key(device: Device):
    return (device.kind, device.identifier_type, device.identifier)


def snapshot(devices):
    return {device_key(d): d for d in devices}


def diff_devices(previous, current):
    events = []
    for key in sorted(current.keys() - previous.keys()):
        events.append(("connected", current[key]))
    for key in sorted(previous.keys() - current.keys()):
        events.append(("disconnected", previous[key]))
    for key in sorted(current.keys() & previous.keys()):
        if current[key] != previous[key]:
            events.append(("changed", current[key]))
    return events


class DebouncedInventory:
    """Require consecutive matching scans before changing stable inventory."""
    def __init__(self, initial, confirmations=2):
        if confirmations < 1:
            raise ValueError("confirmations must be >= 1")
        self.stable = snapshot(initial)
        self.confirmations = confirmations
        self.candidates = {}

    def update(self, observed):
        observed = snapshot(observed)
        events = []
        keys = self.stable.keys() | observed.keys()
        for key in keys:
            stable_device = self.stable.get(key)
            observed_device = observed.get(key)
            if stable_device is not None and observed_device is not None:
                if stable_device == observed_device:
                    self.candidates.pop(key, None)
                    continue
                candidate = ("changed", observed_device)
            elif observed_device is not None:
                candidate = ("connected", observed_device)
            else:
                candidate = ("disconnected", stable_device)

            previous = self.candidates.get(key)
            count = previous[1] + 1 if previous and previous[0] == candidate else 1
            self.candidates[key] = (candidate, count)
            if count >= self.confirmations:
                event, device = candidate
                events.append((event, device))
                if event == "disconnected":
                    self.stable.pop(key, None)
                else:
                    self.stable[key] = device
                self.candidates.pop(key, None)
        return sorted(events, key=lambda x: (device_key(x[1]), x[0]))


class DeviceMonitor:
    """Read-only monitor. Never mounts, unmounts, formats, or writes devices."""
    def __init__(self, inventory=None, interval=2.0, confirmations=2,
                 popen=subprocess.Popen, clock=time.monotonic):
        if interval < 0.5:
            raise ValueError("interval must be at least 0.5 seconds")
        self.inventory = inventory or DeviceInventory()
        self.interval = interval
        self.confirmations = confirmations
        self.popen = popen
        self.clock = clock
        self._stop = False

    def stop(self):
        self._stop = True

    def _start_udev(self):
        if not shutil.which("udevadm"):
            return None
        try:
            return self.popen(
                ["udevadm", "monitor", "--udev", "--subsystem-match=block", "--property"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1,
            )
        except OSError:
            return None

    def watch(self, callback, emit_initial=True):
        initial = self.inventory.all()
        tracker = DebouncedInventory(initial, self.confirmations)
        if emit_initial:
            for device in tracker.stable.values():
                callback("present", device)
        process = self._start_udev()
        last_scan = self.clock()
        try:
            while not self._stop:
                if process and process.stdout:
                    import selectors
                    selector = selectors.DefaultSelector()
                    try:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        if selector.select(timeout=min(self.interval, 1.0)):
                            line = process.stdout.readline()
                            if line:
                                last_scan = 0.0
                    finally:
                        selector.close()
                else:
                    time.sleep(min(self.interval, 1.0))
                now = self.clock()
                if now - last_scan >= self.interval:
                    events = tracker.update(self.inventory.all())
                    for event, device in events:
                        callback(event, device)
                    last_scan = now
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except Exception:
                    process.kill()


def format_device(device):
    meta = device.metadata or {}
    if device.kind == "android":
        classification = "ADB authorised"
    else:
        classification = "removable" if meta.get("removable") else "fixed/internal"
        if meta.get("system"):
            classification += ", system"
    location = device.mountpoint or "not mounted"
    return f"{device.kind} | {classification} | {device.label} | {device.identifier} | {location}"
