"""Move excerpts from sources that are not CC BY / CC0 out of the distributed curation files.

Usage: python3 -I scripts/split_quotes.py

For every row in curation/extract_*.csv and curation/biotin_thresholds.csv whose source licence
(read from the saved full text) is not CC BY or CC0, the `quote` is copied into
curation/withheld/full_quotes.csv (not distributed) and blanked in the curation file.
Run it after adding extraction rows and before scripts/build.py.
"""
from __future__ import annotations

import csv
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import build  # noqa: E402
import fetch_fulltext  # noqa: E402


def licence(pmcid: str) -> str:
    fetch_fulltext.fetch(pmcid)
    src = build.EPMC / (f"{pmcid}.html" if pmcid in fetch_fulltext.HTML_ONLY else f"{pmcid}.xml")
    return build.license_of(src.read_text(encoding="utf-8", errors="replace"))


def main() -> None:
    withheld = build.WITHHELD_QUOTES
    withheld.parent.mkdir(parents=True, exist_ok=True)
    full: dict[str, dict] = {}
    if withheld.exists():
        with withheld.open(newline="", encoding="utf-8") as f:
            full = {r["row_id"]: r for r in csv.DictReader(f)}
    files = sorted((HERE / "curation").glob("extract_*.csv"))
    thr = HERE / "curation" / "biotin_thresholds.csv"
    if thr.exists():
        files.append(thr)
    lic_cache: dict[str, str] = {}
    moved = 0
    for p in files:
        with p.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            hdr = reader.fieldnames
            rows = list(reader)
        changed = False
        for r in rows:
            pmcid = r["pmcid"].strip()
            if pmcid not in lic_cache:
                lic_cache[pmcid] = licence(pmcid)
            lic = lic_cache[pmcid]
            q = r["quote"]
            if q.strip():
                full[r["row_id"]] = {"row_id": r["row_id"], "pmcid": pmcid, "license": lic, "quote": q}
            if q.strip() and not build.quote_licence_ok(lic):
                r["quote"] = ""
                changed = True
                moved += 1
        if changed:
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=hdr)
                w.writeheader()
                w.writerows(rows)
    with withheld.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["row_id", "pmcid", "license", "quote"])
        w.writeheader()
        w.writerows(sorted(full.values(), key=lambda r: r["row_id"]))
    print(f"moved {moved} restricted excerpts; withheld-excerpt file holds {len(full)} excerpts")


if __name__ == "__main__":
    main()
