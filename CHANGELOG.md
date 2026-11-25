# Changelog

## 1.0.0 (2026-11-25)

First release.

- `data/effects.csv`: 212 published estimates across 86 supplement × biomarker pairs, from 60 open-access sources. Every number was copied from full text and checked against a verbatim excerpt. Null findings are included.
- 16 assay interference rows (biotin in streptavidin–biotin immunoassays) kept as their own `effect_kind`.
- `data/biotin_interference_thresholds.csv`: 36 assay × platform rows from 9 in vitro spiking studies.
- `data/sources.csv`: 69 sources, each DOI checked against Crossref and against the DOI printed in the article.
- `evidence_quote` is filled only for sources under CC BY or CC0 (122 effect rows and 4 threshold rows); `evidence_quote_status` gives the licence for the rest.
- `web/supplement-effects.json` for the lifefrom.ai website; build script and tests.
