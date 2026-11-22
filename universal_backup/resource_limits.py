"""Resource policy for backup worker processes."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys


DEFAULTS = {
    "memory_high": "1G", "memory_max": "2G",
    "cpu_weight": 20, "io_weight": 20, "nice": 10,
    "ionice_class": 3, "max_parallel_jobs": 1,
}


def normalize_policy(raw=None):
    policy = dict(DEFAULTS)
    if raw:
        if not isinstance(raw, dict):
            raise ValueError("resources must be a mapping")
        policy.update(raw)
    for key in ("memory_high", "memory_max"):
        value = str(policy[key]).upper()
        if not value.endswith(("K", "M", "G", "T")) or not value[:-1].isdigit():
            raise ValueError(f"{key} must be a size such as 512M, 1G or 2G")
        policy[key] = value
    for key in ("cpu_weight", "io_weight"):
        if not isinstance(policy[key], int) or not 1 <= policy[key] <= 10000:
            raise ValueError(f"{key} must be an integer from 1 to 10000")
    if not isinstance(policy["nice"], int) or not -20 <= policy["nice"] <= 19:
        raise ValueError("nice must be an integer from -20 to 19")
    if policy["ionice_class"] not in (1, 2, 3):
        raise ValueError("ionice_class must be 1, 2 or 3")
    if policy["max_parallel_jobs"] != 1:
        raise ValueError("this release supports max_parallel_jobs: 1 only")
    return policy


def build_limited_command(argv, policy=None, systemd_run=True):
    p = normalize_policy(policy)
    prefix = []
    if systemd_run:
        prefix = [
            "systemd-run", "--user", "--scope", "--quiet", "--collect",
            "--property=MemoryHigh=" + p["memory_high"],
            "--property=MemoryMax=" + p["memory_max"],
            "--property=CPUWeight=" + str(p["cpu_weight"]),
            "--property=IOWeight=" + str(p["io_weight"]),
        ]
    if shutil.which("nice"):
        prefix += ["nice", "-n", str(p["nice"])]
    if shutil.which("ionice"):
        prefix += ["ionice", "-c", str(p["ionice_class"])]
    return prefix + list(argv)


def run_limited(argv, policy=None, env=None):
    has_systemd = shutil.which("systemd-run") is not None and bool(os.environ.get("XDG_RUNTIME_DIR"))
    command = build_limited_command(argv, policy, systemd_run=has_systemd)
    if not has_systemd:
        print("[RESOURCE WARNING] user systemd scope unavailable; memory ceiling cannot be enforced.", file=sys.stderr)
    return subprocess.call(command, env=env)
