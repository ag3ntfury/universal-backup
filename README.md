# Universal Backup

**A local-first, SHA-256-verified backup manager for Linux.**

Universal Backup creates independent backup jobs, watches for configured storage devices and Android phones (ADB), schedules backups, stores versioned snapshots, and verifies stored content. The desktop edition includes a simple job dashboard and optional GNOME desktop prompts/notifications.

> **Project status: Alpha (v0.5.1).** The backup engine and scheduler have automated regression tests, but this is not yet a mature disaster-recovery product. Test with disposable data first. Do not rely on it as your only backup. Full-system imaging, MTP, wireless ADB pairing, cloud destinations, encryption-at-rest, and automatic retention are not supported.

## What works

- Multiple independent YAML backup jobs.
- Multiple local source folders per job.
- Destination selection by filesystem UUID, not a volatile `/dev/sdX` name.
- Android shared-storage source staging through an authorised ADB connection.
- Versioned content-addressed backup storage using SHA-256.
- Post-backup verification and restore without overwriting existing files.
- Prompt or automatic scheduling; one worker at a time.
- Persistent scheduler state, interrupted-job recovery, and exclusive daemon/worker locks.
- Debounced USB/storage and authorised ADB device monitoring.
- Conservative worker CPU, I/O and memory controls when supported by the user's systemd session.
- Optional Tk desktop dashboard, systemd user service, and desktop notifications.

## Requirements

Supported target: Ubuntu 24.04 LTS or newer (and compatible Linux distributions).

- Python 3.10+
- `python3-venv`
- `lsblk`, `findmnt`, and `udevadm` (normally supplied by Ubuntu's `util-linux` and `udev` packages)
- `adb` only for Android phone sources
- `python3-tk` for the desktop dashboard
- `zenity` and `libnotify-bin` for desktop prompts and notifications
- A systemd user session for managed background scheduling and worker resource scopes

On Ubuntu, optional desktop/Android dependencies can be installed with:

```bash
sudo apt update && sudo apt install python3-venv python3-tk zenity libnotify-bin adb
```

## Install (recommended)

Clone the repository and run the installer as your normal desktop user. **Do not use sudo.**

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/universal-backup.git
cd universal-backup
./install.sh
```

The installer copies the application into `~/.local/share/universal-backup/source/`, installs it non-editably into an isolated Python environment, installs a systemd **user** service and adds an Applications-menu launcher. You can move or delete the original extracted download after installation. It does not start the scheduler, create a backup job, mount a drive, or modify existing backup archives.

Open **Universal Backup** from the Applications menu. Select **Add backup job**, choose a source folder and a mounted destination drive, set the backup frequency, and choose automatic or confirmation mode. Then select **Enable scheduler** when ready. Enabling the scheduler also enables it for future desktop logins; **Pause scheduler** stops and disables it.

The desktop dashboard shows mounted storage and authorised ADB devices, job status, last attempt details and errors. You can add, edit, enable, disable and remove job profiles. The running scheduler checks for profile changes on each polling cycle, so edits are picked up without restarting the service or interrupting a backup. Detailed percentage progress and restore controls are not yet available. The job wizard creates local-folder jobs. Advanced Android ADB jobs can be configured with the examples in `config/examples/` and edited in the jobs folder.

## Command-line use

After installation:

```bash
universal-backup devices
universal-backup validate ~/.config/universal-backup/jobs/my-job.yaml
universal-backup tick --config-dir ~/.config/universal-backup/jobs
universal-backup daemon --config-dir ~/.config/universal-backup/jobs
```

The desktop service can also be controlled with:

```bash
systemctl --user status universal-backup.service
systemctl --user enable --now universal-backup.service
systemctl --user disable --now universal-backup.service
journalctl --user -u universal-backup.service -f
```

## Backup job model

Each YAML file is one job. See [`config/examples/documents-backup.yaml`](config/examples/documents-backup.yaml) and [`config/examples/android-phone-backup.yaml`](config/examples/android-phone-backup.yaml). A job specifies:

- a unique `id` and human-readable `name`;
- one or more source entries;
- destination filesystem UUID and a relative folder path on that filesystem;
- interval from 30 minutes to 30 days;
- `prompt` or `auto` scheduling mode;
- mandatory SHA-256 integrity and post-backup verification.

Use `prompt` for confirmation before each due backup. Under the desktop service, Universal Backup uses a Zenity dialog; in a terminal it asks interactively. If no graphical prompt is available, the job is safely declined rather than silently started. `auto` starts when due and when all required sources and the destination are present.

## Safety model and limitations

- Device discovery is read-only. Universal Backup does not format or mount drives.
- A destination is matched by filesystem UUID and system filesystems are rejected.
- Destination paths must be relative and are checked not to escape the mounted filesystem.
- Only one worker runs at a time for a scheduler state file.
- A job is marked successful only after the engine completes; interrupted jobs return to pending.
- Restore refuses to overwrite existing destination files.
- There is no automatic pruning in this release. Backup versions can consume substantial space.
- Android access is limited to storage exposed through ADB shared storage; private app data is not accessible.
- Resource ceilings depend on systemd user-scope support. The fallback lowers CPU/I/O priority but cannot enforce a memory ceiling.
- The current engine is not a full-system image tool and does not guarantee application-consistent snapshots of live databases or virtual machines.
- No encryption-at-rest is provided. Use encrypted storage if the backup contains sensitive information.

## Uninstall

```bash
./uninstall.sh
```

This removes the app environment, launcher and user service, while preserving job profiles and scheduler state. It does not delete backup archives. To additionally remove profiles/state, use `./uninstall.sh --purge-config` and confirm the prompt. Backup archives are never removed by the uninstaller.

## Development and tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
python -m unittest discover -s tests -v
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development guidelines and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for component boundaries.

## Security reports

Please do not publish sensitive security reports as public issues. Until a dedicated security contact is configured, open a private vulnerability report through GitHub's repository security advisory feature when available.

## License

MIT. See [`LICENSE`](LICENSE).
