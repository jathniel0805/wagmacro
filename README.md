# wagmacro

A daily fundamental bias board for seven currencies — USD, EUR, GBP, JPY,
AUD, CAD, NZD — each scored −9 to +9.

The board is rebuilt every weekday by GitHub Actions and published to
GitHub Pages. Nothing has to be running locally for it to update.

## How a score is built

Three components, each scored −3 to +3, summed:

| Component | Input | Why |
|---|---|---|
| **Rates** | 2y government yield differential, plus its 20-day change | The policy-path proxy. Level is the carry; the change is the repricing, and spot responds to repricing. |
| **Positioning** | CFTC leveraged-fund net position as a share of open interest | Where the fast money sits. Normalised by open interest so a growing market doesn't inflate the reading. |
| **Calendar** | Scheduled high/medium-impact releases, surprise vs forecast | What is about to move it. |

USD carries a `DERIVED` flag. The CFTC publishes currency futures quoted
*against* the dollar, so there is no USD contract to read; its positioning
is the open-interest-weighted inverse of the other six. This is shown on
the board rather than hidden.

A component with no data **scores zero and says so**. It does not score
zero and read as a neutral market.

## Layout

```
wagmacro/
  core/      types + every threshold in one config file
  ingest/    transport, cot, calendar, yields — fetch and parse, never score
  model/     scorers + aggregate — pure functions, no I/O
  store/     JSON archive of each day's board
  render/    viewmodel -> html; the view model holds every decision
  tests/     38 tests over the model layer
tools/       one-off investigation scripts
history/     one JSON file per day, committed by the daily workflow
```

The seam that matters: `model/` is pure functions over parsed readings.
Sources, storage and presentation can each be replaced without touching
the scoring logic. That is what makes a subscription version a change of
deployment rather than a rewrite.

## Running it

```bash
# live
python -m wagmacro.cli --out site/index.html --history-dir history

# the bundled illustrative dataset — every number invented, loudly labelled
python -m wagmacro.cli --sample --out site/index.html

# tests
python -m unittest wagmacro.tests.test_model
```

No third-party dependencies. Standard library only.

## Known gaps

These are open, recorded here so nobody mistakes them for bugs.

**1. The 2y yield series are unverified.** `ingest/yields.py` has
`SERIES_VERIFIED = False`, and `from_fred()` refuses to run until someone
confirms each series really is a 2-year government yield. Until then the
Rates component scores 0 across the board and the dashboard says so.
Run the **Verify yield sources** workflow (Actions tab) to find out what
the candidate series actually are.

A wrong series ID would produce a plausible wrong yield differential in
the most heavily weighted component. Scoring nothing is the safer failure.

**2. The calendar feed carries no `actual` values.** It ships forecast and
previous only, so the Calendar component currently measures *expectation
drift*, not surprise. `EventReading.actual` is the hook for a feed that
carries it.

**3. The ±5 STRONG threshold is a starting guess.** Three components that
must all agree strongly to clear ±5 may mean the band almost never fires —
the sample board peaks at +4. `history/` exists so the threshold can be
refitted against real spread after a few weeks. Old boards keep the
methodology version that produced them, so history is never silently
restated.

## Scheduling

`.github/workflows/daily.yml` runs at 22:30 UTC Sunday–Thursday, which is
06:30 Manila Monday–Friday, after the New York close. Change the cron
expression to move it.

Two things to know about GitHub's scheduler: runs can be delayed by
10–20 minutes at busy times, and scheduled workflows in a repository with
no human activity for 60 days get disabled automatically — GitHub emails
you first.
