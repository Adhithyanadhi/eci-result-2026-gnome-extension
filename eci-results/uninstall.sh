#!/usr/bin/env bash
set -euo pipefail

OLD_UUID="eci-seat-share@local"
NEW_UUID="eci-seat-share-panel@local"

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$OLD_UUID" >/dev/null 2>&1 || true
  gnome-extensions disable "$NEW_UUID" >/dev/null 2>&1 || true
fi

systemctl --user disable --now eci-seat-share.service >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/eci-seat-share.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true

rm -rf "$HOME/.local/share/eci-seat-share"
rm -rf "$HOME/.local/share/gnome-shell/extensions/$OLD_UUID"
rm -rf "$HOME/.local/share/gnome-shell/extensions/$NEW_UUID"

echo "Uninstalled ECI Seat Share Panel."
