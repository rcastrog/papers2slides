---
title: Paper2Slides To Do
description: Pending implementation and validation tasks for Paper2Slides
ms.date: 2026-03-19
ms.topic: how-to
---

# To Do

## Critical

* [ ] Fix repetitiveness of bullets
* [x] Highlight repeated bullets (exact and near repeated)
* [x] Verify repeated bullets render yellow in Reveal and PPTX outputs
* [x] Verify near-repeated bullets render orange in Reveal and PPTX outputs

## High

* [x] Test in Spanish again
* [x] Try other modes and audiences
* [ ] Review truthfulness of reasons for citation
* [x] Keep image generation strictly controlled by UI option selection

## Medium

* [x] Add an icon for the UI so it is less generic
* [x] Set Run repair-on-audit to true by default
* [x] Keep generated images disabled by default unless explicitly enabled
* [x] More tests with different number of slides
* [ ] Test URL option
* [x] Compact verbose validation errors in run warnings and manifests

## Benchmark Notes (2026-03-19)

* Ran 24 real-mode benchmark jobs across 3 papers, 8 scenario combinations, 2 languages, and 3 slide targets (8/12/18)
* Quality-gate pass rate was 58.33% overall (14/24), with stronger results at 8-slide targets and weaker results at 18-slide targets
* Bullet repetitiveness remains validation-focused: average exact uniqueness 0.9572 and average near-duplicate pairs 0.75, with higher duplicate pressure in executive_friendly runs
* Image generation control verified: effective image generation stayed disabled in all benchmark runs unless explicitly enabled


## Low

* [ ] Add different PPTX templates
* [ ] Improve pictures in PPTX (not deformed)