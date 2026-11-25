"""Search Europe PMC and print one line per hit (PMCID, DOI, year, OA flag, title).

Usage: python3 -I scripts/search_epmc.py 'QUERY' [pageSize] [sort, default 'CITED desc'; use 'P_PDATE_D desc' for newest]
Example query: '(berberine) AND (HbA1c) AND (meta-analysis) AND OPEN_ACCESS:y'
"""
import json
import sys
import urllib.parse
import urllib.request

q = sys.argv[1]
n = sys.argv[2] if len(sys.argv) > 2 else "25"
sort = sys.argv[3] if len(sys.argv) > 3 else "CITED desc"
url = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search?format=json&resultType=lite"
    f"&pageSize={n}&sort=" + urllib.parse.quote(sort) + "&query=" + urllib.parse.quote(q)
)
req = urllib.request.Request(url, headers={"User-Agent": "LifeFrom-open-build/1.0"})
with urllib.request.urlopen(req, timeout=60) as r:
    d = json.load(r)
print("hits:", d.get("hitCount"))
for h in d.get("resultList", {}).get("result", []):
    print(
        h.get("pmcid", "-"), "|", h.get("doi", "-"), "|", h.get("pubYear"), "|",
        "OA" if h.get("isOpenAccess") == "Y" else "noOA", "|", h.get("citedByCount"), "cites |",
        h.get("journalTitle"), "|", h.get("title"),
    )
