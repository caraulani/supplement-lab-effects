"""Build every output of the supplement-lab-effects release from the curated extractions.

Usage (from the repository folder):
    python3 -I scripts/build.py            # uses cached raw files, fetches anything missing
    python3 -I scripts/build.py --refetch  # re-downloads full texts and Crossref records

Inputs (raw downloads live in a sibling folder, ../_raw/, outside the repository)
    curation/extract_*.csv, curation/biotin_thresholds.csv   extractions, one row per estimate
    curation/withheld/full_quotes.csv   excerpts from sources that are not CC BY or CC0 (not
                                        distributed; optional, see WITHHELD_QUOTES below)
    ../_raw/europepmc/<PMCID>.xml/.txt  open-access full texts (Europe PMC)
    ../_raw/crossref/<doi>.json         Crossref metadata
    ../_raw/lifefrom-release-1/markers.csv   LifeFrom marker list (marker_slug join)

Outputs
    data/effects.csv, data/sources.csv, data/biotin_interference_thresholds.csv,
    web/supplement-effects.json, SHA256SUMS

The build stops with an error if any quote is missing from its full text, any DOI fails
Crossref or does not match the article, any marker_slug is unknown, or a row breaks a
field rule. Standard library only.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent.parent
OPEN = HERE.parent
RAW = OPEN / "_raw"
EPMC = RAW / "europepmc"
CROSSREF = RAW / "crossref"
MARKERS = RAW / "lifefrom-release-1" / "markers.csv"
ACCESS_DATE = "2026-11-25"
VERSION = "1.0.0"
UA = "LifeFrom-open-build/1.0 (dataset build script)"

sys.path.insert(0, str(HERE / "scripts"))
import fetch_fulltext  # noqa: E402

EFFECT_KINDS = {"physiological", "assay_interference"}
# Full excerpts for rows whose source licence does not allow redistribution (anything other
# than CC BY or CC0). This file is not distributed. When it is absent, those rows are checked for
# DOI, licence, CI order, marker join and required fields, but not against an excerpt.
WITHHELD_QUOTES = HERE / "curation" / "withheld" / "full_quotes.csv"


def quote_licence_ok(lic: str) -> bool:
    """Excerpts ship only for CC BY (any version, not NC/ND/SA variants) and CC0 sources."""
    return bool(re.fullmatch(r"CC BY( [0-9.]+| \(version not stated\))?|CC0 1\.0", lic))
CURATED_COLS = [
    "row_id", "supplement", "form", "marker_slug", "biomarker", "effect_kind",
    "dose_text", "dose_min", "dose_max", "dose_unit",
    "duration_text", "duration_min_weeks", "duration_max_weeks",
    "population", "baseline_status", "comparator", "measure",
    "effect", "ci_lo", "ci_hi", "unit", "k_trials", "n", "i2",
    "slope", "slope_unit", "certainty", "study_design",
    "pmcid", "doi", "source_label", "location", "quote", "notes",
]
THRESH_FILE = HERE / "curation" / "biotin_thresholds.csv"
THRESH_COLS = [
    "row_id", "analyte", "marker_slug", "assay", "platform", "manufacturer", "assay_format",
    "threshold_value", "threshold_unit", "threshold_basis", "bias_at_threshold_pct", "direction",
    "tested_concentrations", "sample_type", "study_design", "pmcid", "doi", "source_label",
    "location", "quote", "notes",
]
NUMERIC = ["dose_min", "dose_max", "duration_min_weeks", "duration_max_weeks",
           "effect", "ci_lo", "ci_hi", "k_trials", "n", "i2", "slope"]

# Pair labels for rows without a LifeFrom marker_slug: maps the row's biomarker text
# (lowercased) to one pair label so related rows group together.
UNSLUGGED_PAIR = [
    (r"omega-3 index|rbc epa\s*\+\s*dha|red blood cell epa", "Omega-3 Index (RBC EPA+DHA, %)"),
    (r"dp-?ucmgp|desphospho", "dp-ucMGP"),
    (r"undercarboxylated osteocalcin|ucoc", "Undercarboxylated osteocalcin"),
    (r"coenzyme q10|coq10|ubiquinone", "Plasma CoQ10"),
]


def die(msg: str) -> None:
    print("BUILD ERROR:", msg, file=sys.stderr)
    sys.exit(1)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def norm_title(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def num(v: str):
    v = (v or "").strip().replace("−", "-")
    if v == "":
        return None
    try:
        float(v)
    except ValueError:
        die(f"not a number: {v!r}")
    return v  # keep the number exactly as printed (trailing zeros matter)


def fl(v):
    """Number for checks and JSON: int when written without a decimal point."""
    if v is None:
        return None
    return int(v) if re.fullmatch(r"-?\d+", v) else float(v)


def load_curation() -> list[dict]:
    rows: list[dict] = []
    files = sorted((HERE / "curation").glob("extract_*.csv"))
    if not files:
        die("no curation/extract_*.csv files")
    for p in files:
        with p.open(newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            missing = [c for c in CURATED_COLS if c not in (r.fieldnames or [])]
            if missing:
                die(f"{p.name}: missing columns {missing}")
            for row in r:
                if not any((v or "").strip() for v in row.values()):
                    continue
                rows.append({k: (row.get(k) or "").strip() for k in CURATED_COLS})
    full: dict[str, str] = {}
    if WITHHELD_QUOTES.exists():
        with WITHHELD_QUOTES.open(newline="", encoding="utf-8") as f:
            full = {q["row_id"]: q["quote"] for q in csv.DictReader(f)}
    for r in rows:
        r["quote_public"] = r["quote"]
        r["quote"] = full.get(r["row_id"]) or r["quote"]
    ids = [r["row_id"] for r in rows]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        die(f"duplicate row_id {sorted(dup)}")
    return rows


def license_of(xml: str) -> str:
    if xml.lstrip().lower().startswith("<!doctype html") or "<html" in xml[:500].lower():
        m = re.search(r"creativecommons\.org/licenses/([a-z\-]+)/([0-9.]+)", xml)
        if m:
            return f"CC {m.group(1).upper()} {m.group(2)}"
        return "no open licence stated; free to read at PubMed Central (publisher copyright)"
    perm = re.search(r"<permissions>(.*?)</permissions>", xml, re.S)
    block = perm.group(1) if perm else xml[:20000]
    m = re.search(r"creativecommons\.org/(licenses|publicdomain)/([a-z\-]+)/([0-9.]+)?", block)
    if m:
        kind, code, ver = m.groups()
        if kind == "publicdomain":
            return "CC0 1.0" if code == "zero" else "public domain"
        return f"CC {code.upper()} {ver or ''}".strip()
    txt = norm_ws(re.sub(r"<[^>]+>", " ", block))
    low = txt.lower()
    if "creative commons attribution noncommercial" in low or "attribution-noncommercial" in low:
        return "CC BY-NC (version not stated)"
    if "creative commons attribution" in low:
        return "CC BY (version not stated)"
    if "nutrition.org" in low and "free access" in low:
        return "free access under the American Society for Nutrition licence terms (not CC)"
    return ("other: " + txt[:160]) if txt else "not stated in XML"


def crossref(doi: str, refetch: bool) -> dict:
    CROSSREF.mkdir(parents=True, exist_ok=True)
    p = CROSSREF / (urllib.parse.quote(doi.lower(), safe="") + ".json")
    if refetch or not p.exists():
        url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                p.write_bytes(r.read())
        except Exception as e:  # noqa: BLE001
            die(f"Crossref failed for {doi}: {e}")
        time.sleep(0.2)
    return json.loads(p.read_text(encoding="utf-8"))["message"]


def measure_group(measure: str, comparator: str) -> str:
    """Coarse class of the estimate, for filtering. Order of checks matters."""
    m, c = measure.lower(), comparator.lower()
    if "slope" in m:
        return "dose_response_slope"
    if "dose-response model" in m:
        return "dose_response_point"
    if "day 7 on biotin" in m or "withdrawal" in m:
        return "within_person_on_vs_off"
    if "single arm" in m or "from baseline" in m or "baseline (pre vs post)" in c:
        return "within_arm_change"
    if m.startswith("smd"):
        return "standardised_mean_difference"
    if m.startswith(("md", "wmd")):
        return "mean_difference_vs_control"
    if "percent" in m:
        return "percent_difference_vs_control"
    if "difference" in m and ("placebo" in c or "control" in c):
        return "mean_difference_vs_control"
    if "odds ratio" in m or "risk ratio" in m:
        return "ratio_vs_control"
    return "other"


def title_overlap(a: str, b: str) -> float:
    ta, tb = set(norm_title(a).split()), set(norm_title(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def check_source_row(r: dict, texts: dict, xmls: dict, refetch: bool, public: bool,
                     number_fields: tuple) -> None:
    """Shared checks: full text present, DOI matches, licence gate, excerpt and numbers in text."""
    rid, pmcid = r["row_id"], r["pmcid"]
    if not re.fullmatch(r"PMC\d+", pmcid):
        die(f"{rid}: bad pmcid {pmcid!r}")
    if pmcid not in texts:
        fetch_fulltext.fetch(pmcid, force=refetch)
        texts[pmcid] = (EPMC / f"{pmcid}.txt").read_text(encoding="utf-8")
        src = EPMC / (f"{pmcid}.html" if pmcid in fetch_fulltext.HTML_ONLY else f"{pmcid}.xml")
        xmls[pmcid] = src.read_text(encoding="utf-8", errors="replace")
    raw = texts[pmcid]
    m = re.search(r"^DOI: (\S+)", raw, re.M)
    if not m or m.group(1).lower() != r["doi"].lower():
        die(f"{rid}: DOI {r['doi']} does not match full text {m.group(1) if m else None}")
    r["doi"] = r["doi"].lower()
    r["license"] = license_of(xmls[pmcid])
    r["quote_ok"] = quote_licence_ok(r["license"])
    if not r["quote_ok"] and r["quote_public"]:
        die(f"{rid}: curation file carries an excerpt from a {r['license']} source; "
            "run scripts/split_quotes.py")
    quotes = [q for q in r["quote"].split(" || ") if q.strip()]
    if not quotes:
        if public and not r["quote_ok"]:
            r["unchecked"] = True
            return
        die(f"{rid}: no quote")
    flat = norm_ws(raw)
    for q in quotes:
        if norm_ws(q) not in flat:
            die(f"{rid}: quote not in full text: {q[:100]!r}")
    qn = norm_ws(r["quote"]).replace("\u00b7", ".")
    for c in number_fields:
        v = r[c].replace("\u2212", "-").lstrip("-") if r[c] else ""
        if not v:
            continue
        forms = {v} | ({v[1:]} if v.startswith("0.") else set())
        if not any(re.search(r"(?<![\d.])" + re.escape(x) + r"(?![\d])", qn) for x in forms):
            die(f"{rid}: {c}={r[c]} not found in its evidence quote")


def load_thresholds() -> list[dict]:
    if not THRESH_FILE.exists():
        return []
    full: dict[str, str] = {}
    if WITHHELD_QUOTES.exists():
        with WITHHELD_QUOTES.open(newline="", encoding="utf-8") as f:
            full = {q["row_id"]: q["quote"] for q in csv.DictReader(f)}
    out = []
    with THRESH_FILE.open(newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        missing = [c for c in THRESH_COLS if c not in (rd.fieldnames or [])]
        if missing:
            die(f"{THRESH_FILE.name}: missing columns {missing}")
        for row in rd:
            if not any((v or "").strip() for v in row.values()):
                continue
            r = {k: (row.get(k) or "").strip() for k in THRESH_COLS}
            r["quote_public"] = r["quote"]
            r["quote"] = full.get(r["row_id"]) or r["quote"]
            out.append(r)
    return out


def main() -> None:
    refetch = "--refetch" in sys.argv
    # Without curation/withheld/full_quotes.csv (the public repository does not include it), rows
    # whose excerpt is withheld for licence reasons are not quote-checked. Every other check runs.
    public = "--public-rebuild" in sys.argv or not WITHHELD_QUOTES.exists()
    if public:
        print(f"note: {WITHHELD_QUOTES.relative_to(HERE)} not present; rows whose excerpt is "
              "withheld for licence reasons are not checked against an excerpt (all other checks run)")
    rows = load_curation()

    markers = {}
    with MARKERS.open(newline="", encoding="utf-8") as f:
        for m in csv.DictReader(f):
            markers[m["marker_slug"]] = m

    # ---- full texts, quotes, field rules
    texts: dict[str, str] = {}
    xmls: dict[str, str] = {}
    for r in rows:
        rid = r["row_id"]
        pmcid = r["pmcid"]
        if not re.fullmatch(r"PMC\d+", pmcid):
            die(f"{rid}: bad pmcid {pmcid!r}")
        if pmcid not in texts:
            tp = EPMC / f"{pmcid}.txt"
            fetch_fulltext.fetch(pmcid, force=refetch)  # downloads if missing, re-renders .txt
            raw = tp.read_text(encoding="utf-8")
            texts[pmcid] = raw
            src = EPMC / (f"{pmcid}.html" if pmcid in fetch_fulltext.HTML_ONLY else f"{pmcid}.xml")
            xmls[pmcid] = src.read_text(encoding="utf-8", errors="replace")
        raw = texts[pmcid]
        m = re.search(r"^DOI: (\S+)", raw, re.M)
        if not m or m.group(1).lower() != r["doi"].lower():
            die(f"{rid}: DOI {r['doi']} does not match full text {m.group(1) if m else None}")
        r["doi"] = r["doi"].lower()
        flat = norm_ws(raw)
        r["license"] = license_of(xmls[pmcid])
        r["quote_ok"] = quote_licence_ok(r["license"])
        if not r["quote_ok"] and r["quote_public"]:
            die(f"{rid}: curation file carries an excerpt from a {r['license']} source; "
                "run scripts/split_quotes.py")
        quotes = [q for q in r["quote"].split(" || ") if q.strip()]
        if not quotes:
            if public and not r["quote_ok"]:
                r["unchecked"] = True
            else:
                die(f"{rid}: no quote (excerpts withheld for licence reasons live in {WITHHELD_QUOTES})")
        for q in quotes:
            if norm_ws(q) not in flat:
                die(f"{rid}: quote not in full text: {q[:100]!r}")
        qn = norm_ws(r["quote"]).replace("\u00b7", ".")
        for c in (() if r.get("unchecked") else ("effect", "ci_lo", "ci_hi", "i2", "slope")):
            v = r[c].replace("\u2212", "-").lstrip("-") if r[c] else ""
            if not v:
                continue
            forms = {v} | ({v[1:]} if v.startswith("0.") else set())
            if not any(re.search(r"(?<![\d.])" + re.escape(x) + r"(?![\d])", qn) for x in forms):
                die(f"{rid}: {c}={r[c]} not found in its evidence quote")
        if r["effect_kind"] not in EFFECT_KINDS:
            die(f"{rid}: effect_kind {r['effect_kind']!r}")
        if r["marker_slug"] and r["marker_slug"] not in markers:
            die(f"{rid}: unknown marker_slug {r['marker_slug']!r}")
        for c in NUMERIC:
            r[c] = num(r[c])
        if r["effect"] is None and r["slope"] is None:
            die(f"{rid}: neither effect nor slope")
        lo, hi, e = fl(r["ci_lo"]), fl(r["ci_hi"]), fl(r["effect"])
        if (lo is None) != (hi is None):
            die(f"{rid}: half a CI")
        if lo is not None and e is not None and not (lo <= e <= hi):
            die(f"{rid}: effect {e} outside CI [{lo}, {hi}]")
        if r["i2"] is not None and not (0 <= fl(r["i2"]) <= 100):
            die(f"{rid}: I2 {r['i2']}")
        for need in ("supplement", "biomarker", "measure", "unit", "population", "study_design",
                     "source_label", "location"):
            if not r[need]:
                die(f"{rid}: empty {need}")
        if r["effect"] is not None and not r["unit"]:
            die(f"{rid}: effect without unit")

    # ---- biotin interference thresholds (separate table)
    thresholds = load_thresholds()
    for t in thresholds:
        check_source_row(t, texts, xmls, refetch, public, ("threshold_value",))
        if not t["row_id"].startswith("T"):
            die(f"{t['row_id']}: threshold rows use prefix T")
        if t["marker_slug"] and t["marker_slug"] not in markers:
            die(f"{t['row_id']}: unknown marker_slug {t['marker_slug']!r}")
        if t["threshold_value"]:
            num(t["threshold_value"])
            if not t["threshold_unit"] or not t["threshold_basis"]:
                die(f"{t['row_id']}: threshold without unit or basis")
        elif not t["tested_concentrations"]:
            die(f"{t['row_id']}: no threshold and no tested concentrations")
        for need in ("analyte", "platform", "study_design", "source_label", "location"):
            if not t[need]:
                die(f"{t['row_id']}: empty {need}")
    tids = [t["row_id"] for t in thresholds]
    if len(tids) != len(set(tids)):
        die("duplicate threshold row_id")

    # ---- sources
    sources: dict[str, dict] = {}
    for r in rows + thresholds:
        is_t = r["row_id"].startswith("T") and "threshold_value" in r
        if r["doi"] in sources:
            sources[r["doi"]]["n_threshold_rows" if is_t else "n_rows"] += 1
            continue
        cr = crossref(r["doi"], refetch)
        cr_title = " ".join(cr.get("title") or [""])
        ft_title = re.search(r"^TITLE: (.*)$", texts[r["pmcid"]], re.M)
        ft_title = ft_title.group(1) if ft_title else ""
        ov = title_overlap(cr_title, ft_title)
        if cr.get("DOI", "").lower() != r["doi"] or ov < 0.6:
            die(f"{r['doi']}: Crossref title {cr_title!r} vs full text {ft_title!r} (overlap {ov:.2f})")
        authors = cr.get("author") or []
        first = authors[0].get("family", "") if authors else ""
        issued = (cr.get("issued") or {}).get("date-parts") or [[None]]
        year = issued[0][0] if issued and issued[0] else None
        sources[r["doi"]] = {
            "source_id": "",
            "doi": r["doi"],
            "pmcid": r["pmcid"],
            "title": html.unescape(norm_ws(re.sub(r"<[^>]+>", "", cr_title))),
            "first_author": first,
            "year": year,
            "journal": html.unescape(" ".join(cr.get("container-title") or [])),
            "source_label": r["source_label"],
            "study_design": r["study_design"],
            "license": license_of(xmls[r["pmcid"]]),
            "doi_verified": "crossref",
            "title_match": round(ov, 2),
            "full_text_read": "yes",
            "full_text_url": f"https://europepmc.org/article/PMC/{r['pmcid']}",
            "access_date": ACCESS_DATE,
            "n_rows": 0 if is_t else 1,
            "n_threshold_rows": 1 if is_t else 0,
        }
    for i, s in enumerate(sorted(sources.values(), key=lambda s: (s["first_author"].lower(), s["year"] or 0)), 1):
        s["source_id"] = f"S{i:02d}"
    sid = {d: s["source_id"] for d, s in sources.items()}

    # ---- cosmetic unit spelling (micro sign, litre case); meaning unchanged
    for r in rows:
        u = r["unit"].replace("\u03bc", "\u00b5")
        u = re.sub(r"(?<=[A-Za-zµ])/dl\b", "/dL", u)
        u = re.sub(r"(?<=[A-Za-zµ])/l\b", "/L", u)
        u = re.sub(r"(?<=[A-Za-zµ])/ml\b", "/mL", u)
        u = u.replace("pM/L", "pmol/L")
        if u.startswith("not printed with estimate"):
            u = "not stated in source"
        r["unit"] = u
        r["measure_group"] = measure_group(r["measure"], r["comparator"])

    # ---- pair labels
    for r in rows:
        if r["marker_slug"]:
            r["pair_biomarker"] = markers[r["marker_slug"]]["canonical_name"]
        else:
            low = r["biomarker"].lower()
            r["pair_biomarker"] = next((lab for pat, lab in UNSLUGGED_PAIR if re.search(pat, low)), r["biomarker"])
        r["pair_key"] = f"{r['supplement']}|{r['marker_slug'] or r['pair_biomarker']}"

    # ---- effects.csv
    out_cols = ["row_id", "supplement", "form", "marker_slug", "biomarker", "pair_biomarker",
                "effect_kind", "dose_text", "dose_min", "dose_max", "dose_unit",
                "duration_text", "duration_min_weeks", "duration_max_weeks",
                "population", "baseline_status", "comparator", "measure", "measure_group",
                "effect", "ci_lo", "ci_hi", "unit", "k_trials", "n", "i2",
                "slope", "slope_unit", "certainty", "study_design",
                "source_id", "doi", "pmcid", "source_label", "location",
                "full_text_read", "access_date", "evidence_quote", "evidence_quote_status", "notes"]
    rows.sort(key=lambda r: (r["supplement"].lower(), r["pair_biomarker"].lower(), r["row_id"]))
    (HERE / "data").mkdir(exist_ok=True)

    def fmt(v):
        return "" if v is None else str(v)

    with (HERE / "data" / "effects.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(out_cols)
        for r in rows:
            rr = dict(r, source_id=sid[r["doi"]], full_text_read="yes", access_date=ACCESS_DATE,
                      evidence_quote=norm_ws(r["quote"]) if r["quote_ok"] else "",
                      evidence_quote_status="included" if r["quote_ok"]
                      else f"withheld: source licence is {r['license']}; see location")
            w.writerow([fmt(rr[c]) for c in out_cols])

    src_cols = ["source_id", "doi", "pmcid", "title", "first_author", "year", "journal", "source_label",
                "study_design", "license", "doi_verified", "title_match", "full_text_read",
                "full_text_url", "access_date", "n_rows", "n_threshold_rows"]
    with (HERE / "data" / "sources.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(src_cols)
        for s in sorted(sources.values(), key=lambda s: s["source_id"]):
            w.writerow([fmt(s[c]) for c in src_cols])

    # ---- data/biotin_interference_thresholds.csv
    t_cols = [c for c in THRESH_COLS if c not in ("quote",)] + [
        "source_id", "full_text_read", "access_date", "evidence_quote", "evidence_quote_status"]
    t_path = HERE / "data" / "biotin_interference_thresholds.csv"
    if thresholds:
        with t_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(t_cols)
            for t in sorted(thresholds, key=lambda t: (t["analyte"].lower(), t["platform"].lower(), t["row_id"])):
                tt = dict(t, source_id=sid[t["doi"]], full_text_read="yes", access_date=ACCESS_DATE,
                          evidence_quote=norm_ws(t["quote"]) if t["quote_ok"] else "",
                          evidence_quote_status="included" if t["quote_ok"]
                          else f"withheld: source licence is {t['license']}; see location")
                w.writerow([tt[c] for c in t_cols])
    elif t_path.exists():
        t_path.unlink()

    # ---- web JSON
    pairs: dict[str, dict] = {}
    for r in rows:
        p = pairs.setdefault(r["pair_key"], {
            "supplement": r["supplement"], "forms": [], "marker_slug": r["marker_slug"] or None,
            "biomarker": r["pair_biomarker"], "effect_kinds": [], "rows": [],
        })
        if r["form"] and r["form"] not in p["forms"]:
            p["forms"].append(r["form"])
        if r["effect_kind"] not in p["effect_kinds"]:
            p["effect_kinds"].append(r["effect_kind"])
        dur = None
        if r["duration_min_weeks"] is not None and fl(r["duration_min_weeks"]) == fl(r["duration_max_weeks"]):
            dur = fl(r["duration_min_weeks"])
        row = {
            "id": r["row_id"],
            "form": r["form"] or None,
            "biomarker_as_reported": r["biomarker"],
            "dose": r["dose_text"] or None,
            "dose_range": [fl(r["dose_min"]), fl(r["dose_max"])] if r["dose_min"] is not None or r["dose_max"] is not None else None,
            "dose_unit": r["dose_unit"] or None,
            "duration_weeks": dur,
            "duration_range_weeks": [fl(r["duration_min_weeks"]), fl(r["duration_max_weeks"])]
            if (r["duration_min_weeks"] is not None or r["duration_max_weeks"] is not None) else None,
            "duration": r["duration_text"] or None,
            "population": r["population"],
            "baseline_status": r["baseline_status"] or None,
            "comparator": r["comparator"] or None,
            "effect": fl(r["effect"]),
            "ci": [fl(r["ci_lo"]), fl(r["ci_hi"])] if r["ci_lo"] is not None else None,
            "unit": r["unit"],
            "measure": r["measure"],
            "measure_group": r["measure_group"],
            "k_trials": fl(r["k_trials"]),
            "n": fl(r["n"]),
            "i2": fl(r["i2"]),
            "effect_kind": r["effect_kind"],
            "study_design": r["study_design"],
            "doi": r["doi"],
            "source_label": r["source_label"],
            "location": r["location"],
        }
        if r["slope"] is not None:
            row["slope"] = {"value": fl(r["slope"]), "unit": r["slope_unit"] or None}
        if r["certainty"]:
            row["certainty"] = r["certainty"]
        if r["notes"]:
            row["notes"] = r["notes"]
        p["rows"].append(row)
    for p in pairs.values():
        p["form"] = "; ".join(p["forms"]) if p["forms"] else None
    web = {
        "version": VERSION,
        "generated": ACCESS_DATE,
        "description": "Average effects of supplements on blood biomarkers as reported in meta-analyses "
                       "and trials, one row per published estimate.",
        "license": "CC BY 4.0",
        "source": "https://lifefrom.ai",
        "counts": {"pairs": len(pairs), "rows": len(rows), "sources": len(sources),
                   "biotin_thresholds": len(thresholds)},
        "pairs": sorted(pairs.values(), key=lambda p: (p["supplement"].lower(), p["biomarker"].lower())),
        "biotin_thresholds": [
            {"id": t["row_id"], "analyte": t["analyte"], "marker_slug": t["marker_slug"] or None,
             "assay": t["assay"] or None, "platform": t["platform"], "manufacturer": t["manufacturer"] or None,
             "assay_format": t["assay_format"] or None,
             "threshold": fl(t["threshold_value"] or None), "threshold_unit": t["threshold_unit"] or None,
             "threshold_basis": t["threshold_basis"] or None,
             "bias_at_threshold_pct": t["bias_at_threshold_pct"] or None, "direction": t["direction"] or None,
             "tested_concentrations": t["tested_concentrations"] or None,
             "study_design": t["study_design"], "doi": t["doi"], "source_label": t["source_label"],
             "location": t["location"], **({"notes": t["notes"]} if t["notes"] else {})}
            for t in sorted(thresholds, key=lambda t: (t["analyte"].lower(), t["platform"].lower(), t["row_id"]))
        ],
    }
    (HERE / "web").mkdir(exist_ok=True)
    (HERE / "web" / "supplement-effects.json").write_text(
        json.dumps(web, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ---- checksums
    targets = sorted(
        [p for p in HERE.rglob("*") if p.is_file()
         and ".git" not in p.parts and p.name != "SHA256SUMS"
         and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts and ".venv" not in p.parts
         and "withheld" not in p.relative_to(HERE).parts]
    )
    lines = []
    for p in targets:
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(HERE).as_posix()}")
    (HERE / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    kinds = {}
    for r in rows:
        kinds[r["effect_kind"]] = kinds.get(r["effect_kind"], 0) + 1
    shipped = sum(1 for r in rows if r["quote_ok"])
    unchecked = [r["row_id"] for r in rows + thresholds if r.get("unchecked")]
    if unchecked:
        print(f"rows not checked against an excerpt (excerpt withheld, file absent): {len(unchecked)}")
    print(f"biotin threshold rows {len(thresholds)}")
    print(f"rows {len(rows)}  pairs {len(pairs)}  sources {len(sources)}  kinds {kinds}  "
          f"excerpts shipped {shipped}  withheld {len(rows) - shipped}")


if __name__ == "__main__":
    main()
