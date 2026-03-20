---
title: Benchmark Report 2026-03-19
description: Matrix benchmark results across audiences, styles, slide counts, and languages using multiple papers
ms.date: 2026-03-19
ms.topic: reference
---

## Metric Definitions

This report includes operational and quality metrics computed from each run manifest and quality-gate summary.

| Metric | Definition | Interpretation |
| --- | --- | --- |
| total_runs | Number of matrix runs executed in this benchmark report. | Higher means broader coverage of scenario combinations. |
| completed_runs | Number of runs whose status starts with completed (including completed_with_warnings and failed_with_quality_gate where pipeline execution reached completion). | Distinguishes workflow completion from hard execution failures. |
| quality_gate_pass_count | Number of runs where quality_gate.passed is true in run_summary. | Direct count of runs that satisfied configured quality thresholds. |
| quality_gate_pass_rate | quality_gate_pass_count / total_runs. | Primary reliability indicator for generated deck quality across scenarios. |
| avg_duration_minutes | Mean run duration across all runs, converted from duration_ms. | Higher values indicate slower end-to-end generation for selected scenarios. |
| avg_bullet_exact_unique_ratio | Mean ratio of unique bullet strings after exact-match normalization, taken from quality metrics. | Values closer to 1.0 indicate less exact bullet repetition. |
| avg_bullet_near_duplicate_pair_count | Mean number of bullet-pair matches flagged as near-duplicates within a run. | Lower values indicate fewer semantically repetitive bullet pairs. |
| image_gen_effective_true_count | Number of runs where effective image generation was enabled at execution time. | Confirms whether image generation control policy was actually applied. |

### Breakdown Metric Notes

Each breakdown table (by audience, style, target_slide_count, language, and paper) uses the same aggregation logic:

* runs: Number of benchmark rows in that bucket.
* quality_gate_pass_rate: Mean of per-run pass flags in that bucket.
* avg_bullet_exact_unique_ratio: Mean exact uniqueness ratio in that bucket.
* avg_bullet_near_duplicate_pair_count: Mean near-duplicate bullet-pair count in that bucket.
* avg_duration_minutes: Mean duration in minutes in that bucket.

### Important Caveats

* These metrics are diagnostic proxies; they are useful for trend detection but do not fully capture pedagogical quality, factual accuracy, or narrative coherence.
* quality_gate_pass_rate is threshold-dependent and can change when gate criteria are tuned.
* Repetition metrics are sensitive to language, domain terminology, and slide target size, so cross-bucket comparisons should be interpreted with context.

## Run Metadata

* Benchmark ID: benchmark_20260319_214229
* Generated at: 2026-03-20T01:30:51.026551+00:00
* Runs planned: 24/w gm 
* Runs executed: 24

## Overall Results

| total_runs | completed_runs | quality_gate_pass_count | quality_gate_pass_rate | avg_duration_minutes | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | image_gen_effective_true_count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | 14 | 14 | 0.5833 | 9.501 | 0.9572 | 0.75 | 0 |

## Breakdown by Audience

| audience | runs | quality_gate_pass_rate | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | avg_duration_minutes |
| --- | --- | --- | --- | --- | --- |
| executive_nontechnical | 6 | 0.8333 | 0.8288 | 1.5 | 17.612 |
| research_specialists | 6 | 0.5 | 1.0 | 0.167 | 6.823 |
| students | 6 | 0.3333 | 1.0 | 1 | 6.788 |
| technical_adjacent | 6 | 0.6667 | 1.0 | 0.333 | 6.78 |

## Breakdown by Style

| presentation_style | runs | quality_gate_pass_rate | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | avg_duration_minutes |
| --- | --- | --- | --- | --- | --- |
| executive_friendly | 6 | 0.3333 | 0.8288 | 1.667 | 17.705 |
| journal_club | 6 | 0.8333 | 1.0 | 0.667 | 6.946 |
| teaching | 6 | 0.1667 | 1.0 | 0.333 | 6.745 |
| technical_summary | 6 | 1.0 | 1.0 | 0.333 | 6.606 |

## Breakdown by Slide Target

| target_slide_count | runs | quality_gate_pass_rate | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | avg_duration_minutes |
| --- | --- | --- | --- | --- | --- |
| 12 | 9 | 0.6667 | 1.0 | 0.667 | 6.788 |
| 18 | 9 | 0.2222 | 0.8858 | 1.222 | 13.989 |
| 8 | 6 | 1.0 | 1.0 | 0.167 | 6.838 |

## Breakdown by Language

| language | runs | quality_gate_pass_rate | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | avg_duration_minutes |
| --- | --- | --- | --- | --- | --- |
| en | 12 | 0.6667 | 0.9144 | 0.917 | 12.282 |
| es | 12 | 0.5 | 1.0 | 0.583 | 6.72 |

## Breakdown by Paper

| paper | runs | quality_gate_pass_rate | avg_bullet_exact_unique_ratio | avg_bullet_near_duplicate_pair_count | avg_duration_minutes |
| --- | --- | --- | --- | --- | --- |
| 1706.03762v7.pdf | 8 | 0.5 | 0.875 | 0.375 | 15.19 |
| 2602.11865v1.pdf | 8 | 0.625 | 1.0 | 0.375 | 7.991 |
| Nowcasting_Econ-Report-v16.pdf | 8 | 0.625 | 0.9966 | 1.5 | 5.321 |

## TODO Conclusions

* Bullet repetitiveness status: needs_more_validation
* Recommendation: keep repetition item as validation-focused until repeated multilingual and multi-style runs stay within quality thresholds.
* Image generation control status: verified. Effective image generation remained disabled unless explicitly enabled.

## Raw Artifact Pointers

* Raw JSON: C:\Users\ricastro\OneDrive - Microsoft\paper2slides\backend\runs\benchmark_20260319_214229\benchmark_results.json
* Raw CSV: C:\Users\ricastro\OneDrive - Microsoft\paper2slides\backend\runs\benchmark_20260319_214229\benchmark_results.csv
