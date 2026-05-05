# ECI Margin Watch v2

Minimal CLI dashboard for weak seats by margin.

Columns:

```text
TVK | DMK | ADMK
```

Each party column is sorted independently by **margin ascending**.

## New in v2

When a constituency moves from one tracked party to another between refreshes,
the new entry is marked with the old party:

```text
31  MANAPPARAI(138) (DMK)
71  BHAVANISAGAR(107) (TVK)
```

This means:

```text
MANAPPARAI was previously under DMK in the previous tracked snapshot.
Now it is under this column's party.
```

Important: `(DMK)` means previous tracked leading party from the previous snapshot,
not historical/2021 winner.

On first run, there is no previous snapshot, so no brackets are shown.

## Run

```bash
unzip eci-margin-watch-v2.zip
cd eci-margin-watch-v2
./run.sh
```

Direct command:

```bash
python3 eci_margin_watch.py
```

## Reset tracking baseline

Use this when you want to clear the old snapshot and start fresh:

```bash
python3 eci_margin_watch.py --reset-state
```

State file:

```text
~/.cache/eci-margin-watch-state.json
```

## Options

Fetch once:

```bash
python3 eci_margin_watch.py --once
```

Show only top 10 weak seats per party:

```bash
python3 eci_margin_watch.py --rows 10
```

Random refresh target between 30 and 59 seconds:

```bash
python3 eci_margin_watch.py --min-delay 30 --max-delay 59
```

Do not clear screen:

```bash
python3 eci_margin_watch.py --no-clear
```

Disable persistent state file:

```bash
python3 eci_margin_watch.py --no-state-file
```

## Refresh behavior

The default target delay is random between:

```text
45 to 59 seconds
```

So the API is not called exactly every 60 seconds.
