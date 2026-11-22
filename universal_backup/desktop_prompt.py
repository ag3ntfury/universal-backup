"""Desktop prompt and notification helpers; gracefully degrade on headless systems."""
from __future__ import annotations
import shutil
import subprocess


def notify(title: str, message: str, urgency: str = "normal") -> None:
    command = shutil.which("notify-send")
    if command:
        subprocess.run([command, "--app-name=Universal Backup", f"--urgency={urgency}", title, message], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ask(job_name: str) -> str:
    """Return yes, no, or skip. Headless fallback is safe-deny."""
    zenity = shutil.which("zenity")
    if not zenity:
        notify("Backup waiting for confirmation", f"{job_name}: install zenity or use CLI mode. Job was not started.", "critical")
        return "no"
    result = subprocess.run([
        zenity, "--question", "--title=Universal Backup", "--width=420",
        f"--text=The backup job '{job_name}' is due. Start it now?",
        "--ok-label=Back up", "--cancel-label=Don't back up", "--extra-button=Skip 15 minutes",
    ], text=True, capture_output=True)
    if result.returncode == 0:
        return "yes"
    if result.returncode == 5:
        return "skip"
    return "no"
