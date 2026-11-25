"""Check that every evidence quote in curation CSV files appears verbatim in the saved full text.

Usage: python3 -I scripts/verify_quotes.py curation/extract_A.csv [more.csv]

Each row's `quote` field may hold several quotes separated by " || ".
Rows whose excerpt is withheld for licence reasons take it from curation/withheld/full_quotes.csv.
If that file is absent, those rows (and only those) are skipped with a message; a blank quote from
a CC BY or CC0 source still fails.
Each quote must occur in ../_raw/europepmc/<pmcid>.txt after collapsing whitespace.
Also checks that the DOI in the row equals the DOI printed in the full text (case-insensitive).
Exit code 1 if anything fails.
"""
from __future__ import annotations

import csv
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import build  # noqa: E402
import fetch_fulltext  # noqa: E402

RAW = build.EPMC
WITHHELD = build.WITHHELD_QUOTES


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def withheld_quotes() -> dict[str, str]:
    if not WITHHELD.exists():
        return {}
    with WITHHELD.open(newline="", encoding="utf-8") as f:
        return {r["row_id"]: r["quote"] for r in csv.DictReader(f)}


def licence_ok(pmcid: str) -> bool:
    src = RAW / (f"{pmcid}.html" if pmcid in fetch_fulltext.HTML_ONLY else f"{pmcid}.xml")
    if not src.exists():
        return True  # unknown licence: treat as shippable, so a blank quote fails
    return build.quote_licence_ok(build.license_of(src.read_text(encoding="utf-8", errors="replace")))


def check_file(path: pathlib.Path) -> int:
    bad = skipped = 0
    cache: dict[str, str] = {}
    full = withheld_quotes()
    with path.open(newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):
            pmcid = (row.get("pmcid") or "").strip()
            rid = row.get("row_id") or f"line {i}"
            if not pmcid:
                print(f"FAIL {path.name}:{rid}: no pmcid")
                bad += 1
                continue
            if pmcid not in cache:
                tp = RAW / f"{pmcid}.txt"
                if not tp.exists():
                    print(f"FAIL {path.name}:{rid}: missing {tp}")
                    bad += 1
                    cache[pmcid] = ""
                    continue
                cache[pmcid] = norm(tp.read_text(encoding="utf-8"))
            text = cache[pmcid]
            if not text:
                bad += 1
                continue
            m = re.search(r"^DOI: (\S+)", (RAW / f"{pmcid}.txt").read_text(encoding="utf-8"), re.M)
            doi = (row.get("doi") or "").strip().lower()
            if not m or m.group(1).lower() != doi:
                print(f"FAIL {path.name}:{rid}: doi {doi!r} != full text {m.group(1) if m else None!r}")
                bad += 1
            quote = (row.get("quote") or "") or full.get(row.get("row_id") or "", "")
            quotes = [q for q in quote.split(" || ") if q.strip()]
            if not quotes:
                if not WITHHELD.exists() and not licence_ok(pmcid):
                    skipped += 1
                    continue
                print(f"FAIL {path.name}:{rid}: empty quote")
                bad += 1
            for q in quotes:
                if norm(q) not in text:
                    print(f"FAIL {path.name}:{rid}: quote not found: {q[:120]!r}")
                    bad += 1
    if skipped:
        print(f"{path.name}: skipped {skipped} rows whose excerpt is withheld for licence reasons "
              f"({WITHHELD.relative_to(HERE)} not present)")
    return bad


if __name__ == "__main__":
    total = 0
    for a in sys.argv[1:]:
        n = check_file(pathlib.Path(a))
        print(f"{a}: {'OK' if n == 0 else str(n) + ' failures'}")
        total += n
    sys.exit(1 if total else 0)
