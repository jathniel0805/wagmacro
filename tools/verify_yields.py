"""Round 3: close the last two gaps — GBP and NZD — and price up a
uniform alternative for all seven.

Run from the Actions tab -> "Verify yield sources" -> Run workflow.
Read-only. Changes nothing. Send the log back.

WHERE ROUNDS 1 AND 2 LEFT US

  Dropped: FRED. Unreachable from a GitHub runner — every request timed
  out. Not a bad series ID; the host does not answer datacenter IPs.

  Confirmed: daily, genuinely 2-year, from the official publisher —
      USD  Treasury par yield curve XML
      EUR  ECB yield curve, SR_2Y (AAA-only)
      JPY  MOF JGB daily CSV, 2年 column
      CAD  Bank of Canada Valet, BD.CDN.2YR.DQ.YLD
      AUD  RBA F2, "Australian Government 2 year bond"

  Open —
      GBP  The IADB endpoint works (the IUDBEDR control returned Bank
           Rate at 3.75), but IUDSNPY/IUDMNPY/IUDLNPY came back 4.93 /
           5.36 / 5.74, which reads as a 5y/10y/20y term structure
           rather than three tries at a 2-year. UNVERIFIED either way,
           so this round opens the BoE yield-curve archive and looks
           for an actual 2-year column.
      NZD  RBNZ returns 403 to the runner on both spreadsheets. That is
           bot protection, not a wrong path, so this round tries other
           publishers entirely.

  And PART C prices up Stooq: one aggregator serving 2-year yields for
  all seven in an identical format. Uniform tenor and convention across
  the board, at the cost of provenance — an aggregator rather than each
  country's own central bank. Worth having the facts before choosing.
"""

from __future__ import annotations

import io
import re
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"}
TIMEOUT = 15
_WS = re.compile(r"\s+")

# ---- PART A: Stooq, 2-year government yield, one format for all seven ----
STOOQ = {
    "USD": "2usy.b", "EUR": "2dey.b", "GBP": "2uky.b", "JPY": "2jpy.b",
    "CAD": "2cay.b", "AUD": "2auy.b", "NZD": "2nzy.b",
}
PART_A = {
    f"STOOQ {cur}  ({sym})": f"https://stooq.com/q/d/l/?s={sym}&i=d"
    for cur, sym in STOOQ.items()
}

# ---- PART B: other routes to a New Zealand 2-year ----
PART_B = {
    "NZD  NZ Debt Management — data page":
        "https://debtmanagement.treasury.govt.nz/investor-resources/data",
    "NZD  RBNZ older statistics path":
        "https://www.rbnz.govt.nz/-/media/ReserveBank/Files/Statistics/"
        "tables/b2/hb2-daily.xlsx",
    "NZD  RBNZ statistics landing (is 403 blanket or path-specific?)":
        "https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-"
        "rates/wholesale-interest-rates",
}

BOE_ZIP = ("https://www.bankofengland.co.uk/-/media/boe/files/statistics/"
           "yield-curves/latest-yield-curve-data.zip")


def probe(item: tuple[str, str]) -> str:
    label, url = item
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
            status, ctype = r.status, r.headers.get("Content-Type", "?")
            raw = r.read(2000)
    except urllib.error.HTTPError as e:
        return f"\n{label}\n  status: {e.code} HTTPError\n"
    except Exception as e:                       # noqa: BLE001 — reporting tool
        return f"\n{label}\n  status: ERR  {type(e).__name__}: {e}\n"

    out = [f"\n{label}", f"  status: {status}   type: {ctype}"]
    if raw[:2] == b"PK":
        out.append("  body  : BINARY zip/xlsx")
        return "\n".join(out) + "\n"

    text = raw.decode("utf-8", errors="replace")
    low = text[:400].lower()
    if "<html" in low or "<!doctype html" in low:
        out.append("  body  : HTML page, not a data feed")
        # still useful: does the page link any .csv/.xlsx we could use?
        links = re.findall(r'href="([^"]+\.(?:csv|xlsx|xls))"', text, re.I)[:5]
        for href in links:
            out.append(f"      link: {href}")
        return "\n".join(out) + "\n"

    out.append("  body  :")
    for line in [l for l in text.splitlines() if l.strip()][:5]:
        out.append("      " + _WS.sub(" ", line)[:140])
    return "\n".join(out) + "\n"


def inspect_boe_zip() -> None:
    """Open the BoE yield-curve archive and find where a 2-year lives."""
    print("\n" + "=" * 70)
    print("PART D — inside the BoE yield-curve archive")
    print("=" * 70)
    try:
        with urllib.request.urlopen(
                urllib.request.Request(BOE_ZIP, headers=UA), timeout=60) as r:
            blob = r.read()
    except Exception as e:                       # noqa: BLE001
        print(f"  download failed: {type(e).__name__}: {e}")
        return

    print(f"  downloaded {len(blob)} bytes")
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        print("  not a readable zip")
        return

    names = zf.namelist()
    print(f"  contains {len(names)} entries:")
    for n in names:
        print(f"      {n}")

    try:
        import openpyxl                          # installed by the workflow
    except ImportError:
        print("\n  openpyxl not available — cannot read sheet contents")
        return

    for name in names:
        if not name.lower().endswith((".xlsx", ".xlsm")):
            continue
        print(f"\n  --- {name} ---")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(zf.read(name)),
                                        read_only=True, data_only=True)
        except Exception as e:                   # noqa: BLE001
            print(f"      unreadable: {type(e).__name__}: {e}")
            continue

        print(f"      sheets: {wb.sheetnames}")
        for sheet in wb.sheetnames:
            if "spot" not in sheet.lower():
                continue                          # spot curve is what we want
            ws = wb[sheet]
            print(f"      [{sheet}] first rows:")
            for i, row in enumerate(ws.iter_rows(max_row=6, max_col=14,
                                                 values_only=True)):
                cells = ", ".join("" if c is None else str(c)[:12] for c in row)
                print(f"        r{i}: {cells[:150]}")
            # the maturity header usually sits in one of the first few rows
            for row in ws.iter_rows(max_row=6, max_col=40, values_only=True):
                for j, c in enumerate(row):
                    if isinstance(c, (int, float)) and abs(c - 2.0) < 1e-9:
                        print(f"        -> found maturity 2.0 at column {j}")
                        break
        wb.close()


if __name__ == "__main__":
    print("=" * 70)
    print("PART A — Stooq 2y, uniform across all seven")
    print("=" * 70)
    with ThreadPoolExecutor(max_workers=7) as pool:
        for block in pool.map(probe, PART_A.items()):
            print(block)

    print("\n" + "=" * 70)
    print("PART B — other routes to a New Zealand 2-year")
    print("=" * 70)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for block in pool.map(probe, PART_B.items()):
            print(block)

    inspect_boe_zip()
    print("\nDone. Send the whole log back.")
