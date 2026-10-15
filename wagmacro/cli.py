"""Daily pipeline: fetch -> parse -> score -> store -> render.

Run live:
    python -m wagmacro.cli --out board.html

Run on the bundled sample set (no network, clearly labelled as sample):
    python -m wagmacro.cli --sample --out board.html

The pipeline NEVER raises on a data problem. A source that cannot be
reached produces an UNAVAILABLE component and a loud banner, because a
dashboard that fails silently is worse than one that fails visibly.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .core.config import REQUIRED_HOSTS, SOURCE_URLS
from .core.types import Currency, SourceStamp
from .ingest import calendar as cal
from .ingest import cot as cot_mod
from .ingest import transport
from .ingest import yields as yields_mod
from .model.aggregate import build_board, build_reading
from .model.scorers import score_calendar, score_positioning, score_rates
from .render import html, viewmodel
from .store.repository import BoardRepository


def _blocked_hosts() -> list[str]:
    return [h for h in REQUIRED_HOSTS if not transport.host_reachable(h)]


def run(as_of: date, *, sample: bool) -> tuple[object, bool, str]:
    """Build a board. Returns (board, live, banner)."""
    sources: dict[str, SourceStamp] = {}

    if sample:
        from .sample import SAMPLE
        cot_readings = SAMPLE["cot"]
        events = SAMPLE["events"]
        yield_set = SAMPLE["yields"]
        has_actuals = SAMPLE["has_actuals"]
        for name in ("cot", "calendar", "yields"):
            sources[name] = SourceStamp(
                name=name, url=SOURCE_URLS.get(name, ""), retrieved_at=None,
                data_dated=None, transport="sample", ok=True,
                detail="illustrative sample — not market data",
            )
        banner = ("SAMPLE DATA — these numbers are illustrative and are NOT "
                  "real market readings. Do not trade from this board.")
        return build(as_of, cot_readings, events, yield_set, has_actuals,
                     sources), False, banner

    blocked = _blocked_hosts()

    cot_payload = transport.fetch("cot", SOURCE_URLS["cot"])
    sources["cot"] = cot_payload.stamp
    try:
        cot_readings = cot_mod.parse(cot_payload)
    except cot_mod.CotParseError as exc:
        cot_readings = {}
        sources["cot"] = SourceStamp(
            name="cot", url=SOURCE_URLS["cot"], retrieved_at=None,
            data_dated=None, transport="unavailable", ok=False,
            detail=f"parse failed: {exc}",
        )

    cal_payload = transport.fetch("calendar", SOURCE_URLS["calendar"])
    sources["calendar"] = cal_payload.stamp
    events = cal.in_window(cal.parse(cal_payload), as_of)
    has_actuals = cal.feed_has_actuals(events)

    # Six publishers, one per currency, fetched in parallel. NZD has no
    # reachable publisher and is absent by design — see ingest/yields/.
    yield_set, provider_results = yields_mod.fetch_all(as_of)
    got = [c.value for c, r in sorted(provider_results.items(),
                                      key=lambda kv: kv[0].value) if r.ok]
    missed = [f"{c.value} ({r.detail})"
              for c, r in sorted(provider_results.items(),
                                 key=lambda kv: kv[0].value) if not r.ok]
    sources["yields"] = SourceStamp(
        name="yields", url=SOURCE_URLS["yields"],
        retrieved_at=datetime.now(timezone.utc),
        data_dated=yield_set.as_of if yield_set.points else None,
        transport="http" if got else "unavailable", ok=bool(got),
        detail=("2y from " + ", ".join(got) if got else "no publisher returned "
                "a usable series") + ("; failed: " + "; ".join(missed)
                                      if missed else ""),
    )
    if not yield_set.points:
        yield_set = None

    notices: list[str] = []
    if blocked:
        notices.append(
            "NO LIVE DATA — these hosts are unreachable from this "
            "environment: " + ", ".join(blocked) + ".")
    if yield_set is None:
        notices.append(
            "Rates is scoring 0 for every currency: no yield publisher "
            "returned a usable series, so this board is running on "
            "Positioning and Calendar only.")
    else:
        # NZD has no publisher at all, so it never appears in
        # provider_results; compare against the full currency list.
        absent = [c.value for c in Currency.all() if c not in yield_set.points]
        if absent:
            notices.append(
                "Rates is unavailable for " + ", ".join(absent) +
                ", so those score on two components out of three and "
                "cannot reach the same extremes as the rest. Their totals "
                "are reported as measured, never scaled up.")
    banner = " ".join(notices)

    board = build(as_of, cot_readings, events, yield_set, has_actuals, sources)
    return board, not blocked, banner


def build(as_of, cot_readings, events, yield_set, has_actuals, sources):
    derived_usd = cot_mod.derive_usd(cot_readings) if cot_readings else None

    readings = []
    for currency in Currency.all():
        is_usd = currency is Currency.USD
        components = [
            score_rates(currency, yield_set, as_of),
            score_positioning(
                currency,
                None if is_usd else cot_readings.get(currency),
                as_of,
                derived_net_share=derived_usd if is_usd else None,
            ),
            score_calendar(currency, events, as_of, feed_has_actuals=has_actuals),
        ]
        readings.append(build_reading(currency, components, derived=is_usd))

    return build_board(as_of, readings, sources)


def diagnose() -> int:
    """Fetch every yield publisher and print exactly what came back.

    This exists because six adapters were written against formats that
    had been verified by eye but never parsed in anger. Rather than ship
    them and hope, one run of this prints the series each adapter
    extracted — so a parser reading the wrong column shows up as an
    obviously wrong number, today, instead of as a plausible one that
    quietly skews the heaviest component for months.
    """
    print("=" * 70)
    print("YIELD ADAPTER DIAGNOSTIC — what each publisher actually returned")
    print("=" * 70)

    yield_set, results = yields_mod.fetch_all()

    for currency in Currency.all():
        result = results.get(currency)
        if result is None:
            print(f"\n{currency.value}  — no adapter (see ingest/yields/)")
            continue
        mark = "OK  " if result.ok else "FAIL"
        print(f"\n{currency.value}  [{mark}]  {result.detail}")
        print(f"     {result.url[:100]}")
        if result.series:
            tail = result.series[-5:]
            print("     last observations: "
                  + ", ".join(f"{d} = {v}" for d, v in tail))

    print("\n" + "-" * 70)
    print("ASSEMBLED YIELD SET")
    print("-" * 70)
    if not yield_set.points:
        print("  empty — no publisher produced a usable series")
    for currency in Currency.all():
        point = yield_set.points.get(currency)
        if point is None:
            print(f"  {currency.value}  —  no 2y yield; Rates will score 0")
            continue
        change = point.change_bps
        diff = yield_set.differential(currency)
        print(f"  {currency.value}  {point.yield_pct:6.3f}%  as of {point.as_of}"
              f"   20-obs change: "
              f"{'n/a' if change is None else f'{change:+.1f}bp'}"
              f"   differential: "
              f"{'n/a' if diff is None else f'{diff:+.2f}pp'}")

    if yield_set.notes:
        print("\nNOTES")
        for note in yield_set.notes:
            print(f"  - {note}")

    print("\nSanity check these by eye before trusting the board: a 2-year "
          "yield that looks like a 10-year, or a date that is not recent, "
          "means a parser is reading the wrong column or file.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="wagmacro daily board")
    parser.add_argument("--diagnose", action="store_true",
                        help="fetch every yield publisher and print what "
                             "each adapter extracted, then exit")
    parser.add_argument("--sample", action="store_true",
                        help="run on the bundled illustrative dataset")
    parser.add_argument("--out", type=Path, default=Path("board.html"))
    parser.add_argument("--history-dir", type=Path, default=None,
                        help="where to archive the daily board JSON "
                             "(default: the package's own history/ folder)")
    parser.add_argument("--no-save", action="store_true",
                        help="skip writing to the history store")
    args = parser.parse_args()

    if args.diagnose:
        return diagnose()

    as_of = datetime.now(timezone.utc).date()
    board, live, banner = run(as_of, sample=args.sample)

    if not args.no_save and live:
        # never archive sample data — see sample.py
        BoardRepository(args.history_dir).save(board)

    view = viewmodel.build(board, live=live, banner=banner)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html.render(view), encoding="utf-8")

    print(f"as of {board.as_of}  methodology {board.methodology_version}")
    for r in board.ranked():
        flag = " (derived)" if r.derived else ""
        print(f"  {r.currency.value}  {r.total:+d}  {r.band.value}{flag}")
    if banner:
        print(f"\n{banner}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
