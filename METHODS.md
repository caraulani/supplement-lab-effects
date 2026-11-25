# Methods

This file describes how the dataset was built, in enough detail to rebuild it and get the same numbers.

## Question

For a supplement X taken at dose D for T weeks, how much does blood biomarker Y change on average, compared with placebo or control, in randomised trials? The unit of the dataset is one published effect estimate (one row). Rows are grouped into supplement × biomarker pairs.

## Search

Searches ran on 2026-11-25 against the Europe PMC REST API (`https://www.ebi.ac.uk/europepmc/webservices/rest/search`), which indexes PubMed/MEDLINE and PubMed Central. Queries used title terms for the supplement, the biomarker or biomarker class, and "meta-analysis", restricted to open-access records (`OPEN_ACCESS:y`), sorted by citation count and by date. `scripts/search_epmc.py` reproduces a query. Example:

```
python3 -I scripts/search_epmc.py 'TITLE:"berberine" AND (TITLE:"meta-analysis") AND OPEN_ACCESS:y' 25
```

Search results change as the literature grows, so a rerun on a later date will list more papers. The set of papers actually used is fixed by `curation/extract_*.csv` and `data/sources.csv`.

## Selection

In order of preference:

1. Meta-analyses of randomised controlled trials, especially dose-response meta-analyses.
2. Large randomised trials, where no usable meta-analysis was open access.
3. For assay interference only: controlled experimental or crossover studies in which the supplement was given and assays were measured before and after.

A source was used only if its full text was open access in Europe PMC. Within a pair, a more recent, larger or better-reported meta-analysis was preferred over older or smaller ones. Papers considered and not used are listed with the reason in `curation/excluded_*.csv`.

## Extraction

1. The full text of each source was downloaded as JATS XML from `https://www.ebi.ac.uk/europepmc/webservices/rest/<PMCID>/fullTextXML` and rendered to plain text by `scripts/fetch_fulltext.py`. Table rows are kept as rows, with cells joined by ` | `. Six sources are free to read at PubMed Central but their publishers do not allow XML download (Li 2017 JAMA, PMC5818818, among them). These were rendered from the public PubMed Central web page instead; they are listed in `HTML_ONLY` in the script.
2. Each estimate was copied from the full text exactly as printed: effect, 95% CI, unit, number of trials (k), participants (n), I², dose-response slope and certainty rating. Nothing was converted between units, recalculated, rounded or read off a plot. Fields not reported for that specific estimate are blank. The review's total participant count is never entered against a subgroup estimate.
3. Subgroup estimates were kept when they describe dose, duration or baseline status (for example deficient vs replete).
4. Null and negative results were kept.
5. Each row has one or more verbatim excerpts (each under about 300 characters) that together contain the copied numbers, plus the location (table, figure legend, section). The excerpts are published in `evidence_quote` only for CC BY or CC0 sources. For other sources they are kept in a file that is not distributed (`curation/withheld/full_quotes.csv`) and the published field is blank.
6. `marker_slug` joins to LifeFrom release 1 (`markers.csv`) where the biomarker matches. Biomarkers with no LifeFrom marker (Omega-3 Index, dp-ucMGP, plasma CoQ10, and similar) have a blank slug and a pair label set in `scripts/build.py` (`UNSLUGGED_PAIR`).
7. `effect_kind` is `assay_interference` when the change is an artefact of the measurement (biotin in streptavidin–biotin immunoassays) and `physiological` otherwise. Creatine raises serum creatinine through conversion of creatine to creatinine; that is a real change in the analyte, so it is `physiological`, with a note that creatinine-based eGFR falls without evidence of a fall in measured kidney function where the source shows that.

8. Durations are given in weeks only when the source states weeks or days; durations in months are kept as text.
9. For paywalled papers, author manuscripts deposited in Europe PMC or PubMed Central were searched for and used when they were full text.
10. Within-person or single-arm rows (for example INR change after starting vitamin K in people on warfarin) were used only where no controlled estimate exists; `measure` and `comparator` say so.

## Biotin interference thresholds

`data/biotin_interference_thresholds.csv` comes from laboratory studies that added biotin to pooled serum (or removed it) and measured the bias on each immunoassay. Each row is one analyte × platform.

- `threshold_value` is the lowest tested biotin concentration at which the reported bias exceeded 10%, copied as printed, with the tested levels listed. We did not interpolate between tested levels or convert units.
- Where no tested level exceeded 10%, the threshold is blank and the notes give the highest level tested.
- The build checks that each threshold value appears in its excerpt.

## Verification (run by the build)

`scripts/build.py` refuses to build if any of these fail:

- every excerpt (published, or withheld when that file is present) is found in the saved full text after collapsing whitespace, and the effect, CI bounds, I² and slope each appear in it;
- no excerpt from a source that is not CC BY or CC0 appears in a distributed file;
- the row DOI equals the DOI printed in the full text;
- every DOI resolves at `https://api.crossref.org/works/<doi>` and the Crossref title shares at least 60% of its words with the full-text title (all sources in this release are well above that; see `title_match` in `data/sources.csv`);
- every `marker_slug` exists in `markers.csv`;
- effect lies inside its CI, I² is 0–100, and required fields are filled.

## Rebuild

Raw downloads are kept outside the repository, in a sibling folder `../_raw/`:

- `../_raw/europepmc/` full texts from Europe PMC (and the six PubMed Central pages), written by `scripts/fetch_fulltext.py`;
- `../_raw/crossref/` Crossref records, written by the build;
- `../_raw/lifefrom-release-1/markers.csv` the LifeFrom marker list used for the `marker_slug` join. The build requires it.

```
cd supplement-lab-effects
python3 -I scripts/build.py --refetch   # downloads full texts and Crossref records, then builds
uv run --no-project --with pytest pytest -q tests
```

Without `--refetch`, cached copies are used and anything missing is downloaded.

Excerpts from sources that are not CC BY or CC0 are not distributed. When `curation/withheld/full_quotes.csv` is absent, as in this repository, the build says so and does not check those rows against an excerpt; their DOI, licence, CI order, marker join and required fields are still checked, and every published excerpt is still checked against the full text. `scripts/split_quotes.py` moves such excerpts out of the extraction sheets after new rows are added.

## What the numbers mean

- `MD` / `WMD`: mean difference between supplement and control groups in the change (or end value) of the biomarker, in the printed unit. Negative means lower with the supplement.
- `SMD`: standardised mean difference, in standard deviation units. It cannot be turned back into a lab unit without a reference SD.
- `percent change` or `percent bias`: as defined in the source.
- `dose-response slope`: change in the biomarker per stated dose increment, as modelled by the source. Slopes describe the average across the included trials; they are usually non-linear at high doses and depend on baseline status.

## Known limits

- Average effects from trials. Individual responses vary widely.
- Trial populations differ (age, sex, baseline status, disease). The `population` and `baseline_status` fields give what the source states.
- Effects depend on the assay. This matters most for interference rows, which are platform-specific.
- Meta-analyses overlap in the trials they include. Do not pool rows from different sources for the same pair.
- Open-access restriction: some well-known meta-analyses (for example some Cochrane reviews) were not open access in Europe PMC and are not used.
