#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="Universal Backup"
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
APP_HOME="$DATA_HOME/universal-backup"
SOURCE_HOME="$APP_HOME/source"
VENV="$APP_HOME/venv"
CONFIG_DIR="$CONFIG_HOME/universal-backup/jobs"
STATE_DIR="$STATE_HOME/universal-backup"
STATE_FILE="$STATE_DIR/state.json"
UNIT_DIR="$CONFIG_HOME/systemd/user"
APP_DIR="$DATA_HOME/applications"

fail() { printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[1;92m[INFO]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[WARN]\033[0m %s\n' "$*"; }

[[ "$EUID" -ne 0 ]] || fail "Do not run this installer with sudo. Run it as your desktop user."
command -v python3 >/dev/null || fail "Python 3 is required. Install python3."
python3 -m venv --help >/dev/null 2>&1 || fail "Python venv support is missing. On Ubuntu run: sudo apt install python3-venv"
command -v systemctl >/dev/null || fail "systemd is required for the background scheduler."
systemctl --user show-environment >/dev/null 2>&1 || fail "No active systemd user session. Log into your Ubuntu desktop and retry."
[[ -f "$REPO_DIR/pyproject.toml" && -f "$REPO_DIR/universal_backup/cli.py" ]] || fail "Run this installer from the extracted Universal Backup project directory."

info "Installing $APP_NAME for user $USER"
mkdir -p "$APP_HOME" "$CONFIG_DIR" "$STATE_DIR" "$UNIT_DIR" "$APP_DIR"

# Keep a self-contained application source copy under the managed app directory.
# User job profiles and scheduler state are deliberately stored elsewhere.
SOURCE_STAGE="$APP_HOME/.source-new"
rm -rf "$SOURCE_STAGE"
mkdir -p "$SOURCE_STAGE"
cp -a "$REPO_DIR/." "$SOURCE_STAGE/"
rm -rf "$SOURCE_HOME"
mv "$SOURCE_STAGE" "$SOURCE_HOME"
rm -rf "$SOURCE_HOME/.git" "$SOURCE_HOME/.venv"
find "$SOURCE_HOME" -type d -name __pycache__ -prune -exec rm -rf {} +

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade "$SOURCE_HOME"

UNIT_TEMPLATE="$SOURCE_HOME/packaging/systemd/universal-backup.service.in"
DESKTOP_TEMPLATE="$SOURCE_HOME/packaging/applications/universal-backup.desktop.in"
[[ -f "$UNIT_TEMPLATE" && -f "$DESKTOP_TEMPLATE" ]] || fail "Packaging templates are missing from the project."

sed -e "s|@VENV@|$VENV|g" -e "s|@CONFIG_DIR@|$CONFIG_DIR|g" -e "s|@STATE_FILE@|$STATE_FILE|g" "$UNIT_TEMPLATE" > "$UNIT_DIR/universal-backup.service"
sed -e "s|@VENV@|$VENV|g" "$DESKTOP_TEMPLATE" > "$APP_DIR/universal-backup.desktop"
chmod 644 "$UNIT_DIR/universal-backup.service" "$APP_DIR/universal-backup.desktop"

systemctl --user daemon-reload
if command -v dbus-update-activation-environment >/dev/null; then
  dbus-update-activation-environment --systemd DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR >/dev/null 2>&1 || true
fi
systemctl --user import-environment DISPLAY WAYLAND_DISPLAY XAUTHORITY DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR >/dev/null 2>&1 || true

info "Installation complete. The scheduler has NOT been enabled or started."
info "Open Universal Backup from your Applications menu. Configure a job, review it, then enable the scheduler."
info "Application: $APP_HOME"
info "Job profiles: $CONFIG_DIR"
info "Scheduler state: $STATE_FILE"
if ! command -v zenity >/dev/null || ! command -v notify-send >/dev/null; then
  warn "For confirmation prompts and notifications install: sudo apt install zenity libnotify-bin"
fi
if ! "$VENV/bin/python" -c 'import tkinter' >/dev/null 2>&1; then
  warn "Tkinter is missing. Install it with: sudo apt install python3-tk"
fi
