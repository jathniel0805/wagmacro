"""Find out what the candidate yield series ACTUALLY are.

Run this on a GitHub Actions runner (Actions tab -> "Verify yield
sources" -> Run workflow). It reaches hosts that a Claude container
cannot, reports plain facts, and changes nothing.

It answers two questions:

  1. For each FRED series we have written down as a candidate: what is
     its real title, its units, how often does it update, and what are
     its last few values? A series whose dates land on the first of each
     month is monthly, not daily. A series titled "10-Year" is not a 2y
     yield, whatever our dict calls it.

  2. Which official national publishers are reachable, and in what
     format? That is the route to genuine daily 2y yields for the
     non-US currencies, which FRED does not cover well.

Paste the whole output back into the conversation. Nothing gets marked
verified on the strength of a plausible-looking series ID.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

UA = {"User-Agent": "wagmacro-verify/1.0 (research)"}
TIMEOUT = 25

# What we currently have written down, plus the 10-year series the
# IRLTLT01 family is suspected of actually being, so the comparison is
# visible rather than inferred.
FRED_CANDIDATES = {
    "USD 2y (expect: 2-Year Treasury, daily)": "DGS2",
    "USD 10y (control)": "DGS10",
    "EUR  current entry": "IRLTLT01DEM156N",
    "GBP  current entry": "IRLTLT01GBM156N",
    "JPY  current entry": "IRLTLT01JPM156N",
    "CAD  current entry": "IRLTLT01CAM156N",
    "AUD  current entry": "IRLTLT01AUM156N",
    "NZD  current entry": "IRLTLT01NZM156N",
    # Daily euro-area long rate, as a possible better-frequency anchor.
    "EUR  alt daily": "IRLTLT01EZM156N",
}

# Official publishers of 2-year government yields, one per currency.
# We are checking reachability and format only.
NATIONAL_SOURCES = {
    "US  Treasury par yield curve (XML)":
        "https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/pages/xml?data=daily_treasury_yield_curve&"
        "field_tdr_date_value=2026",
    "DE  Bundesbank 2y (CSV)":
        "https://api.statistiken.bundesbank.de/rest/download/BBSIS/"
        "D.I.ZST.ZI.EUR.S1312.B.A604.R02XX.R.A.A._Z._Z.A?format=csv&lang=en",
    "UK  Bank of England yield curve page":
        "https://www.bankofengland.co.uk/statistics/yield-curves",
    "JP  MOF JGB daily yields (CSV)":
        "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",
    "CA  Bank of Canada Valet (JSON)":
        "https://www.bankofcanada.ca/valet/observations/"
        "BD.CDN.2YR.DQ.YLD/json?recent=5",
    "AU  RBA F2 capital market yields (CSV)":
        "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",
    "NZ  RBNZ B2 wholesale rates (CSV)":
        "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/"
        "statistics/series/b/b2/hb2-daily.csv",
}


def get(url: str, limit: int = 4000) -> tuple[int | str, str]:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(limit).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, f"HTTPError {e.code}"
    except Exception as e:                       # noqa: BLE001 - reporting tool
        return "ERR", f"{type(e).__name__}: {e}"


def probe_fred(label: str, series_id: str) -> None:
    print(f"\n{'-' * 68}\n{label}   id={series_id}")

    status, body = get(f"https://fred.stlouisfed.org/series/{series_id}")
    if status == 200:
        m = re.search(r"<title>(.*?)</title>", body, re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else "(no title found)"
        print(f"  title : {title}")
    else:
        print(f"  title : unavailable (status {status})")

    status, body = get(
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}")
    if status != 200:
        print(f"  data  : unavailable (status {status}) {body[:120]}")
        return

    rows = [r for r in body.strip().splitlines() if r.strip()]
    print(f"  header: {rows[0]}")
    data = [r.split(",") for r in rows[1:]]
    dated = [d for d in data if len(d) >= 2 and d[1].strip() not in {"", "."}]
    if not dated:
        print("  data  : no usable observations")
        return
    print(f"  span  : {dated[0][0]} -> {dated[-1][0]}   ({len(dated)} obs)")
    print(f"  last 5: {', '.join(f'{d[0]}={d[1]}' for d in dated[-5:])}")

    days = {d[0].split("-")[2] for d in dated[-12:]}
    print(f"  cadence: {'MONTHLY (all same day-of-month)' if len(days) == 1 else 'daily or business-daily'}")


def probe_source(label: str, url: str) -> None:
    status, body = get(url, limit=600)
    head = re.sub(r"\s+", " ", body[:220]).strip()
    print(f"\n{label}\n  status: {status}\n  head  : {head}")


if __name__ == "__main__":
    print("=" * 68)
    print("PART 1 - what the FRED candidates really are")
    print("=" * 68)
    for label, sid in FRED_CANDIDATES.items():
        probe_fred(label, sid)

    print("\n\n" + "=" * 68)
    print("PART 2 - official national publishers: reachable? what format?")
    print("=" * 68)
    for label, url in NATIONAL_SOURCES.items():
        probe_source(label, url)

    print("\n\nDone. Paste all of the above back into the conversation.")
