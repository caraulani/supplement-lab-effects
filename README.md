---
license: cc-by-4.0
pretty_name: Supplement–biomarker effects
language:
  - en
size_categories:
  - n<1K
task_categories:
  - tabular-classification
tags:
  - dietary-supplements
  - biomarkers
  - meta-analysis
  - randomized-controlled-trials
  - effect-size
  - laboratory-medicine
  - assay-interference
  - nutrition
configs:
  - config_name: effects
    data_files: data/effects.csv
    default: true
  - config_name: sources
    data_files: data/sources.csv
---

# Supplement–biomarker effects

Interactive version: https://lifefrom.ai/research/open-data/supplement-effects

Version 1.0.0, released 2026-11-25, by LifeFrom (https://lifefrom.ai) and Julian Caraulani.

This dataset answers one question: if people take supplement X at dose D for T weeks, how much does blood biomarker Y change on average in randomised trials? Each row is one published estimate, copied from the full text of an open-access meta-analysis or trial, with its DOI and its table or figure location. Where the source is CC BY or CC0 (122 of 212 rows), the row also carries a short verbatim excerpt that contains the number.

The table describes average effects observed in trial populations.

## Contents

| | Count |
|---|---:|
| Supplement × biomarker pairs | 86 |
| Rows (published estimates) | 212 |
| Sources (distinct DOIs, all full text read) | 69 (60 for effects, 9 for biotin thresholds) |
| Rows whose 95% CI includes zero (difference measures) | 52 |
| Assay interference rows (biotin, in people who took it) | 16 |
| Rows joined to a LifeFrom `marker_slug` | 184 |
| Biotin interference threshold rows (in vitro, per assay) | 36 |

Supplements covered: vitamin D (and D2 vs D3), vitamin K, omega-3 (EPA+DHA), coenzyme Q10, iron, vitamin B12, folic acid, combined B vitamins, magnesium, zinc, psyllium, oat beta-glucan, mixed soluble fibre, plant sterols/stanols, red yeast rice, berberine, creatine and biotin. `web/supplement-effects.json` groups the rows by pair.

A second, smaller table (`data/biotin_interference_thresholds.csv`) lists, per immunoassay and platform, the serum biotin concentration at which laboratory studies that added biotin to serum saw a bias above 10%.

## Who it is for

- Nutrition researchers and trial designers who need expected effect sizes, for example for power calculations.
- Dietitians and educators who want the average size of an effect with its uncertainty and its source.
- Clinical laboratories that need to know which supplements shift a result, including assay artefacts (biotin in streptavidin–biotin immunoassays) and analyte changes that are not disease (creatine raising serum creatinine).
- Developers who need a machine-readable, DOI-linked table.

## Files

| File | What it is |
|---|---|
| `data/effects.csv` | One row per published estimate. Main table. |
| `data/sources.csv` | One row per source: DOI, PMCID, title, first author, year, journal, design, article licence, verification status, and how many rows it gives to each table. |
| `data/biotin_interference_thresholds.csv` | One row per assay × platform: serum biotin concentration at which bias exceeded 10% in spiking studies. |
| `web/supplement-effects.json` | Compact JSON grouped by pair, for the lifefrom.ai website. |
| `curation/extract_*.csv`, `curation/biotin_thresholds.csv` | Extraction sheets that the build reads (excerpts blank for sources that are not CC BY or CC0). |
| `curation/excluded_*.csv` | Papers considered and not used, with the reason. |
| `scripts/` | `build.py` rebuilds every output and runs the checks; `fetch_fulltext.py`, `search_epmc.py`, `verify_quotes.py` and `split_quotes.py` are helpers. |
| `tests/` | Checks (`uv run --no-project --with pytest pytest -q tests`). |
| `METHODS.md` | How to rebuild it and get the same numbers. |

### `data/effects.csv` columns

| Column | Meaning |
|---|---|
| `row_id` | Stable row identifier (group letter + number). |
| `supplement`, `form` | Supplement and form as described by the source (e.g. "D3 (cholecalciferol)", "ferrous sulfate"). |
| `marker_slug` | LifeFrom marker key from release 1 `markers.csv`; blank when LifeFrom has no such marker (e.g. Omega-3 Index, dp-ucMGP, plasma CoQ10, measured GFR). |
| `biomarker` | Biomarker as the source names it. |
| `pair_biomarker` | Label used to group rows into pairs (LifeFrom canonical name where a slug exists). |
| `effect_kind` | `physiological` or `assay_interference`. |
| `dose_text`, `dose_min`, `dose_max`, `dose_unit` | Dose as described, and numeric bounds where stated. |
| `duration_text`, `duration_min_weeks`, `duration_max_weeks` | Duration as described; weeks only where stated in weeks or days. |
| `population`, `baseline_status` | Who was studied and their baseline status where reported (e.g. deficient vs replete). |
| `comparator` | Placebo, control, baseline, another route, etc. |
| `measure` | Effect measure as reported (MD, WMD, SMD, percent change, dose-response slope, within-arm change, …). |
| `measure_group` | Coarse class for filtering: `mean_difference_vs_control`, `standardised_mean_difference`, `percent_difference_vs_control`, `dose_response_point`, `dose_response_slope`, `within_arm_change`, `within_person_on_vs_off`, `ratio_vs_control`, `other`. |
| `effect`, `ci_lo`, `ci_hi`, `unit` | Effect and 95% CI exactly as printed, in the printed unit. `SD` for SMDs. `not stated in source` where the paper gives no unit. |
| `k_trials`, `n`, `i2` | Number of trials (or arms/comparisons where the notes say so), participants, I² (%). Blank if not reported for that estimate. |
| `slope`, `slope_unit` | Dose-response slope where the source reports one. |
| `certainty` | GRADE or the authors' certainty rating, where reported. |
| `study_design` | Design of the source. |
| `source_id`, `doi`, `pmcid`, `source_label`, `location` | Source and where in it the number is. |
| `full_text_read`, `access_date` | Always `yes` and `2026-11-25` in this release. |
| `evidence_quote` | Verbatim excerpt(s) from the full text containing the numbers; several are separated by ` || `. Included only when the source is CC BY or CC0; blank otherwise. |
| `evidence_quote_status` | `included`, or `withheld: source licence is …` for sources under other licences. |
| `notes` | Short factual notes: caveats, sign conventions, inconsistencies in the source. |

### `data/biotin_interference_thresholds.csv` columns

| Column | Meaning |
|---|---|
| `row_id` | T + number. |
| `analyte`, `marker_slug` | Analyte, and LifeFrom marker key where one exists. |
| `assay`, `platform`, `manufacturer`, `assay_format` | Reagent, analyser, maker, and sandwich or competitive format. |
| `threshold_value`, `threshold_unit` | Serum biotin concentration at which bias exceeded 10%, as printed. Blank when no tested level exceeded 10%. |
| `threshold_basis` | `authors' stated threshold for >10% bias`, or `lowest tested concentration with |bias| >10%` (all rows in 1.0.0 use the second). The true threshold lies between that level and the next lower tested level. |
| `bias_at_threshold_pct`, `direction` | Bias at that level and its sign (falsely low or high). |
| `tested_concentrations` | Biotin levels tested; for rows with no threshold the highest is the limit of what is known. |
| `sample_type`, `study_design` | Mostly pooled serum spiked with biotin in vitro. |
| `source_id`, `doi`, `pmcid`, `source_label`, `location`, `evidence_quote`, `evidence_quote_status`, `notes` | As in `effects.csv`. |

These are concentrations in serum, not doses. The serum level reached after a given dose depends on the dose, the timing of the blood draw and the person.

### `web/supplement-effects.json`

```
{version, generated, description, license, source, counts:{pairs, rows, sources},
 pairs:[{supplement, form, forms[], marker_slug, biomarker, effect_kinds[],
   rows:[{id, form, biomarker_as_reported, dose, dose_range, dose_unit, duration_weeks,
          duration_range_weeks, duration, population, baseline_status, comparator,
          effect, ci:[lo,hi], unit, measure, measure_group, k_trials, n, i2,
          slope?:{value, unit}, certainty?, effect_kind, study_design, doi,
          source_label, location, notes?}]}],
 biotin_thresholds:[{id, analyte, marker_slug, assay, platform, manufacturer, assay_format,
   threshold, threshold_unit, threshold_basis, bias_at_threshold_pct, direction,
   tested_concentrations, study_design, doi, source_label, location, notes?}]}
```

`duration_weeks` is a single number only when the source gives one duration; ranges are in `duration_range_weeks`.

## How it was built

Open-access meta-analyses of randomised trials were found through Europe PMC, with dose-response meta-analyses preferred, then large trials. For biotin, a nonrandomised crossover study and a withdrawal study were used because no randomised trial measured assay bias. The biotin threshold table uses laboratory studies in which biotin was added to serum. Numbers were copied only from full texts downloaded on 2026-11-25. Every row has an excerpt that the build checks against the saved full text; excerpts from sources that are not CC BY or CC0 are kept out of the distributed files. Each DOI was checked against Crossref and against the DOI printed in the article. Full details are in `METHODS.md`.

## How to read a row

- A mean difference (MD/WMD) of −0.20 % for HbA1c means the supplement group ended 0.20 percentage points lower than control on average across the pooled trials.
- An SMD is in standard-deviation units and cannot be read as a lab value without a reference SD.
- Within-arm changes (`within_arm_change`) are not placebo-controlled differences; the notes give the placebo change where the source does.
- Rows from different sources for the same pair often pool overlapping trials. Do not combine them.

## Limitations

- These are averages across trials. Individual responses vary, often widely, and depend on baseline status, body weight, adherence, assay and the product used.
- Populations differ between rows (healthy adults, type 2 diabetes, chronic kidney disease, pregnancy, athletes). Check `population` before comparing rows.
- Some sources pool non-randomised studies or active comparators; `study_design`, `comparator` and `notes` say so.
- Several sources contradict themselves (text vs table, abstract vs results). The notes record each one and which figure was used.
- Ten rows have no unit because the source does not print one next to the estimate; they are marked `not stated in source`. Three rows keep a unit that is probably a misprint in the source (ferritin in µmol/L, zinc-trial lipids in µg/dL), marked "as printed" in `unit`.
- Interference rows are specific to the named assay platform and the biotin dose and timing studied. The biotin rows come from small studies (6 and 57 people). No open-access study gave quantitative bias in people taking 100–300 mg/day.
- The Omega-3 Index pair rests on five trials and one network meta-analysis; Harris and colleagues' dose-response model (Walker 2019, AJCN) is not open access and is absent.
- Vitamin K × INR rows describe INR stability (time in therapeutic range, INR variability) in people on vitamin K antagonists, from one RCT and one Cochrane review of one RCT.
- Only open-access full texts were used. Some well-known meta-analyses were not open access and are absent (listed in `curation/excluded_*.csv`).

## Licence

Data: CC BY 4.0. Code: MIT. Verbatim excerpts (`evidence_quote`) are included only for sources published under CC BY or CC0, and they stay under that source licence. For sources under any other licence (CC BY-NC, CC BY-NC-ND, publisher terms) the excerpt is blank; the number, DOI and table or figure location are still given, so it can be checked against the article. See `LICENSE`.

## How to cite

LifeFrom; Caraulani, J. (2026). *Supplement–biomarker effects: average changes in blood biomarkers in randomised trials of supplements, with source DOIs* (Version 1.0.0) [Data set]. https://github.com/caraulani/supplement-lab-effects

When you use a specific number, please also cite the source publication named in that row.
