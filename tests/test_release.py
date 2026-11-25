"""Checks for the supplement-lab-effects release.

Run: uv run --no-project --with pytest pytest -q tests
Tests that need the raw downloads (_raw/) skip when they are absent.
"""
from __future__ import annotations

import csv
import hashlib
import json
import pathlib
import re

import pytest

HERE = pathlib.Path(__file__).resolve().parent.parent
RAW = HERE.parent / "_raw"
EPMC = RAW / "europepmc"
MARKERS = RAW / "lifefrom-release-1" / "markers.csv"


def read_csv(p):
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def effects():
    return read_csv(HERE / "data" / "effects.csv")


@pytest.fixture(scope="module")
def sources():
    return read_csv(HERE / "data" / "sources.csv")


@pytest.fixture(scope="module")
def web():
    return json.loads((HERE / "web" / "supplement-effects.json").read_text(encoding="utf-8"))


def f(v):
    return None if v == "" else float(v)


def test_target_size(effects, web):
    assert web["counts"]["pairs"] >= 30
    assert len(effects) >= web["counts"]["pairs"]


def test_row_ids_unique(effects):
    ids = [r["row_id"] for r in effects]
    assert len(ids) == len(set(ids))


def test_required_fields(effects):
    for r in effects:
        for c in ("supplement", "biomarker", "effect_kind", "population", "measure", "unit",
                  "study_design", "doi", "pmcid", "source_label", "location", "evidence_quote_status"):
            assert r[c], (r["row_id"], c)
        assert r["effect_kind"] in {"physiological", "assay_interference"}
        assert r["full_text_read"] == "yes"
        assert r["access_date"] == "2026-11-25"
        assert r["effect"] or r["slope"], r["row_id"]


def test_numbers(effects):
    for r in effects:
        e, lo, hi = f(r["effect"]), f(r["ci_lo"]), f(r["ci_hi"])
        assert (lo is None) == (hi is None), r["row_id"]
        if lo is not None and e is not None:
            assert lo <= e <= hi, r["row_id"]
        if r["i2"]:
            assert 0 <= float(r["i2"]) <= 100
        for c in ("k_trials", "n"):
            if r[c]:
                assert float(r[c]) > 0 and float(r[c]).is_integer(), (r["row_id"], c)
        if r["dose_min"] and r["dose_max"]:
            assert float(r["dose_min"]) <= float(r["dose_max"]), r["row_id"]
        if r["duration_min_weeks"] and r["duration_max_weeks"]:
            assert float(r["duration_min_weeks"]) <= float(r["duration_max_weeks"]), r["row_id"]


def test_doi_format_and_sources(effects, sources):
    by_doi = {s["doi"]: s for s in sources}
    for r in effects:
        assert re.fullmatch(r"10\.\d{4,9}/\S+", r["doi"]), r["doi"]
        assert r["doi"] in by_doi
        assert by_doi[r["doi"]]["source_id"] == r["source_id"]
    for s in sources:
        assert s["doi_verified"] == "crossref"
        assert float(s["title_match"]) >= 0.6
        assert s["full_text_read"] == "yes"
        assert int(s["n_rows"]) == sum(1 for r in effects if r["doi"] == s["doi"])


def test_interference_category_present(effects):
    kinds = {r["effect_kind"] for r in effects}
    assert kinds == {"physiological", "assay_interference"}


def test_null_findings_present(effects):
    nulls = [r for r in effects if r["ci_lo"] and float(r["ci_lo"]) <= 0 <= float(r["ci_hi"])
             and "ratio" not in r["measure"].lower()]
    assert len(nulls) >= 3


@pytest.mark.skipif(not MARKERS.exists(), reason="release-1 markers not present")
def test_marker_slugs_join():
    slugs = {r["marker_slug"] for r in read_csv(MARKERS)}
    for r in read_csv(HERE / "data" / "effects.csv"):
        if r["marker_slug"]:
            assert r["marker_slug"] in slugs, r["marker_slug"]


WITHHELD = HERE / "curation" / "withheld" / "full_quotes.csv"


def full_quotes(effects):
    """Shipped excerpts, plus withheld ones from curation/withheld/ when that file is present."""
    out = {r["row_id"]: r["evidence_quote"] for r in effects if r["evidence_quote"]}
    if WITHHELD.exists():
        for q in read_csv(WITHHELD):
            out.setdefault(q["row_id"], q["quote"])
    return out


OPEN_LICENCE = re.compile(r"CC BY( [0-9.]+| \(version not stated\))?|CC0 1\.0")


def test_no_restricted_excerpt_ships(effects, sources):
    lic = {s["doi"]: s["license"] for s in sources}
    shipped = withheld = 0
    for r in effects:
        if OPEN_LICENCE.fullmatch(lic[r["doi"]]):
            assert r["evidence_quote"] and r["evidence_quote_status"] == "included", r["row_id"]
            shipped += 1
        else:
            assert r["evidence_quote"] == "", r["row_id"]
            assert r["evidence_quote_status"].startswith("withheld"), r["row_id"]
            withheld += 1
    assert shipped and withheld
    # distributed curation files must not carry restricted excerpts either
    restricted = {s["pmcid"] for s in sources if not OPEN_LICENCE.fullmatch(s["license"])}
    for p in (HERE / "curation").glob("extract_*.csv"):
        for r in read_csv(p):
            if r["pmcid"] in restricted:
                assert r["quote"] == "", (p.name, r["row_id"])
    thr = HERE / "data" / "biotin_interference_thresholds.csv"
    if thr.exists():
        for t in read_csv(thr):
            if OPEN_LICENCE.fullmatch(lic[t["doi"]]):
                assert t["evidence_quote"] and t["evidence_quote_status"] == "included", t["row_id"]
            else:
                assert t["evidence_quote"] == "" and t["evidence_quote_status"].startswith("withheld"), t["row_id"]
    cthr = HERE / "curation" / "biotin_thresholds.csv"
    if cthr.exists():
        for t in read_csv(cthr):
            if t["pmcid"] in restricted:
                assert t["quote"] == "", t["row_id"]
    web_text = (HERE / "web" / "supplement-effects.json").read_text(encoding="utf-8")
    assert "evidence_quote" not in web_text and '"quote"' not in web_text


@pytest.mark.skipif(not WITHHELD.exists(), reason="withheld-excerpt file not present (not distributed)")
def test_every_row_has_full_excerpt(effects):
    fq = full_quotes(effects)
    assert {r["row_id"] for r in effects} <= set(fq)


@pytest.mark.skipif(not EPMC.exists(), reason="raw full texts not present")
def test_quotes_in_full_text(effects):
    cache = {}
    fq = full_quotes(effects)
    for r in effects:
        if r["row_id"] not in fq:
            continue
        p = EPMC / f"{r['pmcid']}.txt"
        if not p.exists():
            pytest.skip(f"{p} missing")
        if r["pmcid"] not in cache:
            cache[r["pmcid"]] = re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))
        for q in fq[r["row_id"]].split(" || "):
            q = re.sub(r"\s+", " ", q).strip()
            assert q in cache[r["pmcid"]], (r["row_id"], q[:80])


def test_web_matches_csv(effects, web):
    assert web["version"] == "1.0.0"
    rows = [row for p in web["pairs"] for row in p["rows"]]
    assert len(rows) == len(effects) == web["counts"]["rows"]
    assert len(web["pairs"]) == web["counts"]["pairs"]
    by_id = {r["row_id"]: r for r in effects}
    for p in web["pairs"]:
        for k in ("supplement", "form", "marker_slug", "biomarker", "rows"):
            assert k in p
        for row in p["rows"]:
            for k in ("dose", "dose_unit", "duration_weeks", "population", "effect", "ci", "unit",
                      "measure", "k_trials", "n", "i2", "effect_kind", "doi", "source_label", "location"):
                assert k in row, k
            c = by_id[row["id"]]
            assert row["doi"] == c["doi"]
            assert (row["effect"] is None and c["effect"] == "") or row["effect"] == float(c["effect"])
            if row["ci"]:
                assert row["ci"] == [float(c["ci_lo"]), float(c["ci_hi"])]


ADVICE = re.compile(
    r"\b(you should|we recommend|is recommended|should take|should be taken|take \d|"
    r"start taking|stop taking|ideal dose|optimal dose|best dose|you need)\b", re.I)


def test_no_advice_wording(web):
    texts = [json.dumps(web, ensure_ascii=False)]
    for name in ("README.md", "METHODS.md"):
        p = HERE / name
        if p.exists():
            texts.append(p.read_text(encoding="utf-8"))
    for t in texts:
        m = ADVICE.search(t)
        assert m is None, t[max(0, m.start() - 80): m.end() + 80]


def test_checksums():
    lines = (HERE / "SHA256SUMS").read_text(encoding="utf-8").strip().splitlines()
    assert lines
    for line in lines:
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((HERE / rel).read_bytes()).hexdigest() == digest, rel


def test_numbers_appear_in_quote(effects):
    fq = full_quotes(effects)
    for r in effects:
        if r["row_id"] not in fq:
            continue
        q = re.sub(r"\s+", " ", fq[r["row_id"]]).replace("·", ".")
        for c in ("effect", "ci_lo", "ci_hi", "i2", "slope"):
            v = r[c].lstrip("-")
            if not v:
                continue
            forms = {v} | ({v[1:]} if v.startswith("0.") else set())
            assert any(re.search(r"(?<![\d.])" + re.escape(x) + r"(?![\d])", q) for x in forms), (r["row_id"], c, v)


def test_biotin_thresholds(sources, web):
    p = HERE / "data" / "biotin_interference_thresholds.csv"
    if not p.exists():
        pytest.skip("no thresholds table")
    rows = read_csv(p)
    by_doi = {s["doi"]: s for s in sources}
    assert len(rows) == web["counts"]["biotin_thresholds"] == len(web["biotin_thresholds"])
    assert len({t["row_id"] for t in rows}) == len(rows)
    for t in rows:
        assert t["row_id"].startswith("T")
        assert t["doi"] in by_doi and by_doi[t["doi"]]["source_id"] == t["source_id"]
        assert t["analyte"] and t["platform"] and t["location"]
        if t["threshold_value"]:
            float(t["threshold_value"])
            assert t["threshold_unit"] and t["threshold_basis"] in {
                "authors' stated threshold for >10% bias", "lowest tested concentration with |bias| >10%"}, t["row_id"]
        else:
            assert t["tested_concentrations"] and "no >10% bias" in t["notes"], t["row_id"]
    for s in sources:
        assert int(s["n_threshold_rows"]) == sum(1 for t in rows if t["doi"] == s["doi"])
    if MARKERS.exists():
        slugs = {r["marker_slug"] for r in read_csv(MARKERS)}
        for t in rows:
            assert not t["marker_slug"] or t["marker_slug"] in slugs
