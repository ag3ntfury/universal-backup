# Changelog

## [0.5.1] - 2026-11-22

### Improved
- Installer now copies the application into its managed data directory and installs it non-editably, so the extracted download can be moved or removed after installation.
- Installer checks for an active systemd user session and refreshes the graphical session environment used by notifications and confirmation prompts.
- Desktop dashboard now shows connected storage/ADB devices, job enablement, recent attempt details and error state.
- Added job editing and per-job enable/disable controls.
- Scheduler enable/pause controls now persist across desktop logins using `systemctl enable --now` and `systemctl disable --now`.
- Scheduler reloads job profiles during polling, so desktop changes do not require a service restart.
- Profile writes are validated and atomically replaced.
- Dashboard refresh timer is kept to a single scheduled callback.
- Destination selection uses a proper dropdown instead of requiring users to enter a device number.

### Safety
- Scheduler remains stopped and disabled after installation until the user explicitly enables it.
- Removing a job is blocked while its state reports a running worker.
- Dashboard explicitly reports that detailed percentage progress is not available in this release.


## 0.5.0 — Desktop onboarding and GitHub packaging

- Added optional Tk desktop dashboard and local-folder job wizard.
- Added systemd user service template and one-user installer/uninstaller.
- Added desktop confirmation prompts and success/failure notifications through Zenity and libnotify when available.
- Added Python console entry points and package metadata.
- Added public project documentation, architecture notes and contribution guidelines.
- Existing v0.4 scheduler, locking, recovery and backup engine retained.

## 0.4.0 — Scheduler reliability and recovery

- Schema-2 scheduler state, atomic persistence and schema-1 migration.
- Exclusive daemon and worker locks.
- Running markers, attempt tracking and interrupted-job recovery.
- Daemon reloads state after worker completion and processes one worker at a time.
