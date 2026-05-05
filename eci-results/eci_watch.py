#!/usr/bin/env python3
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
from typing import Dict, Iterable, List, Optional, Tuple


# Fixed top-bar position mapping:
# 0th value = TVK
# 1st value = ADMK
# 2nd value = DMK
#
# Display value:
# won/leading
PARTIES = [
    {
        "name": "TVK",
        "lead_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-3679S22.htm",
        "win_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywisewinresult-3679S22.htm",
    },
    {
        "name": "ADMK",
        "lead_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-75S22.htm",
        "win_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywisewinresult-75S22.htm",
    },
    {
        "name": "DMK",
        "lead_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywiseleadresult-582S22.htm",
        "win_url": "https://results.eci.gov.in/ResultAcGenMay2026/partywisewinresult-582S22.htm",
    },
]

DEFAULT_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

BLOCK = "█"


class TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._in_cell = False
        self._in_row = False
        self._cell_chunks: List[str] = []
        self._row: List[str] = []

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
class PartyResult:
    name: str
    lead_url: str
    win_url: str
    seats: int
    won: int
    leading: int
    lead_status_range: str
    win_status_range: str
    ok: bool
    error: Optional[str]
    stale: bool = False
    updated_at: Optional[str] = None


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def parse_records(page_html: str) -> List[Dict[str, str]]:
    parser = TableHTMLParser()
    parser.feed(page_html)

    rows = parser.rows
    header_index = None
    header = None

    for idx, row in enumerate(rows):
        normalized = [normalize_header(cell) for cell in row]
        if (
            any(cell in ("sno", "serialno") for cell in normalized)
            and any("constituency" in cell for cell in normalized)
            and any("status" in cell for cell in normalized)
        ):
            header_index = idx
            header = normalized
            break

    if header_index is None or header is None:
        return []

    def find_col(*needles: str) -> Optional[int]:
        for needle in needles:
            for i, col in enumerate(header):
                if needle in col:
                    return i
        return None

    sno_i = find_col("sno", "serialno") or 0
    constituency_i = find_col("constituency")
    candidate_i = find_col("leadingcandidate", "winningcandidate", "candidate")
    votes_i = find_col("totalvotes", "votes")
    margin_i = find_col("margin")
    status_i = find_col("status")
    if status_i is None:
        status_i = len(header) - 1

    records: List[Dict[str, str]] = []

    for row in rows[header_index + 1:]:
        if len(row) <= max(sno_i, status_i):
            continue

        sno = row[sno_i].strip()
        if not re.fullmatch(r"\d+", sno):
            continue

        def get(i: Optional[int]) -> str:
            if i is None or i >= len(row):
                return ""
            return row[i].strip()

        records.append(
            {
                "sno": get(sno_i),
                "constituency": get(constituency_i),
                "candidate": get(candidate_i),
                "votes": get(votes_i),
                "margin": get(margin_i),
                "status": get(status_i),
            }
        )

    return records


def status_min_max(records: Iterable[Dict[str, str]]) -> str:
    numerators: List[int] = []
    denominators: List[int] = []

    for record in records:
        status = record.get("status", "")
        for numerator, denominator in re.findall(r"(\d+)\s*/\s*(\d+)", status):
            numerators.append(int(numerator))
            denominators.append(int(denominator))

    if not numerators or not denominators:
        return "-"

    return f"{min(numerators)}-{max(numerators)}/{min(denominators)}-{max(denominators)}"


def fetch_url(url: str, timeout: int) -> str:
    headers = dict(DEFAULT_HEADERS)
    headers["referer"] = url
    request = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        status_code = getattr(response, "status", 200)
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(f"HTTP {status_code}")
        return response.read().decode("utf-8", errors="replace")


def fetch_records(url: str, timeout: int, empty_on_404: bool = False) -> Tuple[List[Dict[str, str]], Optional[str]]:
    try:
        page_html = fetch_url(url, timeout=timeout)
        return parse_records(page_html), None
    except urllib.error.HTTPError as exc:
        if empty_on_404 and exc.code == 404:
            return [], None
        return [], simplify_error(exc)
    except Exception as exc:
        return [], simplify_error(exc)


def simplify_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"Network: {getattr(exc, 'reason', exc)}"
    if isinstance(exc, TimeoutError):
        return "Timeout"
    return str(exc).strip() or exc.__class__.__name__


def load_previous(json_path: Optional[Path]) -> Dict[str, Dict[str, object]]:
    if not json_path or not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        parties = data.get("parties", {})
        if isinstance(parties, dict):
            return parties
    except Exception:
        return {}
    return {}


def fetch_party(party: Dict[str, str], timeout: int, previous: Dict[str, Dict[str, object]]) -> PartyResult:
    name = party["name"]
    lead_url = party["lead_url"]
    win_url = party["win_url"]

    lead_records, lead_error = fetch_records(lead_url, timeout=timeout)
    win_records, win_error = fetch_records(win_url, timeout=timeout, empty_on_404=True)

    errors = [error for error in [lead_error, win_error] if error]

    if not errors:
        won = len(win_records)
        leading = len(lead_records)

        return PartyResult(
            name=name,
            lead_url=lead_url,
            win_url=win_url,
            seats=won + leading,
            won=won,
            leading=leading,
            lead_status_range=status_min_max(lead_records),
            win_status_range=status_min_max(win_records),
            ok=True,
            error=None,
            stale=False,
            updated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    previous_party = previous.get(name)
    if isinstance(previous_party, dict) and ("won" in previous_party or "leading" in previous_party):
        won = int(previous_party.get("won", 0) or 0)
        leading = int(previous_party.get("leading", 0) or 0)

        return PartyResult(
            name=name,
            lead_url=lead_url,
            win_url=win_url,
            seats=won + leading,
            won=won,
            leading=leading,
            lead_status_range=str(previous_party.get("lead_status_range", previous_party.get("status_range", "-")) or "-"),
            win_status_range=str(previous_party.get("win_status_range", "-") or "-"),
            ok=False,
            error="; ".join(errors),
            stale=True,
            updated_at=str(previous_party.get("updated_at") or ""),
        )

    return PartyResult(
        name=name,
        lead_url=lead_url,
        win_url=win_url,
        seats=0,
        won=0,
        leading=0,
        lead_status_range="-",
        win_status_range="-",
        ok=False,
        error="; ".join(errors),
        stale=False,
        updated_at=None,
    )


def collect_results(timeout: int, json_path: Optional[Path]) -> List[PartyResult]:
    previous = load_previous(json_path)
    return [fetch_party(party, timeout=timeout, previous=previous) for party in PARTIES]


def compact_win_lead(result: PartyResult) -> str:
    return f"{result.won}/{result.leading}"


def to_json_payload(results: List[PartyResult]) -> Dict[str, object]:
    now = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    has_problem = any((not result.ok or result.stale) for result in results)

    # Fixed position array:
    # index 0 = TVK
    # index 1 = ADMK
    # index 2 = DMK
    topbar_values = [compact_win_lead(result) for result in results]
    topbar_display = "  ".join(topbar_values) + (" *" if has_problem else "")

    return {
        "updated_at": now,
        "has_error": any(not result.ok for result in results),
        "has_stale": any(result.stale for result in results),
        "topbar_values": topbar_values,
        "display": topbar_display,
        "display_semantics": "position 0=TVK, position 1=ADMK, position 2=DMK; each value is won/leading",
        "parties": {
            result.name: {
                "seats": result.seats,
                "won": result.won,
                "leading": result.leading,
                "lead_status_range": result.lead_status_range,
                "win_status_range": result.win_status_range,
                "ok": result.ok,
                "error": result.error,
                "stale": result.stale,
                "updated_at": result.updated_at,
                "lead_url": result.lead_url,
                "win_url": result.win_url,
            }
            for result in results
        },
    }


def write_json(json_path: Path, results: List[PartyResult]) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json_payload(results)
    tmp_path = json_path.with_suffix(json_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(json_path)


def bar(value: int, max_value: int, width: int) -> str:
    if value <= 0 or max_value <= 0:
        return " " * width
    filled = round((value / max_value) * width)
    filled = max(0, min(width, filled))
    return BLOCK * filled + " " * (width - filled)


def format_dashboard(results: List[PartyResult], width: int = 48) -> str:
    max_value = max((result.seats for result in results), default=0)
    lines = [
        "Seat Share Among Tracked Parties",
        "Top bar compact format: won/leading, positions are TVK ADMK DMK",
        "",
    ]

    for result in results:
        suffix = (
            f"won/leading {result.won}/{result.leading}  "
            f"win-status {result.win_status_range}  lead-status {result.lead_status_range}"
        )
        if result.stale and result.error:
            suffix += f"  stale error {result.error}"
        elif result.error:
            suffix += f"  error {result.error}"

        lines.append(f"{result.name:<5} {bar(result.seats, max_value, width)}  {result.seats:>3}  {suffix}")

    return "\n".join(lines)


def clear_screen() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def default_json_path() -> Path:
    return Path(os.path.expanduser("~/.cache/eci-seat-share.json"))


def run_once(args: argparse.Namespace) -> List[PartyResult]:
    json_path = Path(args.json_out).expanduser() if args.json_out else None
    results = collect_results(timeout=args.timeout, json_path=json_path)

    if json_path:
        write_json(json_path, results)

    if not args.quiet and not args.daemon:
        if not args.no_clear:
            clear_screen()
        print(format_dashboard(results, width=args.bar_width), flush=True)

    return results


def next_sleep(min_delay: int, max_delay: int) -> int:
    return random.randint(min_delay, max_delay)


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal ECI watcher for TVK, ADMK, and DMK.")
    parser.add_argument("--interval", type=int, default=60, help="Fallback interval. Use --min-delay/--max-delay for randomized refresh.")
    parser.add_argument("--min-delay", type=int, default=45, help="Minimum randomized refresh delay. Default: 45")
    parser.add_argument("--max-delay", type=int, default=59, help="Maximum randomized refresh delay. Must be < 60. Default: 59")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-clear", action="store_true")
    parser.add_argument("--bar-width", type=int, default=48)
    parser.add_argument("--json-out", default=str(default_json_path()))
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.min_delay < 1:
        raise SystemExit("--min-delay must be >= 1")
    if args.max_delay < args.min_delay:
        raise SystemExit("--max-delay must be >= --min-delay")
    if args.max_delay >= 60:
        raise SystemExit("--max-delay must be less than 60")

    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if args.once:
        run_once(args)
        return 0

    while not stop:
        cycle_start = time.monotonic()

        try:
            run_once(args)
        except Exception as exc:
            if not args.quiet:
                print(f"Watcher error: {simplify_error(exc)}", file=sys.stderr, flush=True)

        target_delay = next_sleep(args.min_delay, args.max_delay)
        elapsed = int(time.monotonic() - cycle_start)
        sleep_for = max(1, target_delay - elapsed)

        for _ in range(sleep_for):
            if stop:
                break
            time.sleep(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
