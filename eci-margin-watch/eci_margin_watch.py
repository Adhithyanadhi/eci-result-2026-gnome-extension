#!/usr/bin/env python3
"""
ECI Margin Watch v2

CLI UI:
TVK | DMK | ADMK

Each party column is sorted by margin ascending, so the weakest / closest
seats appear at the top.

New in v2:
- Tracks constituency ownership between refreshes.
- If a constituency moves from one tracked party to another, the new entry is
  annotated with the old party in brackets:
      31  MANAPPARAI(138) (DMK)

Important:
- The bracket means "previous tracked leading party from the last successful refresh",
  not historical/2021 winner.
- On first run, there is no previous snapshot, so no brackets are shown.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import re
import signal
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional


PARTIES = [
    {
        "name": "TVK",
        "url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-3679S22.htm",
    },
    {
        "name": "DMK",
        "url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-582S22.htm",
    },
    {
        "name": "ADMK",
        "url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-75S22.htm",
    },
]

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}


class TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._in_row = False
        self._in_cell = False
        self._row: List[str] = []
        self._cell_chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_row = True
            self._row = []
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_chunks = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th") and self._in_cell:
            text = " ".join("".join(self._cell_chunks).split())
            self._row.append(html.unescape(text))
            self._cell_chunks = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if any(cell.strip() for cell in self._row):
                self.rows.append(self._row)
            self._row = []
            self._in_row = False


@dataclass
class Seat:
    constituency: str
    candidate: str
    margin: int
    status: str
    old_party: Optional[str] = None


@dataclass
class PartyResult:
    name: str
    seats: List[Seat]
    ok: bool
    error: Optional[str] = None


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def constituency_key(value: str) -> str:
    """
    Stable key for matching a constituency across party pages.

    Keeps constituency number if present, e.g. MANAPPARAI(138).
    Removes whitespace and punctuation differences.
    """
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def find_col(header: List[str], *needles: str) -> Optional[int]:
    for needle in needles:
        for i, col in enumerate(header):
            if needle in col:
                return i
    return None


def parse_margin(value: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", value)
    if not digits:
        return None
    return int(digits)


def parse_records(page_html: str) -> List[Seat]:
    parser = TableHTMLParser()
    parser.feed(page_html)

    rows = parser.rows
    header_index = None
    header = None

    for idx, row in enumerate(rows):
        normalized = [normalize_header(cell) for cell in row]
        has_serial = any(cell in ("sno", "serialno") for cell in normalized)
        has_constituency = any("constituency" in cell for cell in normalized)
        has_margin = any("margin" in cell for cell in normalized)

        if has_serial and has_constituency and has_margin:
            header_index = idx
            header = normalized
            break

    if header_index is None or header is None:
        return []

    sno_i = find_col(header, "sno", "serialno") or 0
    constituency_i = find_col(header, "constituency")
    candidate_i = find_col(header, "leadingcandidate", "winningcandidate", "candidate")
    margin_i = find_col(header, "margin")
    status_i = find_col(header, "status")

    if constituency_i is None or margin_i is None:
        return []

    seats: List[Seat] = []

    for row in rows[header_index + 1 :]:
        if len(row) <= max(sno_i, constituency_i, margin_i):
            continue

        sno = row[sno_i].strip()
        if not re.fullmatch(r"\d+", sno):
            continue

        margin = parse_margin(row[margin_i])
        if margin is None:
            continue

        def get(index: Optional[int]) -> str:
            if index is None or index >= len(row):
                return ""
            return row[index].strip()

        seats.append(
            Seat(
                constituency=get(constituency_i),
                candidate=get(candidate_i),
                margin=margin,
                status=get(status_i),
            )
        )

    seats.sort(key=lambda seat: (seat.margin, seat.constituency))
    return seats


def fetch_url(url: str, timeout: int) -> str:
    headers = dict(DEFAULT_HEADERS)
    headers["referer"] = url

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status_code = getattr(response, "status", 200)
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"HTTP {status_code}")
        return response.read().decode("utf-8", errors="replace")


def simplify_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", exc)
        return f"Network: {reason}"
    if isinstance(exc, TimeoutError):
        return "Timeout"
    return str(exc).strip() or exc.__class__.__name__


def fetch_party(party: Dict[str, str], timeout: int) -> PartyResult:
    try:
        page_html = fetch_url(party["url"], timeout=timeout)
        seats = parse_records(page_html)
        if not seats:
            raise RuntimeError("No rows parsed")
        return PartyResult(name=party["name"], seats=seats, ok=True)
    except Exception as exc:
        return PartyResult(name=party["name"], seats=[], ok=False, error=simplify_error(exc))


def collect_results(timeout: int) -> Dict[str, PartyResult]:
    return {
        party["name"]: fetch_party(party, timeout=timeout)
        for party in PARTIES
    }


def build_owner_map(results: Dict[str, PartyResult]) -> Dict[str, str]:
    owner_by_constituency: Dict[str, str] = {}

    for party in PARTIES:
        party_name = party["name"]
        result = results[party_name]
        if not result.ok:
            continue

        for seat in result.seats:
            key = constituency_key(seat.constituency)
            if key:
                owner_by_constituency[key] = party_name

    return owner_by_constituency


def load_state(path: Optional[Path]) -> Dict[str, str]:
    if path is None or not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        owners = data.get("owner_by_constituency", {})
        if isinstance(owners, dict):
            return {
                str(key): str(value)
                for key, value in owners.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    except Exception:
        return {}

    return {}


def save_state(path: Optional[Path], owner_by_constituency: Dict[str, str]) -> None:
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "owner_by_constituency": owner_by_constituency,
    }

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def merge_owner_state(
    previous_owner: Dict[str, str],
    current_owner: Dict[str, str],
) -> Dict[str, str]:
    """
    Keeps the first known owner permanently.

    First run:
      state is empty, so save current party as baseline.

    Later runs:
      existing constituency owner is never overwritten.
      newly appearing constituency is marked as NA.
    """
    if not previous_owner:
        return dict(current_owner)

    merged = dict(previous_owner)

    for key in current_owner:
        if key not in merged:
            merged[key] = "NA"

    return merged
    
def annotate_changes(results: Dict[str, PartyResult], previous_owner: Dict[str, str]) -> int:
    changed_count = 0

    if not previous_owner:
        return changed_count

    for party in PARTIES:
        current_party = party["name"]
        result = results[current_party]
        if not result.ok:
            continue

        for seat in result.seats:
            key = constituency_key(seat.constituency)
            old_party = previous_owner.get(key)

            if old_party and old_party != current_party:
                seat.old_party = old_party
                changed_count += 1
            elif not old_party:
                seat.old_party = "NA"
                changed_count += 1

    return changed_count

def all_fetches_ok(results: Dict[str, PartyResult]) -> bool:
    return all(results[party["name"]].ok for party in PARTIES)


def truncate(value: str, width: int) -> str:
    value = " ".join(value.split())
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def format_seat_cell(seat: Optional[Seat], width: int) -> str:
    if seat is None:
        return " " * width

    margin_text = f"{seat.margin:,}".rjust(7)

    constituency = seat.constituency
    if seat.old_party:
        constituency = f"{constituency} ({seat.old_party})"

    constituency_width = max(1, width - len(margin_text) - 2)
    return f"{margin_text}  {truncate(constituency, constituency_width):<{constituency_width}}"


def format_error_cell(error: str, width: int) -> str:
    return truncate(f"error {error}", width).ljust(width)


def border(left: str, middle: str, right: str, col_width: int) -> str:
    return left + middle.join(["─" * (col_width + 2)] * len(PARTIES)) + right


def format_table(
    results: Dict[str, PartyResult],
    rows: int,
    col_width: int,
    next_delay: Optional[int],
    changed_count: int,
    state_file: Optional[Path],
) -> str:
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    header = f"Updated: {now}"
    if next_delay is not None:
        header += f" | Next refresh target: {next_delay}s"
    header += f" | Changed seats marked as (old-party): {changed_count}"

    lines = [
        "Weak Seats by Margin Ascending",
        header,
    ]

    if state_file:
        lines.append(f"State: {state_file}")

    lines.extend(
        [
            "",
            border("┌", "┬", "┐", col_width),
            "│" + "│".join(f" {party['name']:<{col_width}} " for party in PARTIES) + "│",
            border("├", "┼", "┤", col_width),
        ]
    )

    for row_index in range(rows):
        cells = []

        for party in PARTIES:
            name = party["name"]
            result = results[name]

            if not result.ok:
                cell = format_error_cell(result.error or "unknown", col_width) if row_index == 0 else " " * col_width
            else:
                seat = result.seats[row_index] if row_index < len(result.seats) else None
                cell = format_seat_cell(seat, col_width)

            cells.append(f" {cell} ")

        lines.append("│" + "│".join(cells) + "│")

    lines.append(border("└", "┴", "┘", col_width))
    lines.append("")
    lines.append("Each column is sorted independently by lowest margin first. Press Ctrl+C to stop.")
    return "\n".join(lines)


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def default_state_file() -> Path:
    return Path(os.path.expanduser("~/.cache/eci-margin-watch-state.json"))


def validate_args(args: argparse.Namespace) -> None:
    if args.min_delay < 1:
        raise SystemExit("--min-delay must be >= 1")
    if args.max_delay < args.min_delay:
        raise SystemExit("--max-delay must be >= --min-delay")
    if args.max_delay >= 60:
        raise SystemExit("--max-delay must be less than 60 to keep refresh under 60 seconds")
    if args.rows < 1:
        raise SystemExit("--rows must be >= 1")
    if args.col_width < 18:
        raise SystemExit("--col-width must be >= 18")


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI table of weak seats by ascending margin for TVK, DMK, and ADMK.")
    parser.add_argument("--rows", type=int, default=20, help="Rows to display per party. Default: 20")
    parser.add_argument("--min-delay", type=int, default=45, help="Minimum refresh target in seconds. Default: 45")
    parser.add_argument("--max-delay", type=int, default=59, help="Maximum refresh target in seconds. Must be < 60. Default: 59")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds. Default: 15")
    parser.add_argument("--col-width", type=int, default=40, help="Width of each party column. Default: 40")
    parser.add_argument("--once", action="store_true", help="Fetch once and exit.")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear terminal between refreshes.")
    parser.add_argument(
        "--state-file",
        default=str(default_state_file()),
        help="State file for remembering previous party per constituency. Default: ~/.cache/eci-margin-watch-state.json",
    )
    parser.add_argument(
        "--no-state-file",
        action="store_true",
        help="Do not use a persistent state file. Changes are tracked only during the current process.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete the state file before starting. Useful when you want a clean baseline.",
    )
    args = parser.parse_args()

    validate_args(args)

    state_file = None if args.no_state_file else Path(args.state_file).expanduser()

    if args.reset_state and state_file and state_file.exists():
        state_file.unlink()

    previous_owner = load_state(state_file)

    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while not stop:
        cycle_start = time.monotonic()
        next_delay = random.randint(args.min_delay, args.max_delay)

        results = collect_results(timeout=args.timeout)
        changed_count = annotate_changes(results, previous_owner)

        if not args.no_clear:
            clear_screen()

        print(
            format_table(
                results=results,
                rows=args.rows,
                col_width=args.col_width,
                next_delay=None if args.once else next_delay,
                changed_count=changed_count,
                state_file=state_file,
            ),
            flush=True,
        )

        if all_fetches_ok(results):
            current_owner = build_owner_map(results)
            previous_owner = merge_owner_state(previous_owner, current_owner)
            save_state(state_file, previous_owner)

        if args.once:
            return 0

        elapsed = time.monotonic() - cycle_start
        sleep_seconds = max(1, next_delay - int(elapsed))

        for _ in range(sleep_seconds):
            if stop:
                break
            time.sleep(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
