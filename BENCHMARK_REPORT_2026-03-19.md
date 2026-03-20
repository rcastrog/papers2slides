---
title: Benchmark Report 2026-03-19
description: Matrix benchmark results across audiences, styles, slide counts, and languages using multiple papers
ms.date: 2026-03-19
ms.topic: reference
---

## Run Metadata

* Benchmark ID: benchmark_20260319_214229
* Generated at: 2026-03-20T01:30:51.026551+00:00
* Runs planned: 24
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
