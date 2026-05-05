#!/usr/bin/env bash
set -euo pipefail

UUID="eci-seat-share-panel@local"

echo "GNOME version:"
gnome-shell --version 2>/dev/null || true
echo

echo "Extension:"
gnome-extensions show "$UUID" 2>/dev/null || true
echo

echo "Extension files:"
ls -la "$HOME/.local/share/gnome-shell/extensions/$UUID" 2>/dev/null || true
echo

echo "Metadata:"
cat "$HOME/.local/share/gnome-shell/extensions/$UUID/metadata.json" 2>/dev/null || true
echo

echo "Watcher service:"
systemctl --user --no-pager status eci-seat-share.service || true
echo

echo "Cache:"
cat "$HOME/.cache/eci-seat-share.json" 2>/dev/null || true
echo

echo "Recent GNOME logs:"
journalctl --user -b --no-pager | grep -i "eci-seat-share\|ECI Seat Share\|gjs" | tail -80 || true
echo
