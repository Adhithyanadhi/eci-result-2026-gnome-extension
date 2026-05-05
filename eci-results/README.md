# ECI Seat Share Desktop v5

This version uses separate ECI pages:

```text
won     -> partywisewinresult-*.htm
leading -> partywiseleadresult-*.htm
```

Top-bar format:

```text
won/leading  won/leading  won/leading
```

Fixed positions:

```text
0 = TVK
1 = ADMK
2 = DMK
```

Example:

```text
5/106  2/58  3/38
```

Refresh is randomized between 45 and 59 seconds by default.

## Install

```bash
unzip -o eci-seat-share-desktop-v5.zip
cd eci-seat-share-desktop-v5
./install.sh
```

## CLI check

```bash
./run.sh
```

## Check JSON

```bash
cat ~/.cache/eci-seat-share.json
```

## Restart only watcher after script edits

```bash
systemctl --user restart eci-seat-share.service
```

## Diagnose

```bash
./diagnose.sh
```
