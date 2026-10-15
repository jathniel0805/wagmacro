"""Round 2: confirm a daily 2-year government yield source per currency.

Run from the Actions tab -> "Verify yield sources" -> Run workflow.
Read-only. Changes nothing. Paste the output back.

WHAT ROUND 1 ESTABLISHED

  FRED is unreachable from a GitHub Actions runner. Every request to
  fred.stlouisfed.org timed out, which is why that run took 7m39s. It
  is not a bad series ID — the host does not answer datacenter IPs. So
  FRED is dropped entirely and the Rates component is rebuilt against
  the national publishers instead.

  Confirmed working and genuinely 2-year, daily:
      USD  US Treasury par yield curve XML
      JPY  MOF JGB daily CSV          ("2年" column, e.g. 1.939)
      CAD  Bank of Canada Valet JSON  (BD.CDN.2YR.DQ.YLD)
      AUD  RBA F2 CSV                 ("Australian Government 2 year bond")

  Still unresolved — this round's real job:
      EUR  Bundesbank returned 404 (my series key was a guess)
      GBP  Bank of England returned an HTML page, not data
      NZD  RBNZ returned 403 (the real files are .xlsx, not .csv)

This round runs every request in parallel on a 12-second timeout, so it
finishes in under a minute rather than eight.

Each GBP candidate is an Interactive Database series code. IUDBEDR
(Bank Rate) is included as a CONTROL: if the control returns data and
the yield codes do not, the endpoint is fine and the codes are wrong —
which is a different problem from the endpoint being unusable.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

UA = {"User-Agent": "Mozilla/5.0 (compatible; wagmacro-verify/2.0)"}
TIMEOUT = 12
READ_BYTES = 3000
_WS = re.compile(r"\s+")

_START = (date.today() - timedelta(days=60)).isoformat()
_BOE_FROM = (date.today() - timedelta(days=30)).strftime("%d/%b/%Y")
_BOE_TO = date.today().strftime("%d/%b/%Y")


def _iadb(code: str) -> str:
    return ("https://www.bankofengland.co.uk/boeapps/database/"
            f"_iadb-fromshowcolumns.asp?csv.x=yes&SeriesCodes={code}"
            f"&UsingCodes=Y&CSVF=TN&Datefrom={_BOE_FROM}&Dateto={_BOE_TO}")


def _ecb(key: str) -> str:
    return (f"https://data-api.ecb.europa.eu/service/data/YC/{key}"
            f"?startPeriod={_START}&format=csvdata")


CANDIDATES: dict[str, str] = {
    # -- already confirmed; re-run so one output shows the whole picture --
    "USD  Treasury par yield XML  [CONFIRMED]":
        "https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/pages/xml?data=daily_treasury_yield_curve"
        f"&field_tdr_date_value={date.today().year}",
    "JPY  MOF JGB daily CSV  [CONFIRMED]":
        "https://www.mof.go.jp/jgbs/reference/interest_rate/jgbcm.csv",
    "CAD  BoC Valet 2y JSON  [CONFIRMED]":
        "https://www.bankofcanada.ca/valet/observations/"
        "BD.CDN.2YR.DQ.YLD/json?recent=5",
    "AUD  RBA F2 CSV  [CONFIRMED]":
        "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv",

    # -- EUR: ECB Data Portal yield curve, two instrument variants --
    "EUR  ECB YC AAA-only 2y":
        _ecb("B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"),
    "EUR  ECB YC all-govt 2y":
        _ecb("B.U2.EUR.4F.G_N_C.SV_C_YM.SR_2Y"),
    "EUR  Bundesbank /rest/data/ 2y":
        "https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
        "D.I.ZST.ZI.EUR.S1312.B.A604.R02XX.R.A.A._Z._Z.A?format=csv&lang=en",

    # -- GBP: IADB. IUDBEDR is the control, not a yield. --
    "GBP  IADB IUDBEDR  [CONTROL: Bank Rate]": _iadb("IUDBEDR"),
    "GBP  IADB IUDSNPY": _iadb("IUDSNPY"),
    "GBP  IADB IUDMNPY": _iadb("IUDMNPY"),
    "GBP  IADB IUDLNPY": _iadb("IUDLNPY"),
    "GBP  BoE yield curve archive (zip)":
        "https://www.bankofengland.co.uk/-/media/boe/files/statistics/"
        "yield-curves/latest-yield-curve-data.zip",

    # -- NZD: the real RBNZ files are spreadsheets --
    "NZD  RBNZ hb2-daily-close.xlsx":
        "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/"
        "statistics/series/b/b2/hb2-daily-close.xlsx",
    "NZD  RBNZ hb2-monthly-close.xlsx":
        "https://www.rbnz.govt.nz/-/media/project/sites/rbnz/files/"
        "statistics/series/b/b2/hb2-monthly-close.xlsx",
}


def probe(item: tuple[str, str]) -> str:
    label, url = item
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status = r.status
            ctype = r.headers.get("Content-Type", "?")
            clen = r.headers.get("Content-Length", "?")
            raw = r.read(READ_BYTES)
    except urllib.error.HTTPError as e:
        return f"\n{label}\n  status: {e.code} HTTPError\n"
    except Exception as e:                       # noqa: BLE001 — reporting tool
        return f"\n{label}\n  status: ERR  {type(e).__name__}: {e}\n"

    out = [f"\n{label}",
           f"  status: {status}   type: {ctype}   length: {clen}"]

    if raw[:2] == b"PK":
        out.append(f"  body  : BINARY zip/xlsx, first {len(raw)} bytes read — "
                   "parseable with openpyxl")
        return "\n".join(out) + "\n"

    text = raw.decode("utf-8", errors="replace")
    if "<html" in text[:400].lower() or "<!doctype html" in text[:400].lower():
        out.append("  body  : HTML PAGE, not data — unusable as a feed")
        return "\n".join(out) + "\n"

    out.append("  body  :")
    for line in [l for l in text.splitlines() if l.strip()][:6]:
        flat = _WS.sub(" ", line)[:150]
        out.append("      " + flat)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    print("=" * 70)
    print("ROUND 2 — daily 2y government yield sources")
    print(f"ECB startPeriod={_START}   BoE window={_BOE_FROM}..{_BOE_TO}")
    print("=" * 70)

    with ThreadPoolExecutor(max_workers=14) as pool:
        for block in pool.map(probe, CANDIDATES.items()):
            print(block)

    print("\nDone. Paste all of the above back into the conversation.")
