#!/usr/bin/env bash
set -Eeuo pipefail
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_HOME="$DATA_HOME/universal-backup"
UNIT="$CONFIG_HOME/systemd/user/universal-backup.service"
DESKTOP="$DATA_HOME/applications/universal-backup.desktop"

[[ "${EUID}" -ne 0 ]] || { echo "Do not run with sudo." >&2; exit 1; }
systemctl --user disable --now universal-backup.service 2>/dev/null || true
rm -f "$UNIT" "$DESKTOP"
systemctl --user daemon-reload
rm -rf "$APP_HOME"
echo "Universal Backup application and service removed."
echo "Job profiles and scheduler state were preserved. Backup archives were not touched."
if [[ "${1:-}" == "--purge-config" ]]; then
  echo "This will delete job profiles and scheduler state, but not backup archives."
  read -r -p "Continue? [y/N] " answer
  if [[ "$answer" == "y" || "$answer" == "Y" ]]; then
    rm -rf "$CONFIG_HOME/universal-backup" "${XDG_STATE_HOME:-$HOME/.local/state}/universal-backup"
    echo "Configuration and scheduler state removed."
  fi
fi
