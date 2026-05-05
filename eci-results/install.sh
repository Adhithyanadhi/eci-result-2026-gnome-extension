#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

OLD_UUID="eci-seat-share@local"
NEW_UUID="eci-seat-share-panel@local"

APP_DIR="$HOME/.local/share/eci-seat-share"
OLD_EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$OLD_UUID"
NEW_EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$NEW_UUID"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/eci-seat-share.service"
JSON_FILE="$HOME/.cache/eci-seat-share.json"

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions disable "$OLD_UUID" >/dev/null 2>&1 || true
  gnome-extensions disable "$NEW_UUID" >/dev/null 2>&1 || true
fi

rm -rf "$OLD_EXT_DIR" "$NEW_EXT_DIR"
mkdir -p "$APP_DIR" "$NEW_EXT_DIR" "$SERVICE_DIR" "$HOME/.cache"

cp "$ROOT/eci_watch.py" "$APP_DIR/eci_watch.py"
cp "$ROOT/run.sh" "$APP_DIR/run.sh"
chmod +x "$APP_DIR/eci_watch.py" "$APP_DIR/run.sh"

cp "$ROOT/gnome-extension/metadata.json" "$NEW_EXT_DIR/metadata.json"
cp "$ROOT/gnome-extension/extension.js" "$NEW_EXT_DIR/extension.js"
cp "$ROOT/gnome-extension/stylesheet.css" "$NEW_EXT_DIR/stylesheet.css"

python3 -m py_compile "$APP_DIR/eci_watch.py"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=ECI Seat Share Watcher

[Service]
Type=simple
ExecStart=/usr/bin/env python3 $APP_DIR/eci_watch.py --json-out %h/.cache/eci-seat-share.json --min-delay 45 --max-delay 59 --daemon --quiet
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now eci-seat-share.service

python3 "$APP_DIR/eci_watch.py" --json-out "$JSON_FILE" --once --quiet || true

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions enable "$NEW_UUID" >/dev/null 2>&1 || true
fi

echo
echo "Installed ECI Seat Share Panel v5."
echo
echo "Winning count comes from:"
echo "  partywisewinresult-*"
echo
echo "Leading count comes from:"
echo "  partywiseleadresult-*"
echo
echo "Top-bar format:"
echo "  won/leading  won/leading  won/leading"
echo
echo "Fixed positions:"
echo "  0 = TVK"
echo "  1 = ADMK"
echo "  2 = DMK"
echo
echo "If GNOME says the extension does not exist, log out and log back in once."
